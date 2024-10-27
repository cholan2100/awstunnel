import socket
import threading
import boto3
import json
import base64
import os
import logging

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def poll_sqs(queue_url, sqs_client):
    # logging.info(f'Polling SQS queue: {queue_url}')  # Log polling event
    response = sqs_client.receive_message(
        QueueUrl=queue_url,
        MaxNumberOfMessages=10,
        WaitTimeSeconds=1
    )
    return response

def forward_to_sqs(data, queue_url, sqs_client, event, destination):  # Added destination parameter
    if data is None:
        logging.info(f'Forwarding event: {event} to client on SQS queue')
    else:
        logging.info(f'Forwarding data on SQS queue') 
    message_body = json.dumps({
        "data": base64.b64encode(data).decode('utf-8') if data is not None else "None", 
        "event": event,
        "destination": destination  # Added destination to message body
    })
    response = sqs_client.send_message(
        QueueUrl=queue_url,
        MessageBody=message_body
    )
    return response

def receive_from_sqs(queue_url, sqs_client, connections, lock, return_queue_url):  # Added return_queue_url parameter
    while True:
        messages = poll_sqs(queue_url, sqs_client)
        
        if 'Messages' in messages:
            for message in messages['Messages']:
                logging.info(f'Body of the message: {message["Body"]}')  # Log the body of the message
                body = json.loads(message['Body'])
                destination = body['destination']
                event = body['event']
                if body['data'] != 'None':
                    request_data = base64.b64decode(body['data'])
                else:
                    request_data = None
                
                logging.info(f'Received message for destination: {destination}')  # Log received message
                
                target_addr, target_port = destination.split(':')
                target_port = int(target_port)
                
                with lock:
                    if event == 'connect':
                        logging.info(f'Handling connect event for destination: {destination}')  # Log connect event handling
                        if destination not in connections:
                            logging.info(f'Establishing new connection to destination: {destination}')  # Log new connection establishment
                            try:
                                new_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                                new_socket.connect((target_addr, target_port))
                                connections[destination] = new_socket
                                forward_to_sqs(None, return_queue_url, sqs_client, event='connected', destination=destination)  # Send empty data and event
                                target_socket = new_socket
                            except socket.error as e:
                                logging.error(f'Failed to establish connection to destination: {destination} - {e}')  # Log connection failure
                        else:
                            logging.info(f'Connection to destination: {destination} already exists')  # Log existing connection
                            target_socket = connections[destination]                        
                    elif event == 'reqest':
                        logging.info(f'Received data destination: {destination}')  # Log request event handling
                    elif event == 'close':
                        logging.info(f'Closing connection to destination: {destination}')  # Log close event handling
                        target_socket = connections.pop(destination, None)
                        target_socket.close()  # Close the socket
                
                if request_data is not None:
                    target_socket.sendall(request_data)
                    logging.info(f'Sent data to destination: {destination}')  # Log sent data

                sqs_client.delete_message(
                    QueueUrl=queue_url,
                    ReceiptHandle=message['ReceiptHandle']
                )
                logging.info(f'Deleted message from SQS for destination: {destination}')  # Log message deletion

def receive_from_tcp(connections, queue_url, sqs_client, lock):
    while True:
        for destination in list(connections.keys()):  # Iterate over a copy of the keys
            target_socket = connections[destination]
            try:
                response_data = target_socket.recv(254*1024)
                if response_data:
                    logging.info(f'Received response data from: {destination}')  # Log received response
                    forward_to_sqs(response_data, queue_url, sqs_client, event='response', destination=destination)  # Added event data
            except BlockingIOError:
                # No data available, continue to the next connection
                continue
            except (socket.error, OSError):  # Handle socket closure
                logging.error(f'Connection closed for destination: {destination}')  # Log connection closure
                with lock:  # Use lock only when modifying connections
                    connections.pop(destination, None)  # Safely remove the closed connection

def start_server_side(queue_url, sqs_client):
    connections = {}
    lock = threading.Lock()
    
    # Add the new return queue URL from the environment variable
    return_queue_url = os.getenv('SQS_RX')
    logging.info(f'Using return queue URL: {return_queue_url}')  # Log return queue URL

    logging.info('Starting server side threads')  # Log server start
    sqs_thread = threading.Thread(
        target=receive_from_sqs,
        args=(queue_url, sqs_client, connections, lock, return_queue_url)  # Pass return_queue_url
    )
    tcp_thread = threading.Thread(
        target=receive_from_tcp,
        args=(connections, return_queue_url, sqs_client, lock)  # Update to use return_queue_url
    )
    
    sqs_thread.start()
    tcp_thread.start()
    
    sqs_thread.join()
    tcp_thread.join()

sqs_client = boto3.client('sqs')
QUEUE_URL = os.getenv('SQS_TX')

start_server_side(QUEUE_URL, sqs_client)
