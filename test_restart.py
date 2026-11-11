"""NFR-006 (#60): everything the chat saves survives a server restart.

Each test starts a real server on a temporary database file (pytest's
tmp_path, deleted automatically), uses it like real clients would, stops
the server, starts a new one on the same file and checks what is still there.
"""

import socket
import time

import pytest

from chat.server import ChatServer

from conftest import WireClient


class Client(WireClient):
    def __init__(self, server, name):
        super().__init__(server)
        self.name = name
        self.send({"type": "register", "username": name})
        assert self.recv_until("registered")["username"] == name

    def drain(self, wait=0.4):
        got = []
        self.sock.settimeout(wait)
        try:
            while True:
                message = self.recv()
                if message is None:
                    break
                got.append(message)
        except socket.timeout:
            pass
        self.sock.settimeout(3.0)
        return got


def wait_until(check, timeout=3.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if check():
            return True
        time.sleep(0.02)
    return False


@pytest.fixture
def restartable(tmp_path):
    """restartable() starts a server on the test's database file; calling
    it again stops the old one first, like restarting the real server."""
    path = str(tmp_path / "chat.db")
    running = []

    def start():
        if running:
            running.pop().stop()
        srv = ChatServer(port=0, db_path=path).start()
        running.append(srv)
        return srv

    yield start
    for srv in running:
        srv.stop()


def history(messages, kind="chat"):
    return [m["text"] for m in messages if m["type"] == kind and m.get("history")]


def test_everyone_history_survives(restartable):
    srv = restartable()
    alice = Client(srv, "alice")
    for text in ("first", "second"):
        alice.send({"type": "chat", "text": text})
    assert wait_until(lambda: len(srv.store.recent_chat()) == 2)
    alice.close()

    srv = restartable()
    bob = Client(srv, "bob")
    assert history(bob.drain()) == ["first", "second"]


def test_private_history_survives(restartable):
    srv = restartable()
    alice, bob = Client(srv, "alice"), Client(srv, "bob")
    alice.send({"type": "private", "to": "bob", "text": "just us"})
    bob.recv_until("private")
    bob.send({"type": "private", "to": "alice", "text": "yes"})
    alice.recv_until("private")
    assert wait_until(lambda: len(srv.store.private_between("alice", "bob")) == 2)

    srv = restartable()
    saved = srv.store.private_between("alice", "bob")
    assert [(m["from"], m["to"], m["text"]) for m in saved] == [
        ("alice", "bob", "just us"), ("bob", "alice", "yes")]
    assert srv.store.private_between("alice", "carol") == []


def test_offline_messages_survive(restartable):
    srv = restartable()
    bob = Client(srv, "bob")
    bob.send({"type": "quit"})
    assert wait_until(lambda: "bob" not in srv.users)
    alice = Client(srv, "alice")
    alice.send({"type": "private", "to": "bob", "text": "while you were out"})
    assert alice.recv_until("private_sent")["queued"] is True

    srv = restartable()
    bob = Client(srv, "bob")
    waiting = [m for m in bob.drain() if m["type"] == "private"]
    assert [(m["from"], m["text"], m["offline"]) for m in waiting] == [
        ("alice", "while you were out", True)]


def test_groups_survive(restartable):
    srv = restartable()
    alice, bob = Client(srv, "alice"), Client(srv, "bob")
    alice.send({"type": "create_group", "group": "Squad"})
    alice.recv_until("group_update")
    bob.send({"type": "join_group", "group": "Squad"})
    bob.recv_until("group_update")

    srv = restartable()
    assert srv.groups.names() == ["Squad"]
    assert srv.groups.members("Squad") == ["alice", "bob"]
    assert srv.groups.admin("Squad") == "alice"
    alice, bob = Client(srv, "alice"), Client(srv, "bob")
    alice.send({"type": "group", "group": "Squad", "text": "back again"})
    assert bob.recv_until("chat")["text"] == "back again"


def test_group_history_survives(restartable):
    srv = restartable()
    alice = Client(srv, "alice")
    alice.send({"type": "create_group", "group": "Squad"})
    alice.recv_until("group_update")
    alice.send({"type": "group", "group": "Squad", "text": "remember me"})
    assert wait_until(lambda: len(srv.store.group_messages("Squad")) == 1)

    srv = restartable()
    carol = Client(srv, "carol")
    carol.send({"type": "join_group", "group": "Squad"})
    assert history(carol.drain()) == ["remember me"]


def test_everything_survives_two_restarts(restartable):
    srv = restartable()
    alice, bob = Client(srv, "alice"), Client(srv, "bob")
    alice.send({"type": "create_group", "group": "Squad"})
    alice.recv_until("group_update")
    bob.send({"type": "join_group", "group": "Squad"})
    bob.recv_until("group_update")
    alice.send({"type": "chat", "text": "hello all"})
    alice.send({"type": "group", "group": "Squad", "text": "hello squad"})
    alice.send({"type": "private", "to": "bob", "text": "hello bob"})
    alice.recv_until("private_sent")
    assert wait_until(lambda: srv.store.count() == 3)

    restartable()
    srv = restartable()  # a second restart changes nothing
    assert srv.store.count() == 3
    assert srv.groups.members("Squad") == ["alice", "bob"]
    dave = Client(srv, "dave")
    assert history(dave.drain()) == ["hello all"]
    dave.send({"type": "join_group", "group": "Squad"})
    assert history(dave.drain()) == ["hello squad"]
    assert [m["text"] for m in srv.store.private_between("alice", "bob")] == ["hello bob"]


def test_memory_database_keeps_nothing():
    srv = ChatServer(port=0).start()
    alice = Client(srv, "alice")
    alice.send({"type": "chat", "text": "gone"})
    assert wait_until(lambda: srv.store.count() == 1)
    srv.stop()
    srv = ChatServer(port=0).start()
    try:
        assert srv.store.count() == 0
        assert srv.groups.names() == []
    finally:
        srv.stop()
