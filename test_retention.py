"""NFR-007 (#54): keep only the most recent messages of each chat."""

import argparse
import time

import pytest

from chat import config
from chat.server import ChatServer
from chat.storage import MessageStore

from conftest import WireClient


def chat(i, sender="alice"):
    return {"id": i, "time": f"t{i}", "from": sender, "text": f"m{i}"}


def texts(messages):
    return [m["text"] for m in messages]


def test_everyone_chat_keeps_the_newest():
    store = MessageStore(keep=5)
    for i in range(12):
        store.save_chat(chat(i))
    assert texts(store.recent_chat(limit=100)) == [f"m{i}" for i in range(7, 12)]
    assert store.count() == 5


def test_nothing_is_removed_below_the_limit():
    store = MessageStore(keep=5)
    for i in range(3):
        store.save_chat(chat(i))
    assert store.count() == 3


def test_each_private_pair_has_its_own_limit():
    store = MessageStore(keep=3)
    for i in range(6):  # both directions count as one conversation
        sender, to = ("alice", "bob") if i % 2 == 0 else ("bob", "alice")
        store.save_private({**chat(i, sender), "to": to})
    store.save_private({**chat(99), "to": "carol"})
    assert texts(store.private_between("alice", "bob", limit=100)) == ["m3", "m4", "m5"]
    assert texts(store.private_between("alice", "carol", limit=100)) == ["m99"]


def test_each_group_has_its_own_limit():
    store = MessageStore(keep=2)
    for i in range(5):
        store.save_group({**chat(i), "group": "Squad"})
    store.save_group({**chat(50), "group": "Team"})
    assert texts(store.group_messages("Squad", limit=100)) == ["m3", "m4"]
    assert texts(store.group_messages("Team", limit=100)) == ["m50"]


def test_chats_do_not_trim_each_other():
    store = MessageStore(keep=2)
    store.save_private({**chat(1), "to": "bob"})
    store.save_group({**chat(2), "group": "Squad"})
    for i in range(10, 15):
        store.save_chat(chat(i))
    assert texts(store.private_between("alice", "bob")) == ["m1"]
    assert texts(store.group_messages("Squad")) == ["m2"]
    assert texts(store.recent_chat()) == ["m13", "m14"]


def test_zero_keeps_everything():
    store = MessageStore(keep=0)
    for i in range(50):
        store.save_chat(chat(i))
    assert store.count() == 50


def test_limit_applies_to_an_existing_file(tmp_path):
    path = str(tmp_path / "chat.db")
    big = MessageStore(path)
    for i in range(10):
        big.save_chat(chat(i))
    big.close()
    small = MessageStore(path, keep=4)
    small.save_chat(chat(10))
    assert texts(small.recent_chat(limit=100)) == ["m7", "m8", "m9", "m10"]


# ----------------------------------------------------------------- setting
def test_default_limit_is_500(monkeypatch):
    monkeypatch.delenv("CHAT_KEEP", raising=False)
    assert config.parse_args("x", []).keep == 500


def test_limit_from_environment(monkeypatch):
    monkeypatch.setenv("CHAT_KEEP", "50")
    assert config.parse_args("x", []).keep == 50


def test_flag_beats_environment(monkeypatch):
    monkeypatch.setenv("CHAT_KEEP", "50")
    assert config.parse_args("x", ["--keep", "7"]).keep == 7


@pytest.mark.parametrize("bad", ["-1", "lots", "2.5"])
def test_bad_limit_is_rejected(bad):
    with pytest.raises(argparse.ArgumentTypeError):
        config.keep_count(bad)


def test_bad_flag_stops_the_server():
    with pytest.raises(SystemExit):
        config.parse_args("x", ["--keep", "-3"])


def test_server_passes_the_limit_to_the_store():
    srv = ChatServer(port=0, keep=25)
    assert srv.store.keep == 25
    assert ChatServer(port=0).store.keep == 0  # tests keep everything


def test_server_trims_while_running(tmp_path):
    srv = ChatServer(port=0, db_path=str(tmp_path / "chat.db"), keep=3).start()
    try:
        alice = WireClient(srv)
        alice.send({"type": "register", "username": "alice"})
        alice.recv_until("registered")
        for i in range(6):
            alice.send({"type": "chat", "text": f"x{i}"})
        deadline = time.time() + 3
        while texts(srv.store.recent_chat()) != ["x3", "x4", "x5"]:
            assert time.time() < deadline, texts(srv.store.recent_chat())
            time.sleep(0.02)
        alice.close()
    finally:
        srv.stop()
