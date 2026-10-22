"""Terminal chat client: one copy runs per user."""

import socket
import sys
import threading

from chat import config, protocol


def format_message(message):
    """Turn a message from the server into one line of text to print."""
    kind = message["type"]
    if kind == "chat":
        return f"{message['from']}: {message['text']}"
    if kind == "system":  # #5: join/leave notices are marked with "*"
        return f"* {message['text']}"
    if kind == "error":  # errors such as "Username already taken." get "!"
        return f"! {message['message']}"
    return str(message)


def register(sock):
    """#2 (FR-001, UC-01): ask for a username until the server accepts one.

    Returns the accepted name, or None if the user quit or the server closed.
    """
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
            # Show who else is online so the user knows who can read them.
            others = [u for u in reply["users"] if u != reply["username"]]
            print(f"Welcome, {reply['username']}! Online: {', '.join(others) or 'nobody yet'}")
            return reply["username"]
        print(format_message(reply))  # e.g. name taken: loop and ask again


def receive_loop(sock):
    """#3 (FR-003): print messages the moment they arrive.

    Runs in a background thread so incoming messages appear even while the
    user is in the middle of typing.
    """
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
    args = config.parse_args("Connect to the chat server.")  # #10: --host/--port
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
