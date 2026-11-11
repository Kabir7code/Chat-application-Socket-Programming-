"""FR-012 (#59): private messages sent while someone is offline."""

import socket
import threading
import time

from chat.client import format_message
from chat.server import ChatServer
from chat.storage import MessageStore

from conftest import WireClient


def drain(client, wait=0.4):
    got = []
    client.sock.settimeout(wait)
    try:
        while True:
            message = client.recv()
            if message is None:
                break
            got.append(message)
    except socket.timeout:
        pass
    client.sock.settimeout(3.0)
    return got


def wait_until(check, timeout=3.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if check():
            return True
        time.sleep(0.02)
    return False


def privates(messages):
    return [m for m in messages if m["type"] == "private"]


def went_offline(server, connect, name):
    """Log `name` in once, then quit, so the server knows them."""
    client = connect(name)
    client.send({"type": "quit"})
    assert wait_until(lambda: name not in server.users)


# --------------------------------------------------------------- storage
def test_users_are_remembered():
    store = MessageStore()
    assert not store.is_known_user("bob")
    store.remember_user("bob")
    store.remember_user("bob")  # twice is harmless
    assert store.is_known_user("bob")


def test_waiting_messages_come_out_oldest_first_and_once():
    store = MessageStore()
    for i in range(3):
        store.queue_offline({"id": i, "time": f"t{i}", "from": "alice", "to": "bob",
                             "text": f"m{i}"})
    store.queue_offline({"id": 9, "time": "t9", "from": "alice", "to": "carol", "text": "c"})
    taken = store.take_offline("bob")
    assert [m["text"] for m in taken] == ["m0", "m1", "m2"]
    assert all(m["type"] == "private" and m["offline"] is True for m in taken)
    assert taken[0] == {"type": "private", "id": 0, "time": "t0", "from": "alice",
                        "to": "bob", "text": "m0", "offline": True}
    assert store.take_offline("bob") == []
    assert store.waiting_count("carol") == 1


def test_waiting_messages_survive_reopening_the_file(tmp_path):
    path = str(tmp_path / "chat.db")
    store = MessageStore(path)
    store.remember_user("bob")
    store.queue_offline({"id": 1, "time": "t", "from": "alice", "to": "bob", "text": "hi"})
    store.close()
    reopened = MessageStore(path)
    assert reopened.is_known_user("bob")
    assert [m["text"] for m in reopened.take_offline("bob")] == ["hi"]


# ---------------------------------------------------------------- server
def test_sender_is_told_it_will_be_delivered_later(server, connect):
    went_offline(server, connect, "bob")
    alice = connect("alice")
    alice.send({"type": "private", "to": "bob", "text": "call me"})
    sent = alice.recv_until("private_sent")
    assert sent["queued"] is True and sent["to"] == "bob" and sent["text"] == "call me"
    assert server.store.waiting_count("bob") == 1


def test_recipient_gets_waiting_messages_after_logging_in(server, connect):
    went_offline(server, connect, "bob")
    alice = connect("alice")
    for text in ("one", "two", "three"):
        alice.send({"type": "private", "to": "bob", "text": text})
        alice.recv_until("private_sent")
    bob = WireClient(server)
    try:
        bob.send({"type": "register", "username": "bob"})
        assert bob.recv()["type"] == "registered"
        got = privates(drain(bob))
        assert [m["text"] for m in got] == ["one", "two", "three"]
        assert all(m["from"] == "alice" and m["offline"] is True for m in got)
    finally:
        bob.close()


def test_each_waiting_message_is_delivered_once(server, connect):
    went_offline(server, connect, "bob")
    alice = connect("alice")
    alice.send({"type": "private", "to": "bob", "text": "once"})
    alice.recv_until("private_sent")
    bob = connect("bob")
    assert [m["text"] for m in privates(drain(bob))] == ["once"]
    bob.send({"type": "quit"})
    assert wait_until(lambda: "bob" not in server.users)
    again = connect("bob")
    assert privates(drain(again)) == []


def test_unknown_name_still_gets_user_not_found(server, connect):
    alice = connect("alice")
    alice.send({"type": "private", "to": "ghost", "text": "anyone?"})
    assert alice.recv_until("error")["code"] == "USER_NOT_FOUND"
    assert server.store.waiting_count("ghost") == 0


def test_online_messages_are_not_queued(server, connect):
    alice, bob = connect("alice"), connect("bob")
    alice.send({"type": "private", "to": "bob", "text": "live"})
    assert bob.recv_until("private")["text"] == "live"
    assert "queued" not in alice.recv_until("private_sent")
    assert server.store.waiting_count("bob") == 0


def test_waiting_message_is_kept_in_private_history(server, connect):
    went_offline(server, connect, "bob")
    alice = connect("alice")
    alice.send({"type": "private", "to": "bob", "text": "saved"})
    alice.recv_until("private_sent")
    assert [m["text"] for m in server.store.private_between("alice", "bob")] == ["saved"]


def test_nothing_is_lost_while_the_recipient_logs_in(server, connect):
    went_offline(server, connect, "bob")
    alice = connect("alice")
    total = 30

    def blast():
        for i in range(total):
            alice.send({"type": "private", "to": "bob", "text": f"m{i}"})

    sender = threading.Thread(target=blast)
    sender.start()
    bob = connect("bob")
    sender.join()
    texts = []
    deadline = time.time() + 5
    while len(texts) < total and time.time() < deadline:
        texts += [m["text"] for m in privates(drain(bob, wait=0.3))]
    assert sorted(texts, key=lambda t: int(t[1:])) == [f"m{i}" for i in range(total)]
    assert len(texts) == total  # nothing twice
    assert server.store.waiting_count("bob") == 0


def test_waiting_messages_survive_a_server_restart(tmp_path):
    path = str(tmp_path / "chat.db")
    srv = ChatServer(port=0, db_path=path).start()
    for name in ("bob", "alice"):
        client = WireClient(srv)
        client.send({"type": "register", "username": name})
        client.recv_until("registered")
        if name == "bob":
            client.send({"type": "quit"})
            assert wait_until(lambda: "bob" not in srv.users)
        else:
            client.send({"type": "private", "to": "bob", "text": "after restart"})
            assert client.recv_until("private_sent")["queued"] is True
    srv.stop()

    srv = ChatServer(port=0, db_path=path).start()
    bob = WireClient(srv)
    try:
        bob.send({"type": "register", "username": "bob"})
        bob.recv_until("registered")
        assert [m["text"] for m in privates(drain(bob))] == ["after restart"]
    finally:
        bob.close()
        srv.stop()


# ------------------------------------------------------- terminal client
def test_client_shows_queued_and_offline_messages():
    queued = {"type": "private_sent", "to": "bob", "text": "hi", "queued": True}
    assert format_message(queued) == "[private to bob] hi (offline - delivered when they log in)"
    waiting = {"type": "private", "from": "alice", "text": "hi", "offline": True}
    assert format_message(waiting) == "[private] alice (while you were away): hi"
