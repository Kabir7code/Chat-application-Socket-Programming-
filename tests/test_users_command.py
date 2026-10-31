"""FR-006 (#7): /users lists everyone who is online."""

from chat.client import HELP, format_message, parse_command


def online(client):
    client.send({"type": "list_users"})
    return client.recv_until("users")["users"]


# ------------------------------------------------------------- client side
def test_parse_users_command():
    assert parse_command("/users") == ({"type": "list_users"}, None)


def test_users_is_in_help():
    assert "/users" in HELP


def test_format_users_reply():
    line = format_message({"type": "users", "users": ["alice", "bob", "carol"]})
    assert line == "* Online (3): alice, bob, carol"


# ------------------------------------------------------------- server side
def test_lists_everyone_online_sorted(server, connect):
    connect("carol")
    connect("alice")
    bob = connect("bob")
    assert online(bob) == ["alice", "bob", "carol"]


def test_only_user_sees_themselves(server, connect):
    alice = connect("alice")
    assert online(alice) == ["alice"]


def test_user_who_left_is_no_longer_listed(server, connect):
    alice, bob = connect("alice"), connect("bob")
    bob.send({"type": "quit"})
    alice.recv_until("system")  # bob joined
    alice.recv_until("system")  # bob left
    assert online(alice) == ["alice"]


def test_new_user_appears_in_list(server, connect):
    alice = connect("alice")
    assert online(alice) == ["alice"]
    connect("dave")
    assert online(alice) == ["alice", "dave"]


def test_connected_but_unregistered_users_are_not_listed(server, connect):
    alice = connect("alice")
    connect()  # connected, never chose a name
    assert online(alice) == ["alice"]


def test_unregistered_socket_cannot_list_users(server, connect):
    stranger = connect()
    stranger.send({"type": "list_users"})
    reply = stranger.recv()
    assert reply["type"] == "error" and reply["code"] == "NOT_REGISTERED"


def test_reply_goes_only_to_the_asker(server, connect):
    alice, bob = connect("alice"), connect("bob")
    alice.recv_until("system")  # bob joined
    alice.send({"type": "list_users"})
    alice.recv_until("users")
    bob.assert_silent()
