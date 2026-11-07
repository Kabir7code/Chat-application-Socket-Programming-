"""NFR-004 (#12): extra automated tests for the Sprint 2 features that had
few or no tests: message IDs, client display and commands, TLS settings,
and the session registry."""

import threading

import pytest

from chat import config, protocol
from chat.client import HELP, format_message, parse_command
from chat.registry import SessionRegistry


# ------------------------------------------------------- message IDs (#30)
def test_group_messages_get_an_id(server, connect):
    alice, bob = connect("alice"), connect("bob")
    alice.send({"type": "create_group", "group": "Squad"})
    alice.recv_until("group_update")
    bob.send({"type": "join_group", "group": "Squad"})
    bob.recv_until("group_update")

    alice.send({"type": "group", "group": "Squad", "text": "hi"})
    message = bob.recv_until("chat")
    assert isinstance(message["id"], int)


def test_ids_increase_across_chat_private_and_group(server, connect):
    alice, bob = connect("alice"), connect("bob")
    alice.send({"type": "create_group", "group": "Squad"})
    alice.recv_until("group_update")
    bob.send({"type": "join_group", "group": "Squad"})
    bob.recv_until("group_update")

    alice.send({"type": "chat", "text": "one"})
    first = bob.recv_until("chat")["id"]
    alice.send({"type": "private", "to": "bob", "text": "two"})
    second = bob.recv_until("private")["id"]
    alice.send({"type": "group", "group": "Squad", "text": "three"})
    third = bob.recv_until("chat")["id"]
    assert first < second < third


def test_private_confirmation_has_same_id_as_delivered_message(server, connect):
    alice, bob = connect("alice"), connect("bob")
    alice.send({"type": "private", "to": "bob", "text": "hey"})
    delivered = bob.recv_until("private")
    confirmation = alice.recv_until("private_sent")
    assert delivered["id"] == confirmation["id"]


def test_new_message_id_is_unique_under_threads():
    ids = []
    lock = threading.Lock()

    def grab():
        mine = [protocol.new_message_id() for _ in range(500)]
        with lock:
            ids.extend(mine)

    threads = [threading.Thread(target=grab) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(ids) == len(set(ids)) == 4000


# ----------------------------------------------------- client display
@pytest.mark.parametrize("message, expected", [
    ({"type": "chat", "from": "alice", "text": "hi"}, "alice: hi"),
    ({"type": "chat", "context": "group", "group": "Squad", "from": "alice", "text": "hi"},
     "[Squad] alice: hi"),
    ({"type": "private", "from": "bob", "text": "psst"}, "[private] bob: psst"),
    ({"type": "private_sent", "to": "bob", "text": "psst"}, "[private to bob] psst"),
    ({"type": "system", "text": "bob joined the chat"}, "* bob joined the chat"),
    ({"type": "error", "message": "Username already taken."}, "! Username already taken."),
    ({"type": "group_update", "group": "Squad", "text": "bob joined Squad",
      "members": ["alice", "bob"]}, "* [Squad] bob joined Squad (members: alice, bob)"),
    ({"type": "group_update", "group": "Squad", "text": "You left Squad", "members": []},
     "* [Squad] You left Squad (members: none)"),
])
def test_format_message(message, expected):
    assert format_message(message) == expected


# ----------------------------------------------------- client commands
def test_help_lists_every_command():
    message, text = parse_command("/help")
    assert message is None and text == HELP
    for command in ("/msg", "/create", "/join", "/add", "/leave", "/g", "/quit"):
        assert command in HELP


def test_group_message_keeps_spaces_in_text():
    message, _ = parse_command("/g Squad hello   there  everyone")
    assert message == {"type": "group", "group": "Squad", "text": "hello   there  everyone"}


def test_add_needs_group_and_user():
    message, text = parse_command("/add Squad")
    assert message is None and text == "Usage: /add <group> <user>"


def test_slash_alone_is_unknown():
    message, text = parse_command("/")
    assert message is None and "Unknown command" in text


# ----------------------------------------------------- TLS settings (#22)
def test_tls_is_on_by_default(monkeypatch):
    monkeypatch.delenv("CHAT_NO_TLS", raising=False)
    assert config.parse_args("x", []).no_tls is False


def test_no_tls_from_environment(monkeypatch):
    monkeypatch.setenv("CHAT_NO_TLS", "1")
    args = config.parse_args("x", [])
    assert args.no_tls is True
    assert config.server_tls(args) is None
    assert config.client_tls(args) is None


def test_cert_paths_can_be_overridden(monkeypatch):
    monkeypatch.setenv("CHAT_CERT", "env.crt")
    args = config.parse_args("x", ["--key", "my.key", "--cafile", "ca.crt"])
    assert (args.cert, args.key, args.cafile) == ("env.crt", "my.key", "ca.crt")


def test_client_without_cafile_gives_clear_message(tmp_path):
    args = config.parse_args("x", ["--cafile", str(tmp_path / "missing.crt")])
    with pytest.raises(SystemExit, match="Copy server.crt"):
        config.client_tls(args)


# ----------------------------------------------------- session registry
class FakeSession:
    def __init__(self):
        self.username = None


def test_registry_register_and_disconnect():
    registry, session = SessionRegistry(), FakeSession()
    registry.connect(session)
    assert registry.register(session, "alice")
    assert registry.get("alice") is session
    assert registry.usernames() == ["alice"]
    assert registry.disconnect(session) is True
    assert registry.get("alice") is None


def test_registry_disconnect_of_unregistered_session():
    registry, session = SessionRegistry(), FakeSession()
    registry.connect(session)
    assert registry.disconnect(session) is False
    assert registry.connected() == []


def test_registry_usernames_are_sorted():
    registry = SessionRegistry()
    for name in ("carol", "alice", "bob"):
        registry.register(FakeSession(), name)
    assert registry.usernames() == ["alice", "bob", "carol"]
