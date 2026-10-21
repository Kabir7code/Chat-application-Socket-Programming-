"""Chat server: accepts many clients at once, one thread per client (FR-002).

Every client must register a unique username first (FR-001). After that,
chat lines are delivered in real time to everyone else (FR-003), and other
users are told when someone joins or leaves (FR-006).
"""

import re
import socket
import threading
import time

from chat import config, protocol

USERNAME_PATTERN = re.compile(r"^[A-Za-z0-9_]{1,20}$")


def system_message(event, username, text):
    return {"type": "system", "event": event, "username": username, "text": text}


def error_message(code, text):
    return {"type": "error", "code": code, "message": text}


class ChatServer:
    def __init__(self, host=config.DEFAULT_HOST, port=config.DEFAULT_PORT):
        self.host = host
        self.port = port
        self.clients = []  # every connected socket
        self.users = {}  # username -> socket, registered users only
        self._listener = None
        self._running = threading.Event()

    # ------------------------------------------------------------ lifecycle
    def start(self):
        """Bind and start accepting connections in a background thread."""
        self._listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._listener.bind((self.host, self.port))
        self._listener.listen()
        self.port = self._listener.getsockname()[1]  # real port if 0 was given
        self._running.set()
        threading.Thread(target=self._accept_loop, daemon=True).start()
        return self

    def serve_forever(self):
        self.start()
        print(f"Chat server listening on {self.host}:{self.port}")
        try:
            while self._running.is_set():
                time.sleep(0.5)
        except KeyboardInterrupt:
            print("\nShutting down.")
        finally:
            self.stop()

    def stop(self):
        self._running.clear()
        if self._listener:
            self._listener.close()
        for conn in list(self.clients):
            conn.close()

    # -------------------------------------------------------------- workers
    def _accept_loop(self):
        while self._running.is_set():
            try:
                conn, _addr = self._listener.accept()
            except OSError:
                break  # listener closed
            self.clients.append(conn)
            threading.Thread(target=self._handle_client, args=(conn,), daemon=True).start()

    def _handle_client(self, conn):
        username = None
        try:
            while True:
                message = protocol.recv_message(conn)
                if message is None:
                    break
                if username is None:
                    if message["type"] == "register":
                        username = self._register(conn, message.get("username", ""))
                    continue
                if message["type"] == "chat":
                    self._deliver_chat(username, message.get("text", ""))
        finally:
            if conn in self.clients:
                self.clients.remove(conn)
            if username is not None and self.users.get(username) is conn:
                del self.users[username]
                self._broadcast(
                    system_message("leave", username, f"{username} left the chat")
                )
            conn.close()

    # ------------------------------------------------------------- features
    def _register(self, conn, username):
        """Register a username. Returns it on success, None on failure."""
        username = str(username).strip()
        if not USERNAME_PATTERN.match(username):
            protocol.send_message(conn, error_message(
                "INVALID_USERNAME",
                "Username must be 1-20 letters, digits or underscores.",
            ))
            return None
        if username in self.users:
            protocol.send_message(conn, error_message(
                "USERNAME_TAKEN", "Username already taken."
            ))
            return None
        self.users[username] = conn
        protocol.send_message(conn, {
            "type": "registered",
            "username": username,
            "users": sorted(self.users),
        })
        self._broadcast(
            system_message("join", username, f"{username} joined the chat"),
            exclude=conn,
        )
        return username

    def _deliver_chat(self, sender, text):
        message = protocol.make_chat_message(text, sender)
        message["context"] = "general"
        self._broadcast(message, exclude=self.users.get(sender))

    def _broadcast(self, message, exclude=None):
        """Send to every registered user except `exclude`."""
        for conn in list(self.users.values()):
            if conn is not exclude:
                protocol.send_message(conn, message)


def main():
    args = config.parse_args("Run the chat server.")
    ChatServer(args.host, args.port).serve_forever()


if __name__ == "__main__":
    main()
