"""System validation tests: the whole chat system checked against its requirements.

The tests in tests/ are unit and integration tests: they import the server's
classes and look inside them. This file is different. It treats the system as
a black box, the way a user sees it:

  * the server is started as its own program (python -m chat.server), on a free
    port, with its own database file, and stopped/restarted like the real thing;
  * clients talk to it only over TCP, using the wire protocol
    (4-byte length + JSON), or through the real terminal client program;
  * nothing from the server's code is imported.

Each test is named after the requirement it validates (FR-001 ... FR-013 from
the SRS and the Sprint 3 backlog, NFR-001 ... NFR-007).

Run:
    python3 -m pytest system_tests -v
or  python3 system_tests/test_system_validation.py
"""

import json
import os
import shutil
import socket
import ssl
import struct
import subprocess
import sys
import tempfile
import threading
import time

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PYTHON = sys.executable
TIMEOUT = 5.0


# ------------------------------------------------------------------ helpers
def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class Server:
    """The chat server running as a separate program."""

    def __init__(self, folder, keep=None, tls=None):
        self.folder = folder
        self.db = os.path.join(folder, "chat.db")
        self.keep = keep
        self.tls = tls  # (cert, key) or None
        self.port = free_port()
        self.proc = None

    def start(self):
        cmd = [PYTHON, "-m", "chat.server", "--host", "127.0.0.1", "--port", str(self.port),
               "--db", self.db]
        if self.keep is not None:
            cmd += ["--keep", str(self.keep)]
        if self.tls:
            cmd += ["--cert", self.tls[0], "--key", self.tls[1]]
        else:
            cmd += ["--no-tls"]
        self.proc = subprocess.Popen(cmd, cwd=ROOT, stdout=subprocess.PIPE,
                                     stderr=subprocess.STDOUT, text=True)
        deadline = time.time() + 10
        while time.time() < deadline:
            try:
                socket.create_connection(("127.0.0.1", self.port), timeout=0.2).close()
                return self
            except OSError:
                if self.proc.poll() is not None:
                    raise RuntimeError("server exited: " + self.proc.stdout.read())
                time.sleep(0.05)
        raise RuntimeError("server did not start")

    def stop(self):
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait()
        if self.proc and self.proc.stdout:
            self.proc.stdout.close()

    def restart(self):
        self.stop()
        return self.start()


class Client:
    """A client speaking the wire protocol: 4-byte big-endian length + UTF-8 JSON."""

    def __init__(self, server, name=None, tls_cafile=None):
        sock = socket.create_connection(("127.0.0.1", server.port), timeout=TIMEOUT)
        if tls_cafile:
            ctx = ssl.create_default_context(cafile=tls_cafile)
            sock = ctx.wrap_socket(sock, server_hostname="localhost")
        self.sock = sock
        self.name = name
        self.reply = None
        if name is not None:
            self.send(type="register", username=name)
            self.reply = self.wait_for("registered", "error")

    def send(self, **message):
        body = json.dumps(message).encode("utf-8")
        self.sock.sendall(struct.pack(">I", len(body)) + body)

    def _read(self, n):
        data = b""
        while len(data) < n:
            chunk = self.sock.recv(n - len(data))
            if not chunk:
                return None
            data += chunk
        return data

    def recv(self, timeout=TIMEOUT):
        self.sock.settimeout(timeout)
        header = self._read(4)
        if header is None:
            return None
        body = self._read(struct.unpack(">I", header)[0])
        return None if body is None else json.loads(body.decode("utf-8"))

    def wait_for(self, *types, timeout=TIMEOUT):
        deadline = time.time() + timeout
        while True:
            left = deadline - time.time()
            if left <= 0:
                raise AssertionError(f"no {types} message within {timeout} s")
            message = self.recv(left)
            if message is None:
                raise AssertionError(f"connection closed while waiting for {types}")
            if message["type"] in types:
                return message

    def drain(self, wait=0.4):
        got = []
        try:
            while True:
                message = self.recv(wait)
                if message is None:
                    break
                got.append(message)
        except (socket.timeout, TimeoutError, ssl.SSLError):
            pass
        return got

    def users(self):
        self.send(type="list_users")
        return self.wait_for("users")["users"]

    def close(self):
        try:
            self.sock.close()
        except OSError:
            pass


def terminal_client(server, lines, wait=1.0):
    """Run the real terminal client and type `lines` into it; return what it printed."""
    proc = subprocess.Popen([PYTHON, "-m", "chat.client", "--no-tls", "--host", "127.0.0.1",
                             "--port", str(server.port)],
                            cwd=ROOT, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, text=True)
    for line in lines:
        proc.stdin.write(line + "\n")
        proc.stdin.flush()
        time.sleep(0.3)
    time.sleep(wait)
    try:  # communicate() closes stdin (end of input), which ends the client
        out, _ = proc.communicate(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()
        out, _ = proc.communicate()
    return out


def texts(messages, kind="chat"):
    return [m["text"] for m in messages if m["type"] == kind]


def history(messages):
    return [m["text"] for m in messages if m.get("history")]


def eventually(check, timeout=TIMEOUT):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if check():
            return True
        time.sleep(0.05)
    return False


def make_group(admin, group, *members):
    admin.send(type="create_group", group=group)
    admin.wait_for("group_update")
    for member in members:
        member.send(type="join_group", group=group)
        member.wait_for("group_update")
    for c in (admin, *members):
        c.drain(0.2)


@pytest.fixture
def folder():
    path = tempfile.mkdtemp(prefix="chat-system-")
    yield path
    shutil.rmtree(path, ignore_errors=True)


@pytest.fixture
def server(folder):
    srv = Server(folder).start()
    yield srv
    srv.stop()


# ======================================================== functional (FR)
def test_FR_001_register_with_a_unique_username(server):
    alice = Client(server, "alice")
    assert alice.reply["type"] == "registered"
    assert Client(server, "alice").reply["code"] == "USERNAME_TAKEN"
    assert Client(server, "").reply["type"] == "error"
    assert Client(server, "a" * 50).reply["type"] == "error"
    out = terminal_client(server, ["bob", "/quit"])
    assert "Welcome, bob!" in out


def test_FR_002_many_users_at_the_same_time(server):
    clients = [Client(server, f"user{i}") for i in range(10)]
    assert sorted(clients[0].users()) == sorted(f"user{i}" for i in range(10))
    clients[5].close()
    assert eventually(lambda: "user5" not in clients[0].users())
    clients[0].send(type="chat", text="still here")
    assert "still here" in texts(clients[9].drain(0.6))


def test_FR_003_real_time_messaging(server):
    alice, bob, carol = Client(server, "alice"), Client(server, "bob"), Client(server, "carol")
    for c in (bob, carol):
        c.drain(0.2)
    alice.send(type="chat", text="hello everyone")
    for c in (bob, carol):
        m = c.wait_for("chat")
        assert (m["from"], m["text"]) == ("alice", "hello everyone")


def test_FR_004_group_chat(server):
    alice, bob, carol = Client(server, "alice"), Client(server, "bob"), Client(server, "carol")
    make_group(alice, "Squad", bob)
    carol.drain(0.2)
    alice.send(type="group", group="Squad", text="squad only")
    assert bob.wait_for("chat")["group"] == "Squad"
    assert "squad only" not in texts(carol.drain(0.5))
    alice.send(type="add_member", group="Squad", username="carol")
    assert carol.wait_for("group_update")["members"] == ["alice", "bob", "carol"]
    assert history(carol.drain(0.4)) == ["squad only"]  # added members see recent messages
    bob.send(type="leave_group", group="Squad")
    bob.wait_for("group_update")
    bob.drain(0.2)
    alice.send(type="group", group="Squad", text="after bob left")
    assert carol.wait_for("chat")["text"] == "after bob left"
    assert "after bob left" not in texts(bob.drain(0.5))


def test_FR_005_private_messaging(server):
    alice, bob, carol = Client(server, "alice"), Client(server, "bob"), Client(server, "carol")
    carol.drain(0.2)
    alice.send(type="private", to="bob", text="just for you")
    m = bob.wait_for("private")
    assert (m["from"], m["text"]) == ("alice", "just for you")
    assert alice.wait_for("private_sent")["to"] == "bob"
    assert "just for you" not in [x.get("text") for x in carol.drain(0.5)]
    alice.send(type="private", to="nobody", text="hi")
    assert alice.wait_for("error")["code"] == "USER_NOT_FOUND"


def test_FR_006_online_users_and_join_leave_notices(server):
    alice = Client(server, "alice")
    alice.drain(0.2)
    bob = Client(server, "bob")
    assert "bob joined the chat" in texts(alice.drain(0.5), "system")
    assert sorted(alice.users()) == ["alice", "bob"]
    bob.send(type="quit")
    assert "bob left the chat" in texts(alice.drain(0.8), "system")
    assert alice.users() == ["alice"]


def test_FR_007_disconnects_are_handled(server):
    alice, bob = Client(server, "alice"), Client(server, "bob")
    bob.sock.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, struct.pack("ii", 1, 0))
    bob.close()  # abrupt reset, no goodbye
    assert eventually(lambda: alice.users() == ["alice"])
    again = Client(server, "bob")  # same name can come back
    assert again.reply["type"] == "registered"


def test_FR_008_bad_input_does_not_crash_the_server(server):
    alice, bob = Client(server, "alice"), Client(server, "bob")
    alice.sock.sendall(struct.pack(">I", 9) + b"{bad json")
    assert alice.wait_for("error")["message"] == "Message was not valid JSON."
    alice.send(type="chat", text="")
    assert alice.wait_for("error")["code"] == "EMPTY_MESSAGE"
    alice.send(type="chat", text="x" * 4001)
    assert alice.wait_for("error")["code"] == "MESSAGE_TOO_LONG"
    bob.drain(0.2)
    alice.send(type="chat", text="alice is fine")
    assert bob.wait_for("chat")["text"] == "alice is fine"
    carol = Client(server, "carol")
    carol.sock.sendall(struct.pack(">I", 10_000_000))  # claims a 10 MB frame
    assert eventually(lambda: "carol" not in bob.users())
    assert Client(server, "dave").reply["type"] == "registered"


def test_FR_009_messages_have_timestamps_and_ids(server):
    alice, bob = Client(server, "alice"), Client(server, "bob")
    alice.send(type="chat", text="what time is it")
    m = bob.wait_for("chat")
    assert isinstance(m["id"], int)
    assert m["time"][:4].isdigit() and "T" in m["time"]
    out = terminal_client(server, ["carol", "time check", "/quit"])
    assert "Welcome, carol!" in out


def test_FR_010_group_history_for_new_members(server):
    alice, carol = Client(server, "alice"), Client(server, "carol")
    make_group(alice, "Squad")
    for i in range(12):
        alice.send(type="group", group="Squad", text=f"g{i}")
    time.sleep(0.5)
    carol.send(type="join_group", group="Squad")
    assert history(carol.drain(0.6)) == [f"g{i}" for i in range(2, 12)]


def test_FR_011_messages_are_saved_and_shown_after_a_restart(server):
    alice = Client(server, "alice")
    for i in range(25):
        alice.send(type="chat", text=f"m{i}")
    time.sleep(0.5)
    bob = Client(server, "bob")
    assert history(bob.drain(0.6)) == [f"m{i}" for i in range(5, 25)]
    server.restart()
    out = terminal_client(server, ["carol", "/quit"])
    assert "(earlier) alice: m24" in out


def test_FR_012_private_history_and_offline_messages(server):
    alice, bob = Client(server, "alice"), Client(server, "bob")
    alice.send(type="private", to="bob", text="first")
    bob.wait_for("private")
    bob.send(type="quit")
    assert eventually(lambda: alice.users() == ["alice"])
    alice.send(type="private", to="bob", text="while you were out")
    assert alice.wait_for("private_sent").get("queued") is True
    server.restart()
    bob = Client(server, "bob")
    waiting = [m for m in bob.drain(0.6) if m["type"] == "private"]
    assert [(m["text"], m.get("offline")) for m in waiting] == [("while you were out", True)]
    bob.send(type="private_history", **{"with": "alice"})
    saved = bob.wait_for("private_history")["messages"]
    assert texts(saved, "private") == ["first", "while you were out"]
    carol = Client(server, "carol")
    carol.send(type="private_history", **{"with": "alice"})
    assert carol.wait_for("private_history")["messages"] == []


def test_FR_013_groups_survive_a_restart(server):
    alice, bob = Client(server, "alice"), Client(server, "bob")
    make_group(alice, "Squad", bob)
    server.restart()
    alice, bob = Client(server, "alice"), Client(server, "bob")
    bob.drain(0.4)
    alice.send(type="group", group="Squad", text="back again")
    assert bob.wait_for("chat")["text"] == "back again"
    carol = Client(server, "carol")
    alice.send(type="add_member", group="Squad", username="carol")
    assert carol.wait_for("group_update")["members"][:2] == ["alice", "bob"]


# ==================================================== non-functional (NFR)
def _twenty_users(server):
    users = [Client(server, f"u{i}") for i in range(20)]
    make_group(users[0], "Load", *users[1:])
    for u in users:
        u.drain(0.1)
    return users


def test_NFR_001_messages_arrive_within_one_second(server):
    users = _twenty_users(server)
    worst = 0.0
    for i in range(10):
        start = time.time()
        users[i].send(type="group", group="Load", text=f"ping {i}")
        for u in users:
            if u is users[i]:
                continue
            u.wait_for("chat")
        worst = max(worst, time.time() - start)
    assert worst < 1.0, f"slowest round took {worst:.3f} s"


def test_NFR_002_twenty_users_nothing_lost(server):
    users = _twenty_users(server)
    received = {i: [] for i in range(20)}

    def reader(i):
        try:
            while len(received[i]) < 19 * 5:
                m = users[i].recv(5)
                if m and m["type"] == "chat":
                    received[i].append(m["text"])
        except (socket.timeout, TimeoutError):
            pass

    readers = [threading.Thread(target=reader, args=(i,)) for i in range(20)]
    for t in readers:
        t.start()
    for r in range(5):
        for i, u in enumerate(users):
            u.send(type="group", group="Load", text=f"{i}-{r}")
    for t in readers:
        t.join(15)
    assert all(len(set(received[i])) == 19 * 5 for i in range(20))


def test_NFR_003_everyone_sees_the_same_order(server):
    senders = [Client(server, n) for n in ("a", "b", "c")]
    watchers = [Client(server, n) for n in ("w1", "w2")]
    for c in senders + watchers:
        c.drain(0.2)
    for r in range(30):
        gate = threading.Barrier(3)

        def go(c, text):
            gate.wait()
            c.send(type="chat", text=text)

        threads = [threading.Thread(target=go, args=(c, f"{c.name}{r}")) for c in senders]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        seen = [[w.wait_for("chat")["text"] for _ in range(3)] for w in watchers]
        assert seen[0] == seen[1]
        for s in senders:
            s.drain(0.05)


def test_NFR_004_usable_and_configurable(server, folder):
    out = terminal_client(server, ["alice", "/help", "/users", "/quit"])
    for command in ("/msg", "/create", "/join", "/history", "/users", "/quit"):
        assert command in out
    assert "alice" in out
    assert os.path.exists(server.db)  # --db puts the data where it is told


@pytest.mark.skipif(shutil.which("openssl") is None, reason="needs openssl to make a certificate")
def test_NFR_005_security_registration_and_encryption(folder):
    certs = os.path.join(folder, "certs")
    subprocess.run([PYTHON, "-m", "chat.make_cert", "--out", certs], cwd=ROOT, check=True,
                   capture_output=True)
    cert, key = os.path.join(certs, "server.crt"), os.path.join(certs, "server.key")
    srv = Server(folder, tls=(cert, key)).start()
    try:
        alice = Client(srv, "alice", tls_cafile=cert)
        assert alice.reply["type"] == "registered"
        plain = socket.create_connection(("127.0.0.1", srv.port), timeout=3)
        body = json.dumps({"type": "register", "username": "eve"}).encode()
        plain.sendall(struct.pack(">I", len(body)) + body)
        try:
            data = plain.recv(4096)
        except (socket.timeout, ConnectionError):
            data = b""
        assert b"registered" not in data  # no plaintext access to a TLS server
        assert "eve" not in alice.users()
        stranger = Client(srv, tls_cafile=cert)  # connected but never registered
        stranger.send(type="chat", text="let me in")
        assert stranger.wait_for("error")["code"] == "NOT_REGISTERED"
    finally:
        srv.stop()


def test_NFR_006_data_survives_two_restarts(server):
    alice, bob = Client(server, "alice"), Client(server, "bob")
    make_group(alice, "Squad", bob)
    alice.send(type="chat", text="hello all")
    alice.send(type="group", group="Squad", text="hello squad")
    alice.send(type="private", to="bob", text="hello bob")
    alice.wait_for("private_sent")
    server.restart()
    server.restart()
    dave = Client(server, "dave")
    assert "hello all" in history(dave.drain(0.6))
    dave.send(type="join_group", group="Squad")
    assert "hello squad" in history(dave.drain(0.6))
    alice = Client(server, "alice")
    alice.send(type="private_history", **{"with": "bob"})
    assert texts(alice.wait_for("private_history")["messages"], "private") == ["hello bob"]


def test_NFR_007_only_the_newest_messages_are_kept(folder):
    srv = Server(folder, keep=5).start()
    try:
        alice = Client(srv, "alice")
        for i in range(8):
            alice.send(type="chat", text=f"m{i}")
        time.sleep(0.5)
        srv.restart()
        bob = Client(srv, "bob")
        assert history(bob.drain(0.6)) == [f"m{i}" for i in range(3, 8)]
    finally:
        srv.stop()


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
