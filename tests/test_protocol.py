"""Message framing tests (NFR-003)."""

import socket
import threading

import pytest

from chat import protocol


@pytest.fixture
def pair():
    a, b = socket.socketpair()
    a.settimeout(3)
    b.settimeout(3)
    yield a, b
    a.close()
    b.close()


def test_round_trip(pair):
    a, b = pair
    protocol.send_message(a, {"type": "chat", "text": "hello"})
    assert protocol.recv_message(b) == {"type": "chat", "text": "hello"}


def test_long_message_arrives_whole(pair):
    a, b = pair
    text = "x" * 5000
    # send from a thread so a full socket buffer cannot block the test
    threading.Thread(
        target=protocol.send_message, args=(a, {"type": "chat", "text": text})
    ).start()
    assert protocol.recv_message(b)["text"] == text


def test_rapid_messages_stay_separate(pair):
    a, b = pair
    for i in range(10):
        protocol.send_message(a, {"type": "chat", "text": f"msg {i}"})
    received = [protocol.recv_message(b)["text"] for _ in range(10)]
    assert received == [f"msg {i}" for i in range(10)]


def test_split_frame_is_reassembled(pair):
    a, b = pair
    frame = protocol.encode({"type": "chat", "text": "split"})
    a.sendall(frame[:3])  # header cut in half
    a.sendall(frame[3:])
    assert protocol.recv_message(b)["text"] == "split"


def test_unicode(pair):
    a, b = pair
    protocol.send_message(a, {"type": "chat", "text": "नमस्ते 👋"})
    assert protocol.recv_message(b)["text"] == "नमस्ते 👋"


def test_closed_connection_returns_none(pair):
    a, b = pair
    a.close()
    assert protocol.recv_message(b) is None


def test_invalid_json_raises():
    with pytest.raises(protocol.ProtocolError):
        protocol.decode(b"not json")


def test_missing_type_raises():
    with pytest.raises(protocol.ProtocolError):
        protocol.decode(b'{"text": "hi"}')


def test_oversized_frame_is_rejected(pair):
    a, b = pair
    a.sendall(protocol.HEADER.pack(protocol.MAX_FRAME_BYTES + 1))
    with pytest.raises(protocol.ProtocolError):
        protocol.recv_message(b)


def test_make_chat_message():
    message = protocol.make_chat_message("Hello there", "userA")
    assert isinstance(message.pop("id"), int)
    assert message == {"type": "chat", "from": "userA", "text": "Hello there"}


def test_message_ids_are_unique_and_increasing():
    ids = [protocol.make_chat_message("x", "a")["id"] for _ in range(5)]
    assert ids == sorted(set(ids))


def test_message_ids_are_unique_across_threads():
    ids = []

    def make_many():
        for _ in range(500):
            ids.append(protocol.new_message_id())

    threads = [threading.Thread(target=make_many) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(set(ids)) == 2000
