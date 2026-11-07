"""FR-011 (#50): the persistent message store."""

import sqlite3
import threading
import time

from chat import protocol
from chat.storage import MessageStore


def chat(text, sender="alice"):
    message = protocol.make_chat_message(text, sender)
    message["context"] = "general"
    return message


def private(text, sender, to):
    return {"type": "private", "id": protocol.new_message_id(), "time": protocol.timestamp(),
            "from": sender, "to": to, "text": text}


def group_chat(text, sender, group):
    message = protocol.make_chat_message(text, sender)
    message.update(context="group", group=group)
    return message


def texts(messages):
    return [m["text"] for m in messages]


def wait_for(check, timeout=3.0):
    """Server threads save messages; give them a moment."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if check():
            return True
        time.sleep(0.02)
    return False


# ------------------------------------------------------------- unit tests
def test_new_store_is_empty():
    store = MessageStore()
    assert store.count() == 0
    assert store.recent_chat() == []


def test_chat_message_round_trip():
    store = MessageStore()
    sent = chat("hello")
    assert store.save_chat(sent) is True
    [loaded] = store.recent_chat()
    assert loaded == sent  # same type, id, time, sender, text and context


def test_private_message_round_trip():
    store = MessageStore()
    sent = private("psst", "alice", "bob")
    store.save_private(sent)
    assert store.private_between("alice", "bob") == [sent]


def test_group_message_round_trip():
    store = MessageStore()
    sent = group_chat("hi squad", "alice", "Squad")
    store.save_group(sent)
    assert store.group_messages("Squad") == [sent]


def test_messages_come_back_oldest_first():
    store = MessageStore()
    for i in range(5):
        store.save_chat(chat(f"m{i}"))
    assert texts(store.recent_chat()) == ["m0", "m1", "m2", "m3", "m4"]


def test_limit_keeps_the_most_recent():
    store = MessageStore()
    for i in range(30):
        store.save_chat(chat(f"m{i}"))
    assert texts(store.recent_chat(limit=20)) == [f"m{i}" for i in range(10, 30)]


def test_kinds_are_kept_apart():
    store = MessageStore()
    store.save_chat(chat("to everyone"))
    store.save_private(private("secret", "alice", "bob"))
    store.save_group(group_chat("group only", "alice", "Squad"))
    assert texts(store.recent_chat()) == ["to everyone"]
    assert texts(store.private_between("alice", "bob")) == ["secret"]
    assert texts(store.group_messages("Squad")) == ["group only"]


def test_private_history_has_both_directions_and_nobody_else():
    store = MessageStore()
    store.save_private(private("hi bob", "alice", "bob"))
    store.save_private(private("hi carol", "alice", "carol"))
    store.save_private(private("hi alice", "bob", "alice"))
    store.save_private(private("carol to bob", "carol", "bob"))
    assert texts(store.private_between("alice", "bob")) == ["hi bob", "hi alice"]
    assert texts(store.private_between("bob", "alice")) == ["hi bob", "hi alice"]


def test_groups_are_kept_apart():
    store = MessageStore()
    store.save_group(group_chat("for squad", "alice", "Squad"))
    store.save_group(group_chat("for team", "alice", "Team"))
    assert texts(store.group_messages("Squad")) == ["for squad"]
    assert texts(store.group_messages("Team")) == ["for team"]


def test_tables_are_created_in_a_new_file(tmp_path):
    path = tmp_path / "chat.db"
    MessageStore(str(path)).close()
    with sqlite3.connect(path) as db:
        tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert "messages" in tables


def test_messages_survive_reopening_the_file(tmp_path):
    path = str(tmp_path / "chat.db")
    store = MessageStore(path)
    store.save_chat(chat("still here?"))
    store.save_private(private("yes", "bob", "alice"))
    store.close()

    reopened = MessageStore(path)
    assert texts(reopened.recent_chat()) == ["still here?"]
    assert texts(reopened.private_between("alice", "bob")) == ["yes"]


def test_safe_to_use_from_many_threads():
    store = MessageStore()

    def write(n):
        for i in range(100):
            store.save_chat(chat(f"{n}-{i}", sender=f"user{n}"))

    threads = [threading.Thread(target=write, args=(n,)) for n in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert store.count() == 800
    assert len(set(texts(store.recent_chat(limit=1000)))) == 800


def test_a_storage_error_is_logged_not_raised(caplog):
    store = MessageStore()
    store.close()  # every save will now fail
    assert store.save_chat(chat("lost")) is False
    assert "Could not save chat message from alice" in caplog.text


# ------------------------------------------------- the server saves messages
def test_server_saves_broadcast_messages(server, connect):
    alice, bob = connect("alice"), connect("bob")
    alice.send({"type": "chat", "text": "hello everyone"})
    delivered = bob.recv_until("chat")
    assert wait_for(lambda: server.store.count() == 1)
    assert server.store.recent_chat() == [delivered]


def test_server_saves_delivered_private_messages(server, connect):
    alice, bob = connect("alice"), connect("bob")
    alice.send({"type": "private", "to": "bob", "text": "just for you"})
    delivered = bob.recv_until("private")
    alice.recv_until("private_sent")
    assert server.store.private_between("alice", "bob") == [delivered]


def test_private_message_to_unknown_user_is_not_saved(server, connect):
    alice = connect("alice")
    alice.send({"type": "private", "to": "ghost", "text": "anyone?"})
    assert alice.recv_until("error")["code"] == "USER_NOT_FOUND"
    assert server.store.count() == 0


def test_server_saves_group_messages(server, connect):
    alice, bob = connect("alice"), connect("bob")
    alice.send({"type": "create_group", "group": "Squad"})
    alice.recv_until("group_update")
    bob.send({"type": "join_group", "group": "Squad"})
    bob.recv_until("group_update")
    alice.send({"type": "group", "group": "Squad", "text": "hi squad"})
    delivered = bob.recv_until("chat")
    assert wait_for(lambda: server.store.count() == 1)
    assert server.store.group_messages("Squad") == [delivered]


def test_rejected_messages_are_not_saved(server, connect):
    alice = connect("alice")
    alice.send({"type": "chat", "text": "   "})
    assert alice.recv_until("error")["code"] == "EMPTY_MESSAGE"
    assert server.store.count() == 0


def test_saved_order_matches_delivery_order(server, connect):
    alice, bob, carol = connect("alice"), connect("bob"), connect("carol")

    def blast(client, name):
        for i in range(30):
            client.send({"type": "chat", "text": f"{name}-{i}"})

    threads = [threading.Thread(target=blast, args=(c, n)) for c, n in ((alice, "a"), (bob, "b"))]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    seen = []
    while len(seen) < 60:
        message = carol.recv()
        if message["type"] == "chat":
            seen.append(message["text"])
    assert wait_for(lambda: server.store.count() == 60)
    assert texts(server.store.recent_chat(limit=60)) == seen


def test_server_with_a_database_file(tmp_path):
    from chat.server import ChatServer

    path = tmp_path / "chat.db"
    srv = ChatServer(port=0, db_path=str(path)).start()
    srv.stop()
    assert path.exists()
