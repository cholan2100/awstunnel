# -*- coding: utf-8 -*-
""" Small Socks5 Proxy Server in Python from https://github.com/MisterDaneel/"""

import logging  # Add this line to import the logging module
import socket
import select
from struct import pack, unpack
import traceback
from threading import Thread, activeCount, Lock, Event
from signal import signal, SIGINT, SIGTERM
from time import sleep
import sys
import boto3
import json
import base64
import os
import threading  # Add this line to import the threading module

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Configuration
MAX_THREADS = 200
BUFSIZE = 2048
TIMEOUT_SOCKET = 5
LOCAL_ADDR = '0.0.0.0'
LOCAL_PORT = 9050
OUTGOING_INTERFACE = ""  # Example: "eth0", leave empty for automatic

# Constants
VER = b'\x05'  # Protocol Version
M_NOAUTH = b'\x00'  # No Authentication Required
M_NOTAVAILABLE = b'\xff'  # No Acceptable Methods
CMD_CONNECT = b'\x01'  # Connect Command
ATYP_IPV4 = b'\x01'  # IPv4 Address
ATYP_DOMAINNAME = b'\x03'  # Domain Name

class ExitStatus:
    """ Manage exit status """
    def __init__(self):
        self.exit = False

    def set_status(self, status):
        """ set exit status """
        self.exit = status

    def get_status(self):
        """ get exit status """
        return self.exit

# Add a global event to signal threads to exit
EXIT_EVENT = threading.Event()

def error(msg="", err=None):
    """ Print exception stack trace python """
    if msg:
        logging.error(f"{msg} - Code: {str(err[0])}, Message: {err[1]}")  # Log the error
        traceback.print_exc()
    else:
        traceback.print_exc()

def proxy_loop(socket_src, socket_dst):
    """ Wait for network activity """
    while not EXIT.get_status():
        try:
            reader, _, _ = select.select([socket_src, socket_dst], [], [], 1)
        except select.error as err:
            error("Select failed", err)
            return
        if not reader:
            continue
        try:
            for sock in reader:
                data = sock.recv(BUFSIZE)
                if not data:
                    return
                if sock is socket_dst:
                    socket_src.send(data)
                else:
                    socket_dst.send(data)
        except socket.error as err:
            error("Loop failed", err)
            return

def connect_to_dst(dst_addr, dst_port):
    """ Connect to desired destination """
    sock = create_socket()
    if OUTGOING_INTERFACE:
        try:
            sock.setsockopt(
                socket.SOL_SOCKET,
                socket.SO_BINDTODEVICE,
                OUTGOING_INTERFACE.encode(),
            )
        except PermissionError as err:
            print("Only root can set OUTGOING_INTERFACE parameter")
            EXIT.set_status(True)
    try:
        sock.connect((dst_addr, dst_port))
        return sock
    except socket.error as err:
        error("Failed to connect to DST", err)
        return 0

def forward_to_sqs(data, queue_url, destination, sqs_client, event):
    if data is None:
        logging.info(f'Sending event: {event} to client on SQS queue')
    else:
        logging.info(f'Forwarding data on SQS queue') 
    message_body = json.dumps({"destination": destination, 
                               "data": base64.b64encode(data).decode('utf-8') if data is not None else "None", 
                               "event": event})
    response = sqs_client.send_message(
        QueueUrl=queue_url,
        MessageBody=message_body
    )
    return response

def poll_sqs(queue_url, sqs_client):
    response = sqs_client.receive_message(
        QueueUrl=queue_url,
        MaxNumberOfMessages=1,
        WaitTimeSeconds=3
    )
    return response

def receive_from_sqs(queue_url, sqs_client, client_socket):
    socket_broke = False
    while True:
        messages = poll_sqs(queue_url, sqs_client)
        if 'Messages' in messages:
            for message in messages['Messages']:
                body = json.loads(message['Body'])
                destination = body['destination']
                data = base64.b64decode(body['data'])
                if 'event' in body and body['event'] == 'connected':
                    logging.info(f"Handling connected event for destination: {body['destination']}")  # Log connected event handling
                    logging.info(f"Connected to destination: {destination}")  # Log connection
                else:
                    logging.info(f"Received message from SQS")  # Log received message
                    logging.info(f"Sending data to client: {len(data)} bytes")  # Log data sending event
                    try:
                        client_socket.sendall(data)
                    except socket.error as err:
                        logging.error(f"Socket error sending data: {err}")  # Log socket error
                        socket_broke = True
                logging.info("Message deleted from SQS")  # Log message deletion
                sqs_client.delete_message(
                    QueueUrl=queue_url,
                    ReceiptHandle=message['ReceiptHandle']
                )
                if socket_broke:
                    break
        else:
            sleep(1)
    logging.info("receive_from_sqs: Thread exiting")
    

def request_client(wrapper):
    """ Client request details """
    try:
        s5_request = wrapper.recv(BUFSIZE)
    except ConnectionResetError:
        if wrapper != 0:
            wrapper.close()
        error()
        return False

    if (
        s5_request[0:1] != VER or
        s5_request[1:2] != CMD_CONNECT or
        s5_request[2:3] != b'\x00'
    ):
        return False

    if s5_request[3:4] == ATYP_IPV4:
        dst_addr = socket.inet_ntoa(s5_request[4:-2])
        dst_port = unpack('>H', s5_request[8:])[0]
    elif s5_request[3:4] == ATYP_DOMAINNAME:
        sz_domain_name = s5_request[4]
        dst_addr = s5_request[5: 5 + sz_domain_name].decode()
        dst_port = unpack('>H', s5_request[5 + sz_domain_name:])[0]
    else:
        return False

    print(dst_addr, dst_port)
    return (dst_addr, dst_port)

def request(wrapper, queue_url, sqs_client):
    # Add a new parameter for the reverse queue URL
    reverse_queue_url = os.getenv('SQS_RX')
    
    dst = request_client(wrapper)
    rep = b'\x07'
    bnd = b'\x00' * 6

    if dst:
        logging.info(f"Connecting to destination: {dst[0]}:{dst[1]}")  # Log connection
        forward_to_sqs(None, queue_url, f"{dst[0]}:{dst[1]}", sqs_client, "connect")
        socket_dst = connect_to_dst(dst[0], dst[1]) # TODO: remove

    if not dst or socket_dst == 0:
        rep = b'\x01'
        logging.warning("Failed to connect to destination")  # Log failure
    else:
        rep = b'\x00'
        bnd = socket.inet_aton(socket_dst.getsockname()[0]) + pack(">H", socket_dst.getsockname()[1])

    reply = VER + rep + b'\x00' + ATYP_IPV4 + bnd

    try:
        wrapper.sendall(reply)
    except socket.error:
        if wrapper != 0:
            wrapper.close()
        return

    if rep == b'\x00':
        destination = f"{dst[0]}:{dst[1]}"
        logging.info(f"Starting thread to receive from SQS for destination: {destination}")  # Log thread start
        threading.Thread(target=receive_from_sqs, args=(reverse_queue_url, sqs_client, wrapper)).start()
        
        while True:
            try:
                data = wrapper.recv(BUFSIZE)
            except ConnectionResetError:
                data = None
            if not data:
                logging.info(f"Client closed connection, closing target connection to: {destination}")  # Log closure
                socket_dst.close()  # Close the target socket

                logging.info(f"Sending closure notification to server for destination: {destination}")  # Log closure notification
                forward_to_sqs(None, queue_url, destination, sqs_client, "close")
                
                break
            
            forward_to_sqs(data, queue_url, destination, sqs_client, "request")

    if wrapper != 0:
        wrapper.close()

    if socket_dst != 0:
        socket_dst.close()

def subnegotiation_client(wrapper):
    try:
        identification_packet = wrapper.recv(BUFSIZE)
    except socket.error:
        error()
        return M_NOTAVAILABLE

    if VER != identification_packet[0:1]:
        return M_NOTAVAILABLE

    nmethods = identification_packet[1]
    methods = identification_packet[2:]

    if len(methods) != nmethods:
        return M_NOTAVAILABLE

    for method in methods:
        if method == ord(M_NOAUTH):
            return M_NOAUTH

    return M_NOTAVAILABLE

def subnegotiation(wrapper):
    method = subnegotiation_client(wrapper)

    if method != M_NOAUTH:
        return False

    reply = VER + method

    try:
        wrapper.sendall(reply)
    except socket.error:
        error()
        return False

    return True

def connection(wrapper, queue_url, sqs_client):
    if subnegotiation(wrapper):
        request(wrapper, queue_url, sqs_client)

def create_socket():
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(TIMEOUT_SOCKET)
    except socket.error as err:
        error("Failed to create socket", err)
        sys.exit(0)
    return sock

def bind_port(sock):
    try:
        print('Bind {}'.format(str(LOCAL_PORT)))
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind((LOCAL_ADDR, LOCAL_PORT))
    except socket.error as err:
        error("Bind failed", err)
        sock.close()
        sys.exit(0)

    try:
        sock.listen(10)
    except socket.error as err:
        error("Listen failed", err)
        sock.close()
        sys.exit(0)

    return sock

def exit_handler(signum, frame):
    print('Signal handler called with signal', signum)
    EXIT.set_status(True)
    exit(1)

def main():
    new_socket = create_socket()
    bind_port(new_socket)
    signal(SIGINT, exit_handler)
    signal(SIGTERM, exit_handler)

    sqs_client = boto3.client('sqs')
    QUEUE_URL = os.getenv('SQS_TX')

    while not EXIT.get_status():
        if activeCount() > MAX_THREADS:
            sleep(3)
            continue

        try:
            wrapper, _ = new_socket.accept()
            wrapper.setblocking(1)
            logging.info("Accepted new connection")  # Log new connection
        except socket.timeout:
            continue
        except socket.error:
            error()
            continue
        except TypeError:
            error()
            sys.exit(0)

        recv_thread = Thread(target=connection, args=(wrapper, QUEUE_URL, sqs_client))
        recv_thread.start()

    new_socket.close()

EXIT = ExitStatus()

if __name__ == '__main__':
    main()
