"""TLS encryption (NFR-005 part 2, #22).

The key check: capture every byte between client and server and make sure
the chat text never appears in it. The same capture without TLS is run as a
control, to prove the capture would have seen the text if it were there.
"""

import shutil
import socket
import ssl
import subprocess
import sys
import threading
import time

import pytest

from chat import config, protocol, tls
from chat.make_cert import make_cert, subject_alt_names
from chat.server import ChatServer

pytestmark = pytest.mark.skipif(shutil.which("openssl") is None, reason="needs openssl")

SECRET = "the exam answers are in folder B"


@pytest.fixture(scope="module")
def certs(tmp_path_factory):
    return make_cert(str(tmp_path_factory.mktemp("certs")), [])


@pytest.fixture
def tls_server(certs):
    srv = ChatServer(port=0, tls_context=tls.server_context(*certs)).start()
    yield srv
    srv.stop()


class Tap:
    """A tiny TCP relay between a client and the server that records every
    byte passing through it, like someone sniffing the network."""

    def __init__(self, target_port):
        self.captured = bytearray()
        self._lock = threading.Lock()
        self.listener = socket.socket()
        self.listener.bind(("127.0.0.1", 0))
        self.listener.listen()
        self.port = self.listener.getsockname()[1]
        self.target_port = target_port
        threading.Thread(target=self._accept, daemon=True).start()

    def _accept(self):
        while True:
            try:
                client, _ = self.listener.accept()
            except OSError:
                return
            upstream = socket.create_connection(("127.0.0.1", self.target_port))
            for src, dst in ((client, upstream), (upstream, client)):
                threading.Thread(target=self._pipe, args=(src, dst), daemon=True).start()

    def _pipe(self, src, dst):
        try:
            while True:
                data = src.recv(4096)
                if not data:
                    break
                with self._lock:
                    self.captured += data
                dst.sendall(data)
        except OSError:
            pass
        finally:
            for s in (src, dst):
                try:
                    s.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass

    def close(self):
        self.listener.close()


def login(sock, name):
    sock.settimeout(5)
    protocol.send_message(sock, {"type": "register", "username": name})
    reply = protocol.recv_message(sock)
    assert reply["type"] == "registered", reply
    return sock


def until(sock, kind):
    while True:
        message = protocol.recv_message(sock)
        if message is None or message["type"] == kind:
            return message


def chat_through_tap(server_port, context):
    tap = Tap(server_port)
    alice = login(tls.connect("127.0.0.1", tap.port, context), "alice")
    bob = login(tls.connect("127.0.0.1", tap.port, context), "bob")
    protocol.send_message(alice, {"type": "chat", "text": SECRET})
    protocol.send_message(alice, {"type": "private", "to": "bob", "text": SECRET + " (private)"})
    received = (until(bob, "chat")["text"], until(bob, "private")["text"])
    time.sleep(0.2)
    alice.close()
    bob.close()
    tap.close()
    return received, bytes(tap.captured)


def test_chat_works_over_tls(tls_server, certs):
    context = tls.client_context(certs[0])
    alice = login(tls.connect("127.0.0.1", tls_server.port, context), "alice")
    bob = login(tls.connect("127.0.0.1", tls_server.port, context), "bob")
    assert isinstance(alice, ssl.SSLSocket) and alice.version() in ("TLSv1.2", "TLSv1.3")
    protocol.send_message(alice, {"type": "chat", "text": "hello over TLS"})
    assert until(bob, "chat")["text"] == "hello over TLS"


def test_captured_traffic_has_no_plaintext(tls_server, certs):
    received, captured = chat_through_tap(tls_server.port, tls.client_context(certs[0]))
    assert received == (SECRET, SECRET + " (private)")  # the chat itself worked
    assert len(captured) > 500  # the tap really did see the traffic
    for plain in (SECRET, "alice", "bob", "register", '"type"'):
        assert plain.encode() not in captured


def test_control_without_tls_the_tap_does_see_plaintext(server):
    received, captured = chat_through_tap(server.port, None)
    assert received == (SECRET, SECRET + " (private)")
    assert SECRET.encode() in captured  # proves the previous test is meaningful


def test_client_rejects_server_it_does_not_trust(tls_server, tmp_path):
    other_cert, _ = make_cert(str(tmp_path), [])  # a different, untrusted certificate
    with pytest.raises(ssl.SSLCertVerificationError):
        tls.connect("127.0.0.1", tls_server.port, tls.client_context(other_cert))


def test_plain_client_cannot_talk_to_tls_server(tls_server, certs):
    plain = socket.create_connection(("127.0.0.1", tls_server.port))
    plain.settimeout(3)
    try:
        protocol.send_message(plain, {"type": "register", "username": "sneaky"})
        reply = plain.recv(4096)
    except OSError:
        reply = b""
    assert b"registered" not in reply
    assert "sneaky" not in tls_server.users
    # and the server still serves proper clients afterwards
    good = login(tls.connect("127.0.0.1", tls_server.port, tls.client_context(certs[0])), "good")
    assert "good" in tls_server.users
    good.close()


def test_stalled_handshake_does_not_block_others(tls_server, certs):
    staller = socket.create_connection(("127.0.0.1", tls_server.port))  # never handshakes
    start = time.time()
    good = login(tls.connect("127.0.0.1", tls_server.port, tls.client_context(certs[0])), "fast")
    assert time.time() - start < 2
    good.close()
    staller.close()


def test_groups_work_over_tls(tls_server, certs):
    context = tls.client_context(certs[0])
    a = login(tls.connect("127.0.0.1", tls_server.port, context), "A")
    b = login(tls.connect("127.0.0.1", tls_server.port, context), "B")
    protocol.send_message(a, {"type": "create_group", "group": "Squad"})
    until(a, "group_update")
    protocol.send_message(b, {"type": "join_group", "group": "Squad"})
    until(b, "group_update")
    protocol.send_message(a, {"type": "group", "group": "Squad", "text": "encrypted group msg"})
    assert until(b, "chat")["text"] == "encrypted group msg"


def test_cert_covers_extra_host():
    assert subject_alt_names(["192.168.1.20", "myhost"]) == [
        "DNS:localhost", "IP:127.0.0.1", "IP:192.168.1.20", "DNS:myhost"]


def test_missing_cert_gives_clear_message(tmp_path):
    args = config.parse_args("test", ["--cert", str(tmp_path / "nope.crt"),
                                      "--key", str(tmp_path / "nope.key")])
    with pytest.raises(SystemExit) as exc:
        config.server_tls(args)
    assert "make_cert" in str(exc.value)


def test_no_tls_flag(monkeypatch):
    monkeypatch.delenv("CHAT_NO_TLS", raising=False)
    assert config.parse_args("test", []).no_tls is False
    args = config.parse_args("test", ["--no-tls"])
    assert config.server_tls(args) is None and config.client_tls(args) is None


def test_real_terminal_client_over_tls(tls_server, certs):
    """End to end with the actual client program and its --cafile option."""
    out = subprocess.run(
        [sys.executable, "-m", "chat.client", "--port", str(tls_server.port), "--cafile", certs[0]],
        input="tlsuser\n/quit\n", capture_output=True, text=True, timeout=15,
    ).stdout
    assert "Welcome, tlsuser!" in out
