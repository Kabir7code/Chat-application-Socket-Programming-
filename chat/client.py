"""Terminal chat client."""

import socket
import sys
import threading

from chat import protocol
from chat.server import DEFAULT_HOST, DEFAULT_PORT


def format_message(message):
    if message["type"] == "chat":
        return f"{message['from']}: {message['text']}"
    return str(message)


def receive_loop(sock):
    while True:
        try:
            message = protocol.recv_message(sock)
        except (OSError, protocol.ProtocolError):
            message = None
        if message is None:
            print("\n[disconnected from server]")
            return
        print(format_message(message))


def main():
    sock = socket.create_connection((DEFAULT_HOST, DEFAULT_PORT))
    threading.Thread(target=receive_loop, args=(sock,), daemon=True).start()
    try:
        for line in sys.stdin:
            line = line.rstrip("\n")
            if line:
                protocol.send_message(sock, {"type": "chat", "text": line})
    except KeyboardInterrupt:
        pass
    finally:
        sock.close()


if __name__ == "__main__":
    main()
