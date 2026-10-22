"""Disconnects (FR-007), private messages (FR-005), thread safety (NFR-002),
error isolation (FR-008) and registration gating (NFR-005)."""

import socket
import struct
import threading
import time

from chat import protocol
from chat.client import parse_command


def wait_until(condition, timeout=3.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if condition():
            return True
        time.sleep(0.02)
    return False


def hard_reset(client):
    """Close with a TCP RST, like a crashed program or dropped network."""
    client.sock.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, struct.pack("ii", 1, 0))
    client.sock.close()


# ---------------------------------------------------------- #4 disconnections
def test_quit_removes_user_and_notifies_others(server, connect):
    alice, bob = connect("alice"), connect("bob")
    alice.recv_until("system")  # bob joined
    bob.send({"type": "quit"})
    notice = alice.recv_until("system")
    assert notice["text"] == "bob left the chat"
    assert "bob" not in server.users


def test_crashed_client_is_cleaned_up(server, connect):
    alice, bob = connect("alice"), connect("bob")
    alice.recv_until("system")
    hard_reset(bob)
    assert alice.recv_until("system")["text"] == "bob left the chat"
    assert wait_until(lambda: len(server.clients) == 1)


def test_server_keeps_working_after_a_crash(server, connect):
    alice, bob = connect("alice"), connect("bob")
    hard_reset(connect("carol"))
    alice.send({"type": "chat", "text": "anyone?"})
    assert bob.recv_until("chat")["text"] == "anyone?"


def test_user_can_reconnect_after_crash(server, connect):
    hard_reset(connect("alice"))
    assert wait_until(lambda: "alice" not in server.users)
    connect("alice")  # ST_14: same username works again


def test_keepalive_is_enabled_on_client_sockets(server, connect):
    connect("alice")
    assert wait_until(lambda: server.clients)
    conn = server.clients[0].conn
    assert conn.getsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE) == 1


# ------------------------------------------------------ #6 private messages
def test_private_message_reaches_only_the_recipient(server, connect):
    alice, bob, carol = connect("alice"), connect("bob"), connect("carol")
    alice.send({"type": "private", "to": "bob", "text": "secret"})
    assert bob.recv_until("private") == {
        "type": "private", "from": "alice", "to": "bob", "text": "secret",
    }
    carol.assert_silent()


def test_sender_sees_confirmation(server, connect):
    alice = connect("alice")
    connect("bob")
    alice.send({"type": "private", "to": "bob", "text": "secret"})
    assert alice.recv_until("private_sent") == {
        "type": "private_sent", "to": "bob", "text": "secret",
    }


def test_private_message_to_unknown_user(server, connect):
    alice = connect("alice")
    alice.send({"type": "private", "to": "ghost", "text": "hello?"})
    reply = alice.recv_until("error")
    assert reply["code"] == "USER_NOT_FOUND"
    assert reply["message"] == "User not found/offline"


def test_private_message_to_user_who_left(server, connect):
    alice, bob = connect("alice"), connect("bob")
    bob.send({"type": "quit"})
    assert wait_until(lambda: "bob" not in server.users)
    alice.send({"type": "private", "to": "bob", "text": "hello?"})
    assert alice.recv_until("error")["code"] == "USER_NOT_FOUND"


# ----------------------------------------------------------- #9 thread safety
def test_only_one_of_many_simultaneous_registrations_wins(server, connect):
    clients = [connect() for _ in range(20)]
    start = threading.Barrier(len(clients))
    replies = []

    def register(client):
        start.wait()
        client.send({"type": "register", "username": "samename"})
        replies.append(client.recv()["type"])

    threads = [threading.Thread(target=register, args=(c,)) for c in clients]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert replies.count("registered") == 1
    assert replies.count("error") == 19


def test_concurrent_senders_never_corrupt_messages(server, connect):
    receiver = connect("receiver")
    senders = [connect(f"sender{i}") for i in range(5)]
    receiver.sock.settimeout(5)

    def flood(client, n):
        for j in range(50):
            client.send({"type": "chat", "text": f"{n}-{j}"})

    threads = [threading.Thread(target=flood, args=(s, i)) for i, s in enumerate(senders)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    texts = [receiver.recv_until("chat")["text"] for _ in range(250)]
    assert sorted(texts) == sorted(f"{i}-{j}" for i in range(5) for j in range(50))


# ----------------------------------------------------------- #17 bad input
def test_invalid_json_gets_error_and_session_continues(server, connect):
    alice, bob = connect("alice"), connect("bob")
    body = b"{this is not json"
    alice.sock.sendall(protocol.HEADER.pack(len(body)) + body)
    assert alice.recv_until("error")["code"] == "MALFORMED"
    alice.send({"type": "chat", "text": "still works"})
    assert bob.recv_until("chat")["text"] == "still works"


def test_oversized_frame_disconnects_only_that_client(server, connect):
    alice, bob, mallory = connect("alice"), connect("bob"), connect("mallory")
    mallory.sock.sendall(protocol.HEADER.pack(protocol.MAX_FRAME_BYTES + 1))
    assert mallory.recv_until("error")["code"] == "MALFORMED"
    assert wait_until(lambda: "mallory" not in server.users)
    alice.send({"type": "chat", "text": "unaffected"})
    assert bob.recv_until("chat")["text"] == "unaffected"


def test_unknown_message_type(server, connect):
    alice = connect("alice")
    alice.send({"type": "teleport"})
    assert alice.recv_until("error")["code"] == "UNKNOWN_TYPE"


def test_empty_message_is_rejected(server, connect):
    alice, bob = connect("alice"), connect("bob")
    alice.send({"type": "chat", "text": "   "})
    assert alice.recv_until("error")["code"] == "EMPTY_MESSAGE"
    bob.assert_silent()


def test_wrong_field_types_do_not_crash_session(server, connect):
    alice, bob = connect("alice"), connect("bob")
    alice.send({"type": "chat", "text": 12345})
    assert alice.recv_until("error")["code"] == "EMPTY_MESSAGE"
    alice.send({"type": "private", "to": ["bob"], "text": "hi"})
    assert alice.recv_until("error")["code"] == "USER_NOT_FOUND"
    alice.send({"type": "chat", "text": "fine"})
    assert bob.recv_until("chat")["text"] == "fine"


# ------------------------------------------------- #21 unregistered sockets
def test_unregistered_socket_cannot_chat(server, connect):
    bob = connect("bob")
    stranger = connect()
    stranger.send({"type": "chat", "text": "injected"})
    assert stranger.recv()["code"] == "NOT_REGISTERED"
    bob.assert_silent()


def test_unregistered_socket_cannot_send_private(server, connect):
    bob = connect("bob")
    stranger = connect()
    stranger.send({"type": "private", "to": "bob", "text": "injected"})
    assert stranger.recv()["code"] == "NOT_REGISTERED"
    bob.assert_silent()


def test_cannot_register_twice(server, connect):
    alice = connect("alice")
    alice.send({"type": "register", "username": "alice2"})
    assert alice.recv()["code"] == "ALREADY_REGISTERED"


# ----------------------------------------------------- client command parsing
def test_parse_plain_text():
    assert parse_command("hello") == ({"type": "chat", "text": "hello"}, None)


def test_parse_private_message():
    assert parse_command("/msg bob hi there") == (
        {"type": "private", "to": "bob", "text": "hi there"}, None,
    )


def test_parse_private_message_without_text():
    message, local = parse_command("/msg bob")
    assert message is None and "Usage" in local


def test_parse_quit_and_unknown():
    assert parse_command("/quit") == ({"type": "quit"}, None)
    assert parse_command("/dance")[0] is None
