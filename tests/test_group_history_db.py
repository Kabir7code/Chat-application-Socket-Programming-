"""FR-010 (#61): group history is read from the database."""

import socket
import time

from chat.groups import HISTORY_SIZE, GroupManager
from chat.server import ChatServer
from chat.storage import MessageStore

from conftest import WireClient


def group_chat(text, sender="alice", group="Squad"):
    return {"type": "chat", "id": 1, "time": "2026-11-09T10:00:00+00:00",
            "from": sender, "text": text, "context": "group", "group": group}


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


def history_texts(messages):
    return [m["text"] for m in messages if m.get("history")]


def register(srv, name):
    client = WireClient(srv)
    client.send({"type": "register", "username": name})
    client.recv_until("registered")
    return client


def wait_saved(store, group, count):
    deadline = time.time() + 3.0
    while len(store.group_messages(group, 100)) < count:
        assert time.time() < deadline, "group messages were never saved"
        time.sleep(0.02)


# --------------------------------------------------------------- unit tests
def test_history_comes_from_the_store():
    store = MessageStore()
    groups = GroupManager(store)
    groups.create("Squad", "alice")
    store.save_group(group_chat("saved"))
    assert [m["text"] for m in groups.history("Squad")] == ["saved"]


def test_record_does_not_keep_a_second_copy_in_memory():
    store = MessageStore()
    groups = GroupManager(store)
    groups.create("Squad", "alice")
    groups.record("Squad", group_chat("only in memory"))
    assert groups.history("Squad") == []


def test_store_history_keeps_the_last_10_oldest_first():
    store = MessageStore()
    groups = GroupManager(store)
    groups.create("Squad", "alice")
    for i in range(15):
        store.save_group(group_chat(f"m{i}"))
    assert HISTORY_SIZE == 10
    assert [m["text"] for m in groups.history("Squad")] == [f"m{i}" for i in range(5, 15)]


def test_unknown_group_has_no_history():
    store = MessageStore()
    store.save_group(group_chat("orphan", group="Ghost"))
    assert GroupManager(store).history("Ghost") == []


def test_deleting_a_group_deletes_its_messages():
    store = MessageStore()
    groups = GroupManager(store)
    groups.create("Squad", "alice")
    store.save_group(group_chat("old"))
    store.save_group(group_chat("other group", group="Team"))
    groups.leave("Squad", "alice")  # last member leaves -> group deleted
    assert store.group_messages("Squad") == []
    assert [m["text"] for m in store.group_messages("Team")] == ["other group"]
    groups.create("Squad", "bob")
    assert groups.history("Squad") == []


def test_without_a_store_history_stays_in_memory():
    groups = GroupManager()
    groups.create("Squad", "alice")
    groups.record("Squad", group_chat("hi"))
    assert [m["text"] for m in groups.history("Squad")] == ["hi"]


# ------------------------------------------------------ real server restart
def test_group_history_survives_a_server_restart(tmp_path):
    path = str(tmp_path / "chat.db")
    srv = ChatServer(port=0, db_path=path).start()
    alice = register(srv, "alice")
    alice.send({"type": "create_group", "group": "Squad"})
    alice.recv_until("group_update")
    for i in range(3):
        alice.send({"type": "group", "group": "Squad", "text": f"m{i}"})
    wait_saved(srv.store, "Squad", 3)
    srv.stop()
    alice.close()

    srv = ChatServer(port=0, db_path=path).start()
    try:
        bob = register(srv, "bob")
        bob.send({"type": "join_group", "group": "Squad"})
        got = drain(bob)
        assert history_texts(got) == ["m0", "m1", "m2"]
        first = next(m for m in got if m.get("history"))
        assert first["from"] == "alice" and first["group"] == "Squad"
        assert first["context"] == "group"
    finally:
        srv.stop()


def test_message_sent_while_someone_joins_arrives_once(server, connect):
    alice, bob = connect("alice"), connect("bob")
    alice.send({"type": "create_group", "group": "Squad"})
    alice.recv_until("group_update")
    for i in range(20):
        alice.send({"type": "group", "group": "Squad", "text": f"m{i}"})
    bob.send({"type": "join_group", "group": "Squad"})
    for i in range(20, 40):
        alice.send({"type": "group", "group": "Squad", "text": f"m{i}"})
    seen = [m["text"] for m in drain(bob, wait=0.8) if m["type"] == "chat"]
    assert len(seen) == len(set(seen)), seen  # nothing twice
    first = int(seen[0][1:])
    assert seen == [f"m{i}" for i in range(first, 40)]  # and no gaps
