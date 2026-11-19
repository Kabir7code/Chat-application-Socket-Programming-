"""#53: the web UI gets saved history when someone joins."""

import pathlib
import time

import pytest

from chat import web
from chat.server import ChatServer

from test_web import Tab

APP_JS = (pathlib.Path(web.__file__).parent / "static" / "app.js").read_text()


@pytest.fixture
def gateway(server):
    gw = web.ChatGateway(server.host, server.port, tls_context=None, web_port=0).start()
    yield gw
    gw.stop()


def wait_until(check, timeout=3.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if check():
            return True
        time.sleep(0.02)
    return False


def test_everyone_history_reaches_the_page(server, gateway):
    alice = Tab(gateway, "alice")
    alice.send(type="chat", text="before bob")
    assert wait_until(lambda: len(server.store.recent_chat()) == 1)
    bob = Tab(gateway, "bob")
    try:
        event = bob.wait_for(lambda e: e.get("history") and e["type"] == "chat")[-1]
        assert event["text"] == "before bob" and event["from"] == "alice"
        assert event["display"].endswith("(earlier) alice: before bob")
    finally:
        alice.close()
        bob.close()


def test_page_can_load_a_private_chat(server, gateway):
    alice, bob = Tab(gateway, "alice"), Tab(gateway, "bob")
    try:
        alice.send(type="private", to="bob", text="hello bob")
        bob.wait_for_type("private")
        bob.send(type="private_history", **{"with": "alice"})
        reply = bob.wait_for_type("private_history")
        assert reply["with"] == "alice"
        assert [(m["from"], m["text"]) for m in reply["messages"]] == [("alice", "hello bob")]
        assert all(m["history"] and m["id"] for m in reply["messages"])
        assert reply["display"].startswith("* Private messages with alice")
    finally:
        alice.close()
        bob.close()


def test_history_command_works_from_the_page(server, gateway):
    alice, bob = Tab(gateway, "alice"), Tab(gateway, "bob")
    try:
        alice.send(type="private", to="bob", text="typed")
        alice.wait_for_type("private_sent")
        alice.command("/history bob")
        assert [m["text"] for m in alice.wait_for_type("private_history")["messages"]] == ["typed"]
    finally:
        alice.close()
        bob.close()


def test_other_peoples_private_chats_stay_private(server, gateway):
    alice, bob, carol = Tab(gateway, "alice"), Tab(gateway, "bob"), Tab(gateway, "carol")
    try:
        alice.send(type="private", to="bob", text="secret")
        bob.wait_for_type("private")
        carol.send(type="private_history", **{"with": "alice"})
        assert carol.wait_for_type("private_history")["messages"] == []
    finally:
        for each in (alice, bob, carol):
            each.close()


def test_group_history_reaches_the_page(server, gateway):
    alice, bob = Tab(gateway, "alice"), Tab(gateway, "bob")
    try:
        alice.send(type="create_group", group="Squad")
        alice.wait_for_type("group_update")
        alice.send(type="group", group="Squad", text="for the squad")
        assert wait_until(lambda: len(server.store.group_messages("Squad")) == 1)
        bob.send(type="join_group", group="Squad")
        event = bob.wait_for(lambda e: e.get("history") and e.get("group") == "Squad")[-1]
        assert event["text"] == "for the squad"
    finally:
        alice.close()
        bob.close()


def test_page_gets_its_groups_back_after_a_server_restart(tmp_path):
    path = str(tmp_path / "chat.db")
    srv = ChatServer(port=0, db_path=path).start()
    gw = web.ChatGateway(srv.host, srv.port, tls_context=None, web_port=0).start()
    alice = Tab(gw, "alice")
    alice.send(type="create_group", group="Squad")
    alice.wait_for_type("group_update")
    alice.send(type="group", group="Squad", text="saved")
    assert wait_until(lambda: len(srv.store.group_messages("Squad")) == 1)
    srv.stop()
    gw.stop()
    alice.close()

    srv = ChatServer(port=0, db_path=path).start()
    gw = web.ChatGateway(srv.host, srv.port, tls_context=None, web_port=0).start()
    alice = Tab(gw, "alice")
    try:
        update = alice.wait_for_type("group_update")
        assert update["group"] == "Squad" and update["event"] == "member"
        assert "alice" in update["members"]
        event = alice.wait_for(lambda e: e.get("history") and e.get("group") == "Squad")[-1]
        assert event["text"] == "saved" and event["from"] == "alice"
    finally:
        alice.close()
        gw.stop()
        srv.stop()


# --------------------------------------------------------------- the page
def test_page_asks_for_private_history_when_a_chat_opens():
    assert 'type: "private_history"' in APP_JS
    assert "loadPrivateHistory(privateChat(" in APP_JS


def test_page_handles_private_history_replies():
    assert 'case "private_history":' in APP_JS
    assert "function addPrivateHistory" in APP_JS


def test_page_does_not_count_old_messages_as_unread():
    assert "addTo(EVERYONE, bubble(message, mine), { countUnread: !message.history });" in APP_JS
