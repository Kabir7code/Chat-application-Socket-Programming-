"""NFR-001 (#19): a message reaches the other users within 1 second."""

import time

MAX_DELAY = 1.0  # seconds


def test_broadcast_arrives_within_one_second(server, connect):
    alice, bob = connect("alice"), connect("bob")
    alice.recv_until("system")  # bob joined

    start = time.perf_counter()
    alice.send({"type": "chat", "text": "ping"})
    message = bob.recv_until("chat")
    elapsed = time.perf_counter() - start

    assert message["text"] == "ping"
    assert elapsed < MAX_DELAY, f"took {elapsed:.3f}s"


def test_private_message_arrives_within_one_second(server, connect):
    alice, bob = connect("alice"), connect("bob")

    start = time.perf_counter()
    alice.send({"type": "private", "to": "bob", "text": "just for you"})
    message = bob.recv_until("private")
    elapsed = time.perf_counter() - start

    assert message["text"] == "just for you"
    assert elapsed < MAX_DELAY, f"took {elapsed:.3f}s"


def test_every_message_in_a_burst_arrives_within_one_second(server, connect):
    alice, bob = connect("alice"), connect("bob")
    alice.recv_until("system")

    for i in range(50):
        start = time.perf_counter()
        alice.send({"type": "chat", "text": f"msg {i}"})
        message = bob.recv_until("chat")
        elapsed = time.perf_counter() - start
        assert message["text"] == f"msg {i}"
        assert elapsed < MAX_DELAY, f"message {i} took {elapsed:.3f}s"
