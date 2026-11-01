"""FR-010 (#18): someone who joins a group sees its recent messages."""

import socket
import time

from chat.client import format_message
from chat.groups import HISTORY_SIZE, GroupManager


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


def wait_for_history(server, group, count, timeout=3.0):
    """Wait until the server has stored `count` messages for the group.
    Each user is handled on their own thread, so a join sent right after
    some messages could otherwise reach the server before they do."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if len(server.groups.history(group)) >= count:
            return
        time.sleep(0.02)
    raise AssertionError("messages never reached the group history")


def history_texts(messages):
    return [m["text"] for m in messages if m.get("history")]


def setup_group(alice, bob):
    alice.send({"type": "create_group", "group": "Squad"})
    alice.recv_until("group_update")
    bob.send({"type": "join_group", "group": "Squad"})
    bob.recv_until("group_update")
    alice.recv_until("group_update")


# ------------------------------------------------------------- unit tests
def test_history_is_empty_for_a_new_group():
    groups = GroupManager()
    groups.create("Squad", "alice")
    assert groups.history("Squad") == []


def test_history_keeps_messages_oldest_first():
    groups = GroupManager()
    groups.create("Squad", "alice")
    for i in range(3):
        groups.record("Squad", {"type": "chat", "text": f"m{i}"})
    assert [m["text"] for m in groups.history("Squad")] == ["m0", "m1", "m2"]


def test_history_keeps_only_the_most_recent_messages():
    groups = GroupManager()
    groups.create("Squad", "alice")
    for i in range(HISTORY_SIZE + 5):
        groups.record("Squad", {"type": "chat", "text": f"m{i}"})
    texts = [m["text"] for m in groups.history("Squad")]
    assert texts == [f"m{i}" for i in range(5, HISTORY_SIZE + 5)]


def test_history_is_deleted_with_the_group():
    groups = GroupManager()
    groups.create("Squad", "alice")
    groups.record("Squad", {"type": "chat", "text": "hi"})
    groups.leave("Squad", "alice")  # last member leaves, group is deleted
    groups.create("Squad", "bob")
    assert groups.history("Squad") == []


def test_history_returns_copies():
    groups = GroupManager()
    groups.create("Squad", "alice")
    groups.record("Squad", {"type": "chat", "text": "hi"})
    groups.history("Squad")[0]["text"] = "changed"
    assert groups.history("Squad")[0]["text"] == "hi"


# ------------------------------------------------------ integration tests
def test_new_member_receives_recent_messages(server, connect):
    alice, bob, carol = connect("alice"), connect("bob"), connect("carol")
    setup_group(alice, bob)
    alice.send({"type": "group", "group": "Squad", "text": "first"})
    wait_for_history(server, "Squad", 1)
    bob.send({"type": "group", "group": "Squad", "text": "second"})
    wait_for_history(server, "Squad", 2)

    carol.send({"type": "join_group", "group": "Squad"})
    assert history_texts(drain(carol)) == ["first", "second"]


def test_history_messages_are_marked_and_keep_sender(server, connect):
    alice, bob = connect("alice"), connect("bob")
    alice.send({"type": "create_group", "group": "Squad"})
    alice.recv_until("group_update")
    alice.send({"type": "group", "group": "Squad", "text": "hello"})
    wait_for_history(server, "Squad", 1)

    bob.send({"type": "join_group", "group": "Squad"})
    [message] = [m for m in drain(bob) if m.get("history")]
    assert message["from"] == "alice"
    assert message["group"] == "Squad"
    assert "id" in message


def test_added_member_receives_recent_messages(server, connect):
    alice, bob = connect("alice"), connect("bob")
    alice.send({"type": "create_group", "group": "Squad"})
    alice.recv_until("group_update")
    alice.send({"type": "group", "group": "Squad", "text": "before bob"})
    wait_for_history(server, "Squad", 1)

    alice.send({"type": "add_member", "group": "Squad", "username": "bob"})
    assert history_texts(drain(bob)) == ["before bob"]


def test_existing_members_do_not_get_history_again(server, connect):
    alice, bob, carol = connect("alice"), connect("bob"), connect("carol")
    setup_group(alice, bob)
    alice.send({"type": "group", "group": "Squad", "text": "hi"})
    drain(bob)

    carol.send({"type": "join_group", "group": "Squad"})
    assert history_texts(drain(bob)) == []
    assert history_texts(drain(alice)) == []


def test_new_member_of_an_empty_group_gets_no_history(server, connect):
    alice, bob = connect("alice"), connect("bob")
    alice.send({"type": "create_group", "group": "Squad"})
    alice.recv_until("group_update")
    bob.send({"type": "join_group", "group": "Squad"})
    assert history_texts(drain(bob)) == []


def test_only_the_last_messages_are_shown(server, connect):
    alice, bob = connect("alice"), connect("bob")
    alice.send({"type": "create_group", "group": "Squad"})
    alice.recv_until("group_update")
    for i in range(HISTORY_SIZE + 3):
        alice.send({"type": "group", "group": "Squad", "text": f"m{i}"})
    last = f"m{HISTORY_SIZE + 2}"
    deadline = time.time() + 3
    while time.time() < deadline:
        stored = server.groups.history("Squad")
        if stored and stored[-1]["text"] == last:
            break
        time.sleep(0.02)

    bob.send({"type": "join_group", "group": "Squad"})
    assert history_texts(drain(bob)) == [f"m{i}" for i in range(3, HISTORY_SIZE + 3)]


def test_client_shows_history_as_earlier():
    line = format_message({"type": "chat", "context": "group", "group": "Squad",
                           "from": "alice", "text": "hi", "history": True})
    assert line == "[Squad] (earlier) alice: hi"
