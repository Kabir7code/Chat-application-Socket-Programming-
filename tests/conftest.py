import socket

import pytest

from chat import protocol
from chat.server import ChatServer


@pytest.fixture
def server():
    srv = ChatServer(port=0).start()  # port 0 = pick any free port
    yield srv
    srv.stop()


class WireClient:
    """Small helper that talks the wire protocol, for tests."""

    def __init__(self, server, timeout=3.0):
        self.sock = socket.create_connection((server.host, server.port))
        self.sock.settimeout(timeout)

    def send(self, message):
        protocol.send_message(self.sock, message)

    def recv(self):
        return protocol.recv_message(self.sock)

    def recv_until(self, msg_type):
        """Read messages until one of the given type arrives."""
        while True:
            message = self.recv()
            if message is None or message["type"] == msg_type:
                return message

    def assert_silent(self, wait=0.3):
        """Check that nothing arrives within `wait` seconds."""
        self.sock.settimeout(wait)
        try:
            message = self.recv()
        except socket.timeout:
            return
        finally:
            self.sock.settimeout(3.0)
        raise AssertionError(f"expected no message, got {message}")

    def close(self):
        self.sock.close()


@pytest.fixture
def connect(server):
    clients = []

    def _connect():
        client = WireClient(server)
        clients.append(client)
        return client

    yield _connect
    for client in clients:
        client.close()
