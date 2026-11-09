"""FR-012 (#57): /history <user> shows a private conversation."""

import time

from chat.client import HELP, format_message, parse_command
from chat.server import PRIVATE_HISTORY_SIZE, ChatServer

from conftest import WireClient


def wait_until(check, timeout=3.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if check():
            return True
        time.sleep(0.02)
    return False


def chat_privately(server, sender, receiver, text):
    sender.send({"type": "private", "to": receiver.name, "text": text})
    receiver.recv_until("private")
    sender.recv_until("private_sent")


def named(client, name):
    client.name = name
    return client


def ask(client, other):
    client.send({"type": "private_history", "with": other})
    return client.recv_until("private_history")


def texts(reply):
    return [m["text"] for m in reply["messages"]]


# ---------------------------------------------------------------- server
def test_history_shows_both_directions_oldest_first(server, connect):
    alice, bob = named(connect("alice"), "alice"), named(connect("bob"), "bob")
    chat_privately(server, alice, bob, "hi bob")
    chat_privately(server, bob, alice, "hi alice")
    chat_privately(server, alice, bob, "how are you?")
    reply = ask(alice, "bob")
    assert reply["with"] == "bob"
    assert texts(reply) == ["hi bob", "hi alice", "how are you?"]
    assert [m["from"] for m in reply["messages"]] == ["alice", "bob", "alice"]
    assert all(m["history"] is True for m in reply["messages"])
    assert texts(ask(bob, "alice")) == texts(reply)  # same from either side


def test_nobody_else_can_read_it(server, connect):
    alice, bob = named(connect("alice"), "alice"), named(connect("bob"), "bob")
    carol = connect("carol")
    chat_privately(server, alice, bob, "secret")
    assert ask(carol, "bob")["messages"] == []
    assert ask(carol, "alice")["messages"] == []


def test_only_the_last_20_are_shown(server, connect):
    alice, bob = named(connect("alice"), "alice"), named(connect("bob"), "bob")
    for i in range(25):
        chat_privately(server, alice, bob, f"m{i}")
    assert PRIVATE_HISTORY_SIZE == 20
    assert texts(ask(alice, "bob")) == [f"m{i}" for i in range(5, 25)]


def test_other_conversations_are_left_out(server, connect):
    alice, bob = named(connect("alice"), "alice"), named(connect("bob"), "bob")
    carol = named(connect("carol"), "carol")
    chat_privately(server, alice, bob, "to bob")
    chat_privately(server, alice, carol, "to carol")
    alice.send({"type": "chat", "text": "to everyone"})
    assert texts(ask(alice, "bob")) == ["to bob"]


def test_empty_history(server, connect):
    alice = connect("alice")
    assert ask(alice, "nobody")["messages"] == []


def test_bad_name_is_an_error(server, connect):
    alice = connect("alice")
    alice.send({"type": "private_history", "with": "not a name!"})
    assert alice.recv_until("error")["code"] == "INVALID_USERNAME"


def test_must_be_registered(server, connect):
    stranger = connect()
    stranger.send({"type": "private_history", "with": "bob"})
    assert stranger.recv_until("error")["code"] == "NOT_REGISTERED"


def test_history_works_after_a_restart(tmp_path):
    path = str(tmp_path / "chat.db")
    srv = ChatServer(port=0, db_path=path).start()
    clients = {}
    for name in ("alice", "bob"):
        client = named(WireClient(srv), name)
        client.send({"type": "register", "username": name})
        client.recv_until("registered")
        clients[name] = client
    chat_privately(srv, clients["alice"], clients["bob"], "before restart")
    srv.stop()

    srv = ChatServer(port=0, db_path=path).start()
    try:
        bob = WireClient(srv)
        bob.send({"type": "register", "username": "bob"})
        bob.recv_until("registered")
        assert texts(ask(bob, "alice")) == ["before restart"]
    finally:
        srv.stop()


# ------------------------------------------------------- terminal client
def test_parse_history_command():
    assert parse_command("/history bob") == ({"type": "private_history", "with": "bob"}, None)
    assert parse_command("/history")[1] == "Usage: /history <user>"
    assert parse_command("/history bob carol")[1] == "Usage: /history <user>"


def test_history_is_in_help():
    assert "/history <user>" in HELP


def test_client_shows_the_conversation():
    reply = {"type": "private_history", "with": "bob", "messages": [
        {"type": "private", "from": "alice", "to": "bob", "text": "hi"},
        {"type": "private", "from": "bob", "to": "alice", "text": "hey"},
    ]}
    assert format_message(reply) == (
        "* Private messages with bob (last 2):\n  alice: hi\n  bob: hey")


def test_client_shows_empty_history():
    reply = {"type": "private_history", "with": "bob", "messages": []}
    assert format_message(reply) == "* No private messages with bob yet."
