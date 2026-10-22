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

# #2 (FR-001): a valid username is 1-20 letters, digits or underscores.
# This also rejects empty names and the 50-character name from test UT_03.
USERNAME_PATTERN = re.compile(r"^[A-Za-z0-9_]{1,20}$")


def system_message(event, username, text):
    """#5 (FR-006): a server notice such as "bob joined the chat"."""
    return {"type": "system", "event": event, "username": username, "text": text}


def error_message(code, text):
    """An error sent back to one client. `code` is for programs, `message`
    is the text shown to the user."""
    return {"type": "error", "code": code, "message": text}


class ChatServer:
    def __init__(self, host=config.DEFAULT_HOST, port=config.DEFAULT_PORT):
        self.host = host
        self.port = port
        self.clients = []  # every connected socket, registered or not
        self.users = {}  # #2: username -> socket, only users who registered
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
        """Runs in its own thread for one client until they disconnect."""
        username = None  # stays None until registration succeeds (#2)
        try:
            while True:
                message = protocol.recv_message(conn)
                if message is None:  # client closed the connection
                    break
                if username is None:
                    # #2 (FR-001): the first thing a client must do is register.
                    if message["type"] == "register":
                        username = self._register(conn, message.get("username", ""))
                    continue
                if message["type"] == "chat":
                    self._deliver_chat(username, message.get("text", ""))  # #3
        finally:
            # Runs however the loop ended, so the user is always cleaned up.
            if conn in self.clients:
                self.clients.remove(conn)
            # Check the socket matches: only the owner of a name may release it.
            if username is not None and self.users.get(username) is conn:
                del self.users[username]  # frees the name for reuse
                # #5 (FR-006): tell everyone still online that this user left.
                self._broadcast(
                    system_message("leave", username, f"{username} left the chat")
                )
            conn.close()

    # ------------------------------------------------------------- features
    def _register(self, conn, username):
        """#2 (FR-001, UC-01): claim a unique username for this connection.

        Returns the username on success. On failure it sends an error and
        returns None, and the client may try again with another name.
        """
        username = str(username).strip()  # "  bob " counts as "bob"
        if not USERNAME_PATTERN.match(username):
            protocol.send_message(conn, error_message(
                "INVALID_USERNAME",
                "Username must be 1-20 letters, digits or underscores.",
            ))
            return None
        if username in self.users:
            # UC-01 alternative flow 3B: wording taken from our use-case doc.
            protocol.send_message(conn, error_message(
                "USERNAME_TAKEN", "Username already taken."
            ))
            return None
        self.users[username] = conn
        # Confirm, and include who is online so the client can show it.
        protocol.send_message(conn, {
            "type": "registered",
            "username": username,
            "users": sorted(self.users),
        })
        # #5 (FR-006): tell everyone else that a new user has joined.
        self._broadcast(
            system_message("join", username, f"{username} joined the chat"),
            exclude=conn,
        )
        return username

    def _deliver_chat(self, sender, text):
        """#3 (FR-003): push a chat line to every other user immediately.

        The server sends as soon as the message arrives, so clients never
        need to refresh or poll. "context" says where the message belongs;
        Sprint 2 adds "group".
        """
        message = protocol.make_chat_message(text, sender)
        message["context"] = "general"
        self._broadcast(message, exclude=self.users.get(sender))

    def _broadcast(self, message, exclude=None):
        """Send to every registered user except `exclude`.

        Unregistered sockets are skipped on purpose: they have not joined
        the chat yet, so they must not see anyone's messages.
        """
        for conn in list(self.users.values()):  # copy: other threads may change it
            if conn is not exclude:
                protocol.send_message(conn, message)


def main():
    args = config.parse_args("Run the chat server.")
    ChatServer(args.host, args.port).serve_forever()


if __name__ == "__main__":
    main()
