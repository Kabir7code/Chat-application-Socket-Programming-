"""FR-011 (#56): a new user sees the recent Everyone chat when they log in."""

import socket
import time

from chat.client import format_message
from chat.server import CHAT_HISTORY_SIZE, ChatServer

from conftest import WireClient


def drain(client, wait=0.4):
    """Every message that arrives within `wait` seconds."""
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


def say(server, client, *texts):
    """Send Everyone messages and wait until the server has saved them."""
    for text in texts:
        client.send({"type": "chat", "text": text})
    deadline = time.time() + 3.0
    while [m["text"] for m in server.store.recent_chat(1)] != [texts[-1]]:
        assert time.time() < deadline, "messages were never saved"
        time.sleep(0.02)


def test_history_size_is_20():
    assert CHAT_HISTORY_SIZE == 20


def test_first_user_gets_no_history(server, connect):
    alice = connect("alice")
    assert history_texts(drain(alice)) == []


def test_partial_history(server, connect):
    alice = connect("alice")
    say(server, alice, "one", "two", "three")
    bob = connect("bob")
    assert history_texts(drain(bob)) == ["one", "two", "three"]


def test_full_history_keeps_the_last_20_oldest_first(server, connect):
    alice = connect("alice")
    say(server, alice, *[f"m{i}" for i in range(25)])
    bob = connect("bob")
    assert history_texts(drain(bob)) == [f"m{i}" for i in range(5, 25)]


def test_history_comes_right_after_registered(server, connect):
    alice = connect("alice")
    say(server, alice, "hello")
    bob = WireClient(server)
    try:
        bob.send({"type": "register", "username": "bob"})
        assert bob.recv()["type"] == "registered"
        first = bob.recv()
        assert first["type"] == "chat" and first["history"] is True
        assert first["from"] == "alice" and first["text"] == "hello"
        assert first["context"] == "general" and "time" in first and "id" in first
    finally:
        bob.close()


def test_private_and_group_messages_are_not_in_history(server, connect):
    alice, bob = connect("alice"), connect("bob")
    alice.send({"type": "private", "to": "bob", "text": "secret"})
    bob.recv_until("private")
    alice.send({"type": "create_group", "group": "Squad"})
    alice.recv_until("group_update")
    alice.send({"type": "group", "group": "Squad", "text": "squad only"})
    say(server, alice, "public")
    carol = connect("carol")
    assert history_texts(drain(carol)) == ["public"]


def test_live_messages_are_not_marked_history(server, connect):
    alice, bob = connect("alice"), connect("bob")
    drain(bob)
    alice.send({"type": "chat", "text": "live"})
    message = bob.recv_until("chat")
    assert message["text"] == "live" and "history" not in message


def test_saved_messages_are_not_changed_by_marking(server, connect):
    alice = connect("alice")
    say(server, alice, "hello")
    connect("bob")
    assert "history" not in server.store.recent_chat()[0]


def test_history_survives_a_server_restart(tmp_path):
    path = str(tmp_path / "chat.db")
    srv = ChatServer(port=0, db_path=path).start()
    alice = WireClient(srv)
    alice.send({"type": "register", "username": "alice"})
    alice.recv_until("registered")
    say(srv, alice, "before the restart")
    alice.close()
    srv.stop()

    srv = ChatServer(port=0, db_path=path).start()
    bob = WireClient(srv)
    try:
        bob.send({"type": "register", "username": "bob"})
        bob.recv_until("registered")
        assert history_texts(drain(bob)) == ["before the restart"]
    finally:
        bob.close()
        srv.stop()


def test_no_message_is_lost_or_doubled_while_joining(server, connect):
    """A message sent while someone is logging in reaches them exactly once:
    either in the history or live, never both and never neither."""
    alice = connect("alice")
    for i in range(20):
        alice.send({"type": "chat", "text": f"m{i}"})
    bob = connect("bob")
    for i in range(20, 40):
        alice.send({"type": "chat", "text": f"m{i}"})
    texts = [m["text"] for m in drain(bob, wait=0.8) if m["type"] == "chat"]
    # bob may have joined part-way through the first 20, so he sees the
    # last 20 saved before he joined, then everything after - no gaps.
    assert len(texts) == len(set(texts))
    assert texts[-1] == "m39"
    first = int(texts[0][1:])
    assert texts == [f"m{i}" for i in range(first, 40)]


def test_terminal_client_shows_earlier():
    message = {"type": "chat", "context": "general", "from": "alice", "text": "hi",
               "history": True}
    assert format_message(message) == "(earlier) alice: hi"


def test_terminal_client_live_message_unchanged():
    message = {"type": "chat", "context": "general", "from": "alice", "text": "hi"}
    assert format_message(message) == "alice: hi"
