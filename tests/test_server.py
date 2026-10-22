"""Server tests for concurrent clients (FR-002)."""

import time


def test_many_clients_connect_at_once(server, connect):
    clients = [connect() for _ in range(5)]
    deadline = time.time() + 3
    while len(server.clients) < 5 and time.time() < deadline:
        time.sleep(0.05)
    assert len(server.clients) == 5
    assert all(c.sock.fileno() != -1 for c in clients)


def test_message_reaches_other_clients(server, connect):
    alice, bob, carol = connect("alice"), connect("bob"), connect("carol")
    alice.send({"type": "chat", "text": "hi all"})
    assert bob.recv_until("chat")["text"] == "hi all"
    assert carol.recv_until("chat")["text"] == "hi all"


def test_sender_does_not_get_own_message(server, connect):
    alice, bob = connect("alice"), connect("bob")
    alice.send({"type": "chat", "text": "hello"})
    assert bob.recv_until("chat")["text"] == "hello"
    alice.assert_silent()


def test_new_client_does_not_disturb_existing_session(server, connect):
    alice, bob = connect("alice"), connect("bob")
    connect("carol")  # a third client joins mid-conversation
    alice.send({"type": "chat", "text": "still here"})
    assert bob.recv_until("chat")["text"] == "still here"
