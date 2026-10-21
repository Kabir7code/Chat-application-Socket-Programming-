"""Registration (FR-001), real-time delivery (FR-003) and presence (FR-006)."""

import time

from chat import config


# ------------------------------------------------------------ FR-001 username
def test_unique_username_is_accepted(server, connect):
    client = connect()
    client.send({"type": "register", "username": "rahul"})
    reply = client.recv()
    assert reply == {"type": "registered", "username": "rahul", "users": ["rahul"]}
    assert "rahul" in server.users


def test_duplicate_username_is_rejected(server, connect):
    connect("rahul")
    second = connect()
    second.send({"type": "register", "username": "rahul"})
    reply = second.recv()
    assert reply["code"] == "USERNAME_TAKEN"
    assert reply["message"] == "Username already taken."


def test_can_retry_with_another_username(server, connect):
    connect("rahul")
    second = connect()
    second.send({"type": "register", "username": "rahul"})
    assert second.recv()["code"] == "USERNAME_TAKEN"
    second.send({"type": "register", "username": "rahul2"})
    assert second.recv()["type"] == "registered"


def test_empty_username_is_rejected(server, connect):
    client = connect()
    client.send({"type": "register", "username": "   "})
    assert client.recv()["code"] == "INVALID_USERNAME"


def test_too_long_username_is_rejected(server, connect):
    client = connect()
    client.send({"type": "register", "username": "a" * 50})
    assert client.recv()["code"] == "INVALID_USERNAME"


def test_username_is_freed_after_leaving(server, connect):
    first = connect("rahul")
    first.close()
    deadline = time.time() + 3
    while "rahul" in server.users and time.time() < deadline:
        time.sleep(0.05)
    connect("rahul")  # would fail if the name were still taken


# ---------------------------------------------------- FR-003 real-time delivery
def test_message_carries_sender_name_and_context(server, connect):
    alice, bob = connect("alice"), connect("bob")
    alice.send({"type": "chat", "text": "Hello there"})
    message = bob.recv_until("chat")
    assert message == {
        "type": "chat",
        "from": "alice",
        "text": "Hello there",
        "context": "general",
    }


def test_messages_arrive_in_order(server, connect):
    alice, bob = connect("alice"), connect("bob")
    for i in range(20):
        alice.send({"type": "chat", "text": str(i)})
    assert [bob.recv_until("chat")["text"] for _ in range(20)] == [str(i) for i in range(20)]


# -------------------------------------------------- FR-006 join / leave notices
def test_others_are_told_when_someone_joins(server, connect):
    alice = connect("alice")
    connect("bob")
    notice = alice.recv_until("system")
    assert notice["event"] == "join"
    assert notice["text"] == "bob joined the chat"


def test_others_are_told_when_someone_leaves(server, connect):
    alice = connect("alice")
    bob = connect("bob")
    alice.recv_until("system")  # bob joined
    bob.close()
    notice = alice.recv_until("system")
    assert notice["event"] == "leave"
    assert notice["text"] == "bob left the chat"


def test_registration_reply_lists_online_users(server, connect):
    connect("alice")
    bob = connect()
    bob.send({"type": "register", "username": "bob"})
    assert bob.recv()["users"] == ["alice", "bob"]


# ------------------------------------------------------------- #10 config
def test_config_defaults(monkeypatch):
    monkeypatch.delenv("CHAT_HOST", raising=False)
    monkeypatch.delenv("CHAT_PORT", raising=False)
    args = config.parse_args("test", [])
    assert (args.host, args.port) == ("127.0.0.1", 5000)


def test_config_from_environment(monkeypatch):
    monkeypatch.setenv("CHAT_HOST", "0.0.0.0")
    monkeypatch.setenv("CHAT_PORT", "6000")
    args = config.parse_args("test", [])
    assert (args.host, args.port) == ("0.0.0.0", 6000)


def test_command_line_overrides_environment(monkeypatch):
    monkeypatch.setenv("CHAT_PORT", "6000")
    args = config.parse_args("test", ["--port", "7000"])
    assert args.port == 7000
