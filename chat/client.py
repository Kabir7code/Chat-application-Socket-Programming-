"""Terminal chat client."""

import socket
import sys
import threading

from chat import config, protocol


def format_message(message):
    kind = message["type"]
    if kind == "chat":
        return f"{message['from']}: {message['text']}"
    if kind == "system":
        return f"* {message['text']}"
    if kind == "error":
        return f"! {message['message']}"
    return str(message)


def register(sock):
    """Ask for a username until the server accepts one (UC-01)."""
    while True:
        try:
            username = input("Choose a username: ").strip()
        except EOFError:
            return None
        protocol.send_message(sock, {"type": "register", "username": username})
        reply = protocol.recv_message(sock)
        if reply is None:
            return None
        if reply["type"] == "registered":
            others = [u for u in reply["users"] if u != reply["username"]]
            print(f"Welcome, {reply['username']}! Online: {', '.join(others) or 'nobody yet'}")
            return reply["username"]
        print(format_message(reply))


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
    args = config.parse_args("Connect to the chat server.")
    try:
        sock = socket.create_connection((args.host, args.port))
    except OSError as exc:
        sys.exit(f"Could not connect to {args.host}:{args.port} ({exc})")
    try:
        if register(sock) is None:
            return
        threading.Thread(target=receive_loop, args=(sock,), daemon=True).start()
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
