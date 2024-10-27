# SOCKS5 Proxy through AWS SQS Messaging Service

This project provides a SOCKS5 proxy server that enables tunneling through the AWS SQS (Simple Queue Service) messaging service. It allows for secure and reliable communication between clients and servers by leveraging the SQS service as a message broker.

## Features

* Implements the SOCKS5 protocol for proxying TCP connections
* Utilizes AWS SQS for message queuing and forwarding
* Supports both IPv4 and domain name addressing
* Handles connection establishment, data forwarding, and connection closure

## Architecture

The proxy server consists of two main components:

1. **Server Side**: This component is responsible for receiving messages from SQS, establishing connections to target servers, and forwarding data between clients and servers. It runs two threads: one for receiving messages from SQS and another for handling TCP connections.
2. **Client Side**: This component initiates connections to the proxy server, which then forwards the requests to the target server through SQS. The client side also handles responses from the target server and forwards them back to the client through SQS.

## Environment Variables

The project relies on the following environment variables:

* `SQS_TX`: The URL of the SQS queue for message forwarding
* `SQS_RX`: The URL of the SQS queue for receiving responses

## Usage

To use this proxy server, you need to have the AWS CLI and Boto3 installed. Set the environment variables `SQS_TX` and `SQS_RX` to the URLs of your SQS queues. Then, run the server side script to start the proxy server.

Create SQS queues
```
./sqs_create.sh
```

Setup environment variables
```
source sqs_env.sh
```

On the client side, configure your application to use the SOCKS5 proxy server. The client side script can be used to initiate connections to the proxy server.

Server:
```
echo "Starting AWS Tunnel server"
source sqs_env.sh
./sqs_clear.sh; python aws_server.py
```

Proxy:
```
echo "Starting Proxy on 0.0.0.0:9050"
source sqs_env.sh
python aws_server.py
```

Client:
```
curl --socks5 localhost:9050 http://www.google.com
```

## Security

This project ensures secure communication by using the AWS SQS service, which provides a secure and reliable message queuing system. The SOCKS5 protocol is used for proxying TCP connections, ensuring that data is encrypted and protected from unauthorized access.

## Limitations

This project is designed for use cases where a secure and reliable proxy server is needed to tunnel through the AWS SQS messaging service. It may not be suitable for high-performance or low-latency applications due to the overhead of using SQS for message queuing.

## Contributing

Contributions are welcome! If you'd like to contribute to this project, please fork the repository, make your changes, and submit a pull request.
