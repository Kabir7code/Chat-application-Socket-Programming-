"""Chat server: accepts many clients at once, one thread per client (FR-002)."""

import socket
import threading
import time

from chat import protocol

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 5000


class ChatServer:
    def __init__(self, host=DEFAULT_HOST, port=DEFAULT_PORT):
        self.host = host
        self.port = port
        self.clients = []  # connected client sockets
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
                conn, addr = self._listener.accept()
            except OSError:
                break  # listener closed
            self.clients.append(conn)
            threading.Thread(
                target=self._handle_client, args=(conn, addr), daemon=True
            ).start()

    def _handle_client(self, conn, addr):
        sender = f"{addr[0]}:{addr[1]}"
        try:
            while True:
                message = protocol.recv_message(conn)
                if message is None:
                    break
                if message["type"] == "chat":
                    self._broadcast(
                        protocol.make_chat_message(message.get("text", ""), sender),
                        exclude=conn,
                    )
        finally:
            if conn in self.clients:
                self.clients.remove(conn)
            conn.close()

    def _broadcast(self, message, exclude=None):
        for conn in list(self.clients):
            if conn is not exclude:
                protocol.send_message(conn, message)


def main():
    ChatServer().serve_forever()


if __name__ == "__main__":
    main()
