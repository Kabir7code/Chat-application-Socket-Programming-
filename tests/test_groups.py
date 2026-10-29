"""Group chat management (FR-004). Test case IDs refer to the Test Cases document."""

import threading
import time

import pytest

from chat.client import parse_command
from chat.groups import GroupError, GroupManager


def wait_until(condition, timeout=3.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if condition():
            return True
        time.sleep(0.02)
    return False


def group_chats(client):
    """Group chat messages that arrive within a short wait."""
    return [m for m in client_messages(client) if m.get("context") == "group"]


def make_group(server, owner, name, *joiners):
    """Create a group and have others join it, waiting for the server each time.
    (Requests from different connections are handled on different threads, so
    without waiting a join could reach the server before the create.)"""
    owner.send({"type": "create_group", "group": name})
    assert wait_until(lambda: name in server.groups.names())
    for client in joiners:
        client.send({"type": "join_group", "group": name})
    assert wait_until(lambda: len(server.groups.members(name)) == 1 + len(joiners))


def event(client, name):
    """Next group_update with the given event, skipping earlier ones."""
    while True:
        message = client.recv_until("group_update")
        if message is None or message["event"] == name:
            return message


def client_messages(client, wait=0.4):
    import socket
    got = []
    client.sock.settimeout(wait)
    try:
        while True:
            m = client.recv()
            if m is None:
                break
            got.append(m)
    except socket.timeout:
        pass
    client.sock.settimeout(3.0)
    return got


# ------------------------------------------------------------ GroupManager
def test_create_sets_owner_and_members():  # UT_10
    groups = GroupManager()
    assert groups.create("ProjectTeam", "userA") == ["userA"]
    assert groups.admin("ProjectTeam") == "userA"
    assert groups.members("ProjectTeam") == ["userA"]


def test_duplicate_group_name_rejected():  # UT_11
    groups = GroupManager()
    groups.create("ProjectTeam", "userA")
    with pytest.raises(GroupError) as exc:
        groups.create("ProjectTeam", "userB")
    assert exc.value.code == "GROUP_EXISTS"
    assert exc.value.message == "Group name already exists."


def test_membership_check():  # UT_12
    groups = GroupManager()
    groups.create("ProjectTeam", "userA")
    groups.join("ProjectTeam", "userB")
    assert groups.is_member("ProjectTeam", "userB")
    assert not groups.is_member("ProjectTeam", "userC")


def test_member_list_add_and_remove():  # UT_18
    groups = GroupManager()
    groups.create("Squad", "userA")
    groups.join("Squad", "userB")
    groups.leave("Squad", "userA")
    assert groups.members("Squad") == ["userB"]


def test_invalid_group_names_rejected():
    groups = GroupManager()
    for bad in ("", "   ", "has space", "x" * 31):
        with pytest.raises(GroupError) as exc:
            groups.create(bad, "userA")
        assert exc.value.code == "INVALID_GROUP_NAME"


def test_only_admin_can_add():
    groups = GroupManager()
    groups.create("Squad", "userA")
    groups.join("Squad", "userB")
    with pytest.raises(GroupError) as exc:
        groups.add("Squad", "userB", "userC")
    assert exc.value.code == "NOT_GROUP_ADMIN"
    assert groups.add("Squad", "userA", "userC") == ["userA", "userB", "userC"]


def test_admin_passes_on_and_empty_group_is_deleted():
    groups = GroupManager()
    groups.create("Squad", "userA")
    groups.join("Squad", "userB")
    groups.leave("Squad", "userA")
    assert groups.admin("Squad") == "userB"
    groups.leave("Squad", "userB")
    assert groups.names() == []


def test_remove_user_takes_them_out_of_every_group():  # UT_21
    groups = GroupManager()
    groups.create("Squad", "userA")
    groups.create("StudyGroup", "userB")
    groups.join("Squad", "userC")
    groups.join("StudyGroup", "userA")
    assert groups.remove_user("userA") == {"Squad": ["userC"], "StudyGroup": ["userB"]}
    assert groups.groups_of("userA") == []


def test_concurrent_creates_of_same_name():
    groups = GroupManager()
    start = threading.Barrier(20)
    wins = []

    def attempt(n):
        start.wait()
        try:
            groups.create("Race", f"user{n}")
            wins.append(n)
        except GroupError:
            pass

    threads = [threading.Thread(target=attempt, args=(n,)) for n in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(wins) == 1


# ----------------------------------------------------------- over the network
def test_create_group(server, connect):  # IT_10
    a = connect("A")
    a.send({"type": "create_group", "group": "StudyGroup"})
    update = event(a, "created")
    assert update["members"] == ["A"]
    assert server.groups.names() == ["StudyGroup"]
    assert server.groups.admin("StudyGroup") == "A"


def test_join_group(server, connect):  # IT_11
    a, b = connect("A"), connect("B")
    make_group(server, a, "StudyGroup")
    b.send({"type": "join_group", "group": "StudyGroup"})
    assert event(b, "joined")["members"] == ["A", "B"]
    b.send({"type": "group", "group": "StudyGroup", "text": "hi"})
    assert a.recv_until("chat")["text"] == "hi"


def test_group_message_reaches_only_members(server, connect):  # IT_12
    a, b, c = connect("A"), connect("B"), connect("C")
    make_group(server, a, "StudyGroup", b)
    a.send({"type": "group", "group": "StudyGroup", "text": "Meeting at 5pm"})
    message = b.recv_until("chat")
    assert (message["context"], message["group"], message["from"], message["text"]) == (
        "group", "StudyGroup", "A", "Meeting at 5pm")
    assert group_chats(c) == []


def test_member_who_leaves_gets_nothing_more(server, connect):  # IT_13
    a, b = connect("A"), connect("B")
    make_group(server, a, "StudyGroup", b)
    b.send({"type": "leave_group", "group": "StudyGroup"})
    assert event(b, "left")["text"] == "You left StudyGroup"
    a.send({"type": "group", "group": "StudyGroup", "text": "anyone still here?"})
    assert group_chats(b) == []


def test_joining_twice_is_harmless(server, connect):  # IT_14
    a = connect("A")
    make_group(server, a, "StudyGroup")
    a.send({"type": "join_group", "group": "StudyGroup"})
    assert a.recv_until("error")["code"] == "ALREADY_MEMBER"
    assert server.groups.members("StudyGroup") == ["A"]


def test_full_group_lifecycle(server, connect):  # ST_07
    a, b, c = connect("A"), connect("B"), connect("C")
    make_group(server, a, "Squad", b, c)
    b.send({"type": "group", "group": "Squad", "text": "step 3"})
    assert a.recv_until("chat")["text"] == "step 3"
    assert c.recv_until("chat")["text"] == "step 3"
    c.send({"type": "leave_group", "group": "Squad"})
    assert wait_until(lambda: server.groups.members("Squad") == ["A", "B"])
    a.send({"type": "group", "group": "Squad", "text": "step 5"})
    assert b.recv_until("chat")["text"] == "step 5"
    assert group_chats(c) == []


def test_user_in_two_groups_gets_each_message_under_the_right_group(server, connect):  # ST_08
    a, b, c = connect("A"), connect("B"), connect("C")
    make_group(server, b, "Squad", a)
    make_group(server, c, "StudyGroup", a)
    b.send({"type": "group", "group": "Squad", "text": "from squad"})
    c.send({"type": "group", "group": "StudyGroup", "text": "from study"})
    got = {(m["group"], m["text"]) for m in group_chats(a)}
    assert got == {("Squad", "from squad"), ("StudyGroup", "from study")}


def test_private_message_not_visible_to_group(server, connect):  # IT_17
    a, b, c = connect("A"), connect("B"), connect("C")
    make_group(server, a, "Squad", b, c)
    client_messages(c)  # clear join notices
    a.send({"type": "private", "to": "B", "text": "hey privately"})
    a.send({"type": "group", "group": "Squad", "text": "hey team"})
    assert b.recv_until("private")["text"] == "hey privately"
    got_c = client_messages(c)
    assert [m["text"] for m in got_c if m["type"] == "chat"] == ["hey team"]
    assert not any(m["type"] == "private" for m in got_c)


def test_private_message_alongside_group_traffic(server, connect):  # ST_10
    a, b, c = connect("A"), connect("B"), connect("C")
    make_group(server, a, "Squad", c)
    for i in range(5):
        c.send({"type": "group", "group": "Squad", "text": f"group {i}"})
    a.send({"type": "private", "to": "B", "text": "just you"})
    assert b.recv_until("private")["text"] == "just you"
    got_a = [m["text"] for m in client_messages(a) if m.get("context") == "group"]
    assert got_a == [f"group {i}" for i in range(5)]


def test_members_see_updated_list_when_someone_joins(server, connect):  # IT_20
    a, b = connect("A"), connect("B")
    make_group(server, a, "Squad")
    b.send({"type": "join_group", "group": "Squad"})
    assert event(a, "joined")["members"] == ["A", "B"]
    assert event(b, "joined")["members"] == ["A", "B"]


def test_leaving_one_group_keeps_the_other(server, connect):  # IT_23
    a, b = connect("A"), connect("B")
    make_group(server, a, "Squad")
    make_group(server, b, "StudyGroup", a)
    a.send({"type": "leave_group", "group": "Squad"})
    assert wait_until(lambda: server.groups.groups_of("A") == ["StudyGroup"])
    assert "A" in server.users
    b.send({"type": "group", "group": "StudyGroup", "text": "still here?"})
    assert a.recv_until("chat")["text"] == "still here?"


def test_disconnect_removes_user_from_groups(server, connect):  # UT_21 / FR-007
    a, b = connect("A"), connect("B")
    make_group(server, a, "Squad", b)
    b.close()
    update = event(a, "left")
    assert update["username"] == "B" and update["members"] == ["A"]


def test_admin_adds_member(server, connect):  # UC-06
    a, b = connect("A"), connect("B")
    make_group(server, a, "Squad")
    a.send({"type": "add_member", "group": "Squad", "username": "B"})
    update = event(b, "added")
    assert update["members"] == ["A", "B"]
    assert event(a, "added")["text"] == "A added B to Squad"


def test_non_admin_cannot_add(server, connect):
    a, b = connect("A"), connect("B")
    connect("C")
    make_group(server, a, "Squad", b)
    b.send({"type": "add_member", "group": "Squad", "username": "C"})
    assert b.recv_until("error")["code"] == "NOT_GROUP_ADMIN"
    assert server.groups.members("Squad") == ["A", "B"]


def test_adding_offline_user(server, connect):
    a = connect("A")
    make_group(server, a, "Squad")
    a.send({"type": "add_member", "group": "Squad", "username": "ghost"})
    assert a.recv_until("error")["message"] == "User not found/offline"


def test_non_member_cannot_send_to_group(server, connect):
    a, b = connect("A"), connect("B")
    make_group(server, a, "Squad")
    b.send({"type": "group", "group": "Squad", "text": "let me in"})
    assert b.recv_until("error")["code"] == "NOT_A_MEMBER"
    assert group_chats(a) == []


def test_unknown_group(server, connect):
    a = connect("A")
    for msg in ({"type": "join_group", "group": "Nope"},
                {"type": "group", "group": "Nope", "text": "hi"},
                {"type": "leave_group", "group": "Nope"}):
        a.send(msg)
        assert a.recv_until("error")["code"] == "GROUP_NOT_FOUND"


def test_group_text_is_validated(server, connect):  # UT_15
    a, b = connect("A"), connect("B")
    make_group(server, a, "Squad", b)
    a.send({"type": "group", "group": "Squad", "text": "   "})
    assert a.recv_until("error")["code"] == "EMPTY_MESSAGE"
    a.send({"type": "group", "group": "Squad", "text": "x" * 4001})
    assert a.recv_until("error")["code"] == "MESSAGE_TOO_LONG"


def test_unregistered_socket_cannot_use_groups(server, connect):
    stranger = connect()
    stranger.send({"type": "create_group", "group": "Squad"})
    assert stranger.recv()["code"] == "NOT_REGISTERED"
    assert server.groups.names() == []


# ------------------------------------------------------------- client side
def test_parse_group_commands():
    assert parse_command("/create Squad") == ({"type": "create_group", "group": "Squad"}, None)
    assert parse_command("/join Squad") == ({"type": "join_group", "group": "Squad"}, None)
    assert parse_command("/leave Squad") == ({"type": "leave_group", "group": "Squad"}, None)
    assert parse_command("/add Squad bob") == (
        {"type": "add_member", "group": "Squad", "username": "bob"}, None)
    assert parse_command("/g Squad hello team") == (
        {"type": "group", "group": "Squad", "text": "hello team"}, None)


def test_parse_group_commands_need_arguments():
    for line in ("/create", "/join", "/add Squad", "/g Squad", "/g Squad   "):
        message, local = parse_command(line)
        assert message is None and local.startswith("Usage")
