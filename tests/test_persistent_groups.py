"""FR-013 (#51): groups, their members and their admin survive a restart."""

import time

from chat.groups import GroupManager
from chat.server import ChatServer
from chat.storage import MessageStore

from conftest import WireClient


def reopen(path):
    """A fresh GroupManager reading the same database file."""
    return GroupManager(MessageStore(path))


def db(tmp_path):
    return str(tmp_path / "chat.db")


# ------------------------------------------------------------- storage
def test_group_state_round_trip():
    store = MessageStore()
    store.save_group_state("Squad", "alice", ["alice", "bob"])
    assert store.load_groups() == {"Squad": ("alice", ["alice", "bob"])}


def test_saving_again_replaces_the_old_state():
    store = MessageStore()
    store.save_group_state("Squad", "alice", ["alice", "bob", "carol"])
    store.save_group_state("Squad", "bob", ["bob", "carol"])
    assert store.load_groups() == {"Squad": ("bob", ["bob", "carol"])}


def test_delete_group():
    store = MessageStore()
    store.save_group_state("Squad", "alice", ["alice"])
    store.delete_group("Squad")
    assert store.load_groups() == {}


def test_members_keep_their_joining_order():
    store = MessageStore()
    store.save_group_state("Squad", "zoe", ["zoe", "adam", "mia"])
    assert store.load_groups()["Squad"][1] == ["zoe", "adam", "mia"]


# ------------------------------------------------- GroupManager + database
def test_created_group_is_restored(tmp_path):
    groups = reopen(db(tmp_path))
    groups.create("Squad", "alice")
    restored = reopen(db(tmp_path))
    assert restored.names() == ["Squad"]
    assert restored.admin("Squad") == "alice"
    assert restored.members("Squad") == ["alice"]


def test_joined_and_added_members_are_restored(tmp_path):
    groups = reopen(db(tmp_path))
    groups.create("Squad", "alice")
    groups.join("Squad", "bob")
    groups.add("Squad", "alice", "carol")
    assert reopen(db(tmp_path)).members("Squad") == ["alice", "bob", "carol"]


def test_leaving_is_saved(tmp_path):
    groups = reopen(db(tmp_path))
    groups.create("Squad", "alice")
    groups.join("Squad", "bob")
    groups.leave("Squad", "bob")
    assert reopen(db(tmp_path)).members("Squad") == ["alice"]


def test_new_admin_is_saved(tmp_path):
    groups = reopen(db(tmp_path))
    groups.create("Squad", "alice")
    groups.join("Squad", "bob")
    groups.leave("Squad", "alice")
    restored = reopen(db(tmp_path))
    assert restored.admin("Squad") == "bob"
    assert restored.members("Squad") == ["bob"]


def test_empty_group_is_deleted_from_the_database(tmp_path):
    groups = reopen(db(tmp_path))
    groups.create("Squad", "alice")
    groups.leave("Squad", "alice")
    assert reopen(db(tmp_path)).names() == []
    assert MessageStore(db(tmp_path)).load_groups() == {}


def test_rules_still_apply_after_a_restart(tmp_path):
    groups = reopen(db(tmp_path))
    groups.create("Squad", "alice")
    groups.join("Squad", "bob")
    restored = reopen(db(tmp_path))
    assert restored.is_member("Squad", "bob")
    assert not restored.is_member("Squad", "carol")
    restored.add("Squad", "alice", "carol")  # alice is still the admin


def test_without_a_database_nothing_is_saved():
    groups = GroupManager()
    groups.create("Squad", "alice")
    assert GroupManager().names() == []


# ---------------------------------------------------- real server restart
def start(path):
    return ChatServer(port=0, db_path=path).start()


def register(srv, name):
    client = WireClient(srv)
    client.send({"type": "register", "username": name})
    assert client.recv_until("registered")["username"] == name
    return client


def wait_until(check, timeout=3.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if check():
            return True
        time.sleep(0.02)
    return False


def test_group_survives_a_server_restart(tmp_path):
    path = db(tmp_path)
    srv = start(path)
    alice, bob = register(srv, "alice"), register(srv, "bob")
    alice.send({"type": "create_group", "group": "Squad"})
    alice.recv_until("group_update")
    bob.send({"type": "join_group", "group": "Squad"})
    bob.recv_until("group_update")
    srv.stop()
    alice.close()
    bob.close()

    srv = start(path)
    try:
        assert srv.groups.names() == ["Squad"]
        assert srv.groups.members("Squad") == ["alice", "bob"]
        assert srv.groups.admin("Squad") == "alice"

        # both reconnect and can talk in the group straight away
        alice, bob = register(srv, "alice"), register(srv, "bob")
        alice.send({"type": "group", "group": "Squad", "text": "still here?"})
        message = bob.recv_until("chat")
        assert message["group"] == "Squad" and message["text"] == "still here?"
    finally:
        srv.stop()


def test_admin_can_still_add_after_a_restart(tmp_path):
    path = db(tmp_path)
    srv = start(path)
    alice = register(srv, "alice")
    alice.send({"type": "create_group", "group": "Squad"})
    alice.recv_until("group_update")
    srv.stop()

    srv = start(path)
    try:
        alice, carol = register(srv, "alice"), register(srv, "carol")
        alice.send({"type": "add_member", "group": "Squad", "username": "carol"})
        assert carol.recv_until("group_update")["members"] == ["alice", "carol"]
    finally:
        srv.stop()


def test_user_who_quits_still_leaves_their_groups(tmp_path):
    """Sprint 2 rule kept: only a server restart keeps memberships."""
    path = db(tmp_path)
    srv = start(path)
    try:
        alice, bob = register(srv, "alice"), register(srv, "bob")
        alice.send({"type": "create_group", "group": "Squad"})
        alice.recv_until("group_update")
        bob.send({"type": "join_group", "group": "Squad"})
        bob.recv_until("group_update")
        bob.send({"type": "quit"})
        assert wait_until(lambda: srv.groups.members("Squad") == ["alice"])
    finally:
        srv.stop()
    assert MessageStore(path).load_groups() == {"Squad": ("alice", ["alice"])}
