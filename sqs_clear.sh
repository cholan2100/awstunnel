#!/bin/bash
# MYQUEUE="https://queue.amazonaws.com/278902205627/MyQueue"

while true; do
    MESSAGES=$(aws sqs receive-message --queue-url $MYQUEUE --max-number-of-messages 10)
    echo $MESSAGES
    if [ -z "$MESSAGES" ]; then
        echo "No more messages in queue."
        break
    fi

    for RECEIPT_HANDLE in $(echo $MESSAGES | jq -r '.Messages[].ReceiptHandle'); do
        aws sqs delete-message --queue-url $MYQUEUE --receipt-handle $RECEIPT_HANDLE
        echo "Deleted message with ReceiptHandle: $RECEIPT_HANDLE"
    done
done

while true; do
    MESSAGES=$(aws sqs receive-message --queue-url $MYQUEUE_RX --max-number-of-messages 10)
    echo $MESSAGES
    if [ -z "$MESSAGES" ]; then
        echo "No more messages in queue."
        break
    fi

    for RECEIPT_HANDLE in $(echo $MESSAGES | jq -r '.Messages[].ReceiptHandle'); do
        aws sqs delete-message --queue-url $MYQUEUE_RX --receipt-handle $RECEIPT_HANDLE
        echo "Deleted message with ReceiptHandle: $RECEIPT_HANDLE"
    done
done