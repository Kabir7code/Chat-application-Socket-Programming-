"""FR-009 (#13): every chat, group and private message carries the time the
server handled it, and the client shows it as [HH:MM] in local time."""

from datetime import datetime, timedelta, timezone

from chat import protocol
from chat.client import format_message, time_prefix


def parse(stamp):
    return datetime.fromisoformat(stamp)


def is_recent(stamp):
    sent = parse(stamp)
    return sent.tzinfo is not None and abs(datetime.now(timezone.utc) - sent) < timedelta(seconds=5)


# ------------------------------------------------------------- unit tests
def test_timestamp_is_utc_iso_8601():
    stamp = protocol.timestamp()
    assert parse(stamp).utcoffset() == timedelta(0)
    assert is_recent(stamp)


def test_chat_message_has_a_time():
    assert is_recent(protocol.make_chat_message("hi", "alice")["time"])


def test_client_shows_local_hours_and_minutes():
    stamp = "2026-10-30T09:05:00+00:00"
    local = parse(stamp).astimezone().strftime("%H:%M")
    line = format_message({"type": "chat", "from": "alice", "text": "hi", "time": stamp})
    assert line == f"[{local}] alice: hi"


def test_group_and_private_lines_get_the_time_first():
    stamp = "2026-10-30T09:05:00+00:00"
    prefix = time_prefix({"time": stamp})
    group = {"type": "chat", "context": "group", "group": "Squad", "from": "alice",
             "text": "hi", "time": stamp}
    private = {"type": "private", "from": "bob", "text": "psst", "time": stamp}
    sent = {"type": "private_sent", "to": "bob", "text": "psst", "time": stamp}
    assert format_message(group) == f"{prefix}[Squad] alice: hi"
    assert format_message(private) == f"{prefix}[private] bob: psst"
    assert format_message(sent) == f"{prefix}[private to bob] psst"


def test_missing_or_bad_time_shows_no_prefix():
    assert time_prefix({}) == ""
    assert time_prefix({"time": "not a time"}) == ""
    assert time_prefix({"time": None}) == ""


# ------------------------------------------------------ integration tests
def test_broadcast_arrives_with_a_time(server, connect):
    alice, bob = connect("alice"), connect("bob")
    alice.send({"type": "chat", "text": "hello"})
    assert is_recent(bob.recv_until("chat")["time"])


def test_private_message_and_confirmation_share_a_time(server, connect):
    alice, bob = connect("alice"), connect("bob")
    alice.send({"type": "private", "to": "bob", "text": "hey"})
    delivered = bob.recv_until("private")
    confirmation = alice.recv_until("private_sent")
    assert is_recent(delivered["time"])
    assert delivered["time"] == confirmation["time"]


def test_group_message_arrives_with_a_time(server, connect):
    alice, bob = connect("alice"), connect("bob")
    alice.send({"type": "create_group", "group": "Squad"})
    alice.recv_until("group_update")
    bob.send({"type": "join_group", "group": "Squad"})
    bob.recv_until("group_update")
    alice.send({"type": "group", "group": "Squad", "text": "hi"})
    assert is_recent(bob.recv_until("chat")["time"])


def test_times_do_not_go_backwards(server, connect):
    alice, bob = connect("alice"), connect("bob")
    for i in range(20):
        alice.send({"type": "chat", "text": str(i)})
    times = [parse(bob.recv_until("chat")["time"]) for _ in range(20)]
    assert times == sorted(times)
