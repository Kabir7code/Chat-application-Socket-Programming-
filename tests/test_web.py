"""Web gateway (#16), driven over HTTP the way the browser page uses it.

No browser needed: urllib plays the part of each tab, and every read of the
event stream has a timeout, so a missing message fails the test, not hangs it.
"""

import http.client
import json
import socket
import urllib.error
import urllib.request

import pytest

from chat import protocol, web
from chat.server import MAX_TEXT_LENGTH

TIMEOUT = 3


@pytest.fixture
def gateway(server):
    gw = web.ChatGateway(server.host, server.port, tls_context=None, web_port=0).start()
    yield gw
    gw.stop()


def base_url(gateway):
    return f"http://127.0.0.1:{gateway.web_port}"


def post(gateway, path, payload):
    """POST JSON; returns (status, reply) for errors as well as successes."""
    request = urllib.request.Request(
        base_url(gateway) + path,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            return response.status, json.load(response)
    except urllib.error.HTTPError as error:
        with error:
            return error.code, json.load(error)


class Tab:
    """One browser tab: a session plus its open event stream."""

    def __init__(self, gateway, username):
        self.gateway = gateway
        status, reply = post(gateway, "/api/connect", {"username": username})
        assert status == 200, reply
        self.session = reply["session"]
        self.reply = reply
        self.stream = urllib.request.urlopen(
            f"{base_url(gateway)}/api/events?session={self.session}", timeout=TIMEOUT)

    def send(self, **message):
        status, reply = post(self.gateway, "/api/send",
                             {"session": self.session, "message": message})
        assert status == 200, reply

    def command(self, line):
        status, reply = post(self.gateway, "/api/command",
                             {"session": self.session, "line": line})
        assert status == 200, reply
        return reply

    def next_event(self):
        """The next event. A socket timeout here fails the test."""
        while True:
            line = self.stream.readline()
            assert line, "event stream ended"
            if line.startswith(b"data: "):
                return json.loads(line[len(b"data: "):])

    def wait_for(self, matches):
        """Read events until one matches; returns all events read so far."""
        seen = []
        while True:
            seen.append(self.next_event())
            if matches(seen[-1]):
                return seen

    def wait_for_type(self, kind):
        return self.wait_for(lambda event: event["type"] == kind)[-1]

    def close(self):
        self.stream.close()


@pytest.fixture
def tab(gateway):
    tabs = []

    def _tab(username):
        new = Tab(gateway, username)
        tabs.append(new)
        return new

    yield _tab
    for each in tabs:
        each.close()


def has_text(text):
    return lambda event: event.get("text") == text


# ------------------------------------------------------------ connecting
def test_two_users_connect(gateway, tab):
    alice = tab("alice")
    bob = tab("bob")
    assert alice.reply["username"] == "alice"
    assert alice.reply["encrypted"] is False
    assert bob.reply["users"] == ["alice", "bob"]
    assert alice.session != bob.session


def test_duplicate_username_is_refused_and_can_retry(gateway, tab):
    tab("alice")
    status, reply = post(gateway, "/api/connect", {"username": "alice"})
    assert status == 400
    assert reply == {"error": "Username already taken."}
    assert tab("alice2").reply["username"] == "alice2"


@pytest.mark.parametrize("username", ["", "has space", "x" * 21, "bad!name"])
def test_invalid_username_is_refused(gateway, username):
    status, reply = post(gateway, "/api/connect", {"username": username})
    assert status == 400
    assert "1-20 letters" in reply["error"]


def test_username_must_be_text(gateway):
    status, _ = post(gateway, "/api/connect", {"username": 7})
    assert status == 400


def test_chat_server_unreachable(server):
    with socket.socket() as spare:  # a port with nothing listening on it
        spare.bind(("127.0.0.1", 0))
        closed_port = spare.getsockname()[1]
    gw = web.ChatGateway("127.0.0.1", closed_port, web_port=0).start()
    try:
        status, reply = post(gw, "/api/connect", {"username": "alice"})
    finally:
        gw.stop()
    assert status == 502
    assert "Could not reach" in reply["error"]


# -------------------------------------------------------------- messages
def test_broadcast_reaches_the_other_stream(gateway, tab):
    alice, bob = tab("alice"), tab("bob")
    alice.send(type="chat", text="hello")
    event = bob.wait_for_type("chat")
    assert event["from"] == "alice"
    assert event["text"] == "hello"
    assert event["display"].endswith("alice: hello")


def test_sender_sees_their_own_message_once(gateway, tab):
    alice, bob = tab("alice"), tab("bob")
    alice.send(type="chat", text="one")
    alice.send(type="chat", text="two")
    seen = alice.wait_for(has_text("two"))
    mine = [event for event in seen if event["type"] == "chat"]
    assert [event["text"] for event in mine] == ["one", "two"]
    assert all(event["self"] for event in mine)
    assert not bob.wait_for_type("chat").get("self")


@pytest.mark.parametrize("text", ["   ", "x" * (MAX_TEXT_LENGTH + 1)])
def test_refused_message_is_not_echoed(gateway, tab, text):
    alice = tab("alice")
    alice.send(type="chat", text=text)
    seen = alice.wait_for(lambda event: event["type"] == "error")
    assert not [event for event in seen if event["type"] == "chat"]


def test_private_message_reaches_only_the_recipient(gateway, tab):
    alice, bob, carol = tab("alice"), tab("bob"), tab("carol")
    alice.send(type="private", to="bob", text="secret")

    assert bob.wait_for_type("private")["text"] == "secret"
    assert alice.wait_for_type("private_sent")["to"] == "bob"

    # Carol's stream is in order, so this later message proves she skipped the first.
    alice.send(type="chat", text="public")
    seen = carol.wait_for(has_text("public"))
    assert not [event for event in seen if event.get("text") == "secret"]


def test_private_message_to_unknown_user(gateway, tab):
    alice = tab("alice")
    alice.send(type="private", to="ghost", text="hi")
    assert alice.wait_for_type("error")["code"] == "USER_NOT_FOUND"


# ---------------------------------------------------------------- groups
def test_create_join_and_group_message(gateway, tab):
    alice, bob, carol = tab("alice"), tab("bob"), tab("carol")
    alice.send(type="create_group", group="Squad")
    assert alice.wait_for_type("group_update")["members"] == ["alice"]
    bob.send(type="join_group", group="Squad")
    assert bob.wait_for_type("group_update")["members"] == ["alice", "bob"]
    alice.wait_for_type("group_update")

    alice.send(type="group", group="Squad", text="team")
    event = bob.wait_for_type("chat")
    assert (event["context"], event["group"], event["text"]) == ("group", "Squad", "team")
    assert "[Squad] alice: team" in event["display"]
    assert alice.wait_for_type("chat")["self"] is True  # the sender's own copy

    alice.send(type="chat", text="public")
    seen = carol.wait_for(has_text("public"))
    assert not [event for event in seen if event.get("text") == "team"]


def test_late_joiner_sees_earlier_messages(gateway, tab):
    alice, bob = tab("alice"), tab("bob")
    alice.send(type="create_group", group="Squad")
    alice.wait_for_type("group_update")
    alice.send(type="group", group="Squad", text="before bob")
    assert alice.wait_for_type("chat")["text"] == "before bob"

    bob.send(type="join_group", group="Squad")
    event = bob.wait_for(has_text("before bob"))[-1]
    assert event["history"] is True
    assert "(earlier)" in event["display"]


def test_non_member_gets_an_error_and_no_echo(gateway, tab):
    alice, bob = tab("alice"), tab("bob")
    alice.send(type="create_group", group="Squad")
    alice.wait_for_type("group_update")
    bob.send(type="group", group="Squad", text="let me in")
    seen = bob.wait_for(lambda event: event["type"] == "error")
    assert seen[-1]["code"] == "NOT_A_MEMBER"
    assert not [event for event in seen if event["type"] == "chat"]


def test_only_the_admin_can_add_members(gateway, tab):
    alice, bob, carol = tab("alice"), tab("bob"), tab("carol")
    alice.send(type="create_group", group="Squad")
    alice.wait_for_type("group_update")
    bob.send(type="join_group", group="Squad")
    bob.wait_for_type("group_update")
    bob.send(type="add_member", group="Squad", username="carol")
    assert bob.wait_for_type("error")["code"] == "NOT_GROUP_ADMIN"
    alice.send(type="add_member", group="Squad", username="carol")
    assert "carol" in carol.wait_for_type("group_update")["members"]


# -------------------------------------------------------------- commands
def test_users_command(gateway, tab):
    alice = tab("alice")
    tab("bob")
    assert alice.command("/users") == {"ok": True, "quit": False}
    event = alice.wait_for_type("users")
    assert event["users"] == ["alice", "bob"]
    assert event["display"] == "* Online (2): alice, bob"


def test_slash_commands_use_the_terminal_rules(gateway, tab):
    alice, bob = tab("alice"), tab("bob")
    alice.command("/msg bob hello there")
    assert bob.wait_for_type("private")["text"] == "hello there"
    alice.command("/create Squad")
    assert alice.wait_for_type("group_update")["group"] == "Squad"
    bob.command("/join Squad")
    bob.wait_for_type("group_update")
    alice.command("/g Squad hi  team")
    assert bob.wait_for_type("chat")["text"] == "hi  team"


def test_commands_answered_locally(gateway, tab):
    alice = tab("alice")
    assert "/users" in alice.command("/help")["local"]
    assert alice.command("/msg bob")["local"] == "Usage: /msg <user> <text>"
    assert "Unknown command" in alice.command("/nope")["local"]


def test_quit_command_leaves_the_chat(gateway, tab):
    alice, bob = tab("alice"), tab("bob")
    assert alice.command("/quit")["quit"] is True
    assert bob.wait_for_type("system")["event"] == "leave"
    assert gateway.get_session(alice.session) is None


# ---------------------------------------------------------- disconnecting
def test_disconnect_gives_a_leave_notice_and_frees_the_name(gateway, tab):
    alice, bob = tab("alice"), tab("bob")
    status, _ = post(gateway, "/api/disconnect", {"session": bob.session})
    assert status == 200
    event = alice.wait_for(lambda event: event.get("event") == "leave")[-1]
    assert event["username"] == "bob"
    assert bob.wait_for_type("disconnected")
    assert tab("bob").reply["username"] == "bob"


def test_chat_server_going_away_is_reported(server, gateway, tab):
    alice = tab("alice")
    server.stop()
    assert alice.wait_for_type("disconnected") == {"type": "disconnected"}


def test_closing_the_stream_ends_the_session(gateway, tab, monkeypatch):
    monkeypatch.setattr(web, "HEARTBEAT_SECONDS", 0.05)
    alice, bob = tab("alice"), tab("bob")
    alice.close()
    assert bob.wait_for_type("system")["event"] == "leave"
    assert gateway.get_session(alice.session) is None


def test_session_without_a_stream_is_closed(gateway, monkeypatch):
    monkeypatch.setattr(web, "STREAM_GRACE_SECONDS", 0.05)
    other = Tab(gateway, "alice")
    status, reply = post(gateway, "/api/connect", {"username": "bob"})
    assert status == 200
    assert other.wait_for(lambda event: event.get("event") == "leave")
    assert gateway.get_session(reply["session"]) is None
    other.close()


def test_second_stream_for_a_session_is_refused(gateway, tab):
    alice = tab("alice")
    with pytest.raises(urllib.error.HTTPError) as error:
        urllib.request.urlopen(
            f"{base_url(gateway)}/api/events?session={alice.session}", timeout=TIMEOUT)
    assert error.value.code == 409
    error.value.close()


# --------------------------------------------------------- bad requests
@pytest.mark.parametrize("path, payload", [
    ("/api/send", {"session": "nope", "message": {"type": "chat", "text": "x"}}),
    ("/api/command", {"session": "nope", "line": "/users"}),
    ("/api/disconnect", {"session": "nope"}),
    ("/api/send", {"message": {"type": "chat", "text": "x"}}),
])
def test_unknown_session_is_404(gateway, path, payload):
    status, reply = post(gateway, path, payload)
    assert status == 404
    assert reply == {"error": "Unknown session."}


def test_events_with_unknown_session_is_404(gateway):
    with pytest.raises(urllib.error.HTTPError) as error:
        urllib.request.urlopen(f"{base_url(gateway)}/api/events?session=nope", timeout=TIMEOUT)
    assert error.value.code == 404
    error.value.close()


@pytest.mark.parametrize("message", [None, "text", {}, {"type": 5}])
def test_send_needs_a_proper_message(gateway, tab, message):
    alice = tab("alice")
    status, _ = post(gateway, "/api/send", {"session": alice.session, "message": message})
    assert status == 400


def test_oversized_message_is_refused(gateway, tab):
    alice = tab("alice")
    payload = {"session": alice.session,
               "message": {"type": "chat", "text": "x" * (protocol.MAX_FRAME_BYTES + 1)}}
    status, reply = post(gateway, "/api/send", payload)
    assert status == 400
    assert "too large" in reply["error"]


def raw_request(gateway, method, path, body=None, headers=None):
    """http.client sends the path exactly as written, unlike a browser."""
    connection = http.client.HTTPConnection("127.0.0.1", gateway.web_port, timeout=TIMEOUT)
    try:
        connection.request(method, path, body=body, headers=headers or {})
        response = connection.getresponse()
        return response.status, response.read(), response
    finally:
        connection.close()


def test_post_from_another_site_is_refused(gateway):
    """A cross-site form can only send text/plain and similar, never JSON."""
    status, _, _ = raw_request(gateway, "POST", "/api/connect", body='{"username": "evil"}',
                               headers={"Content-Type": "text/plain"})
    assert status == 415
    assert gateway._sessions == {}


def test_bad_json_is_refused(gateway):
    status, _, _ = raw_request(gateway, "POST", "/api/connect", body="{nope",
                               headers={"Content-Type": "application/json"})
    assert status == 400


def test_huge_body_is_refused(gateway):
    status, _, _ = raw_request(
        gateway, "POST", "/api/connect", body="x" * (web.MAX_BODY_BYTES + 1),
        headers={"Content-Type": "application/json"})
    assert status == 413


# ---------------------------------------------------------- static files
@pytest.mark.parametrize("path, kind, marker", [
    ("/", "text/html", b"join-form"),
    ("/index.html", "text/html", b"join-form"),
    ("/app.js", "text/javascript", b"EventSource"),
    ("/style.css", "text/css", b".messages"),
])
def test_page_files_are_served(gateway, path, kind, marker):
    status, body, response = raw_request(gateway, "GET", path)
    assert status == 200
    assert response.getheader("Content-Type").startswith(kind)
    assert marker in body


def test_favicon_request_is_answered_quietly(gateway):
    status, body, _ = raw_request(gateway, "GET", "/favicon.ico")
    assert (status, body) == (204, b"")


@pytest.mark.parametrize("path", [
    "/../setup.cfg",
    "/..%2fsetup.cfg",
    "/%2e%2e/setup.cfg",
    "/static/../../setup.cfg",
    "//etc/passwd",
    "/web.py",
    "/chat/web.py",
])
def test_nothing_else_can_be_fetched(gateway, path):
    status, body, _ = raw_request(gateway, "GET", path)
    assert status == 404
    assert b"flake8" not in body


def test_gateway_binds_to_localhost_by_default():
    assert web.parse_args([]).web_host == "127.0.0.1"


def test_gateway_flags_and_chat_server_flags():
    args = web.parse_args(["--web-port", "9000", "--web-host", "0.0.0.0",
                           "--host", "10.0.0.5", "--port", "6000", "--no-tls"])
    assert (args.web_port, args.web_host) == (9000, "0.0.0.0")
    assert (args.host, args.port, args.no_tls) == ("10.0.0.5", 6000, True)
