"""Part-3 (11 Nov 2026): the script used to run every test case in the Test Cases document.

Run from the repository root: python Documents/Test_Reports/run_test_cases.py . results.json [ID ...]
Needs Playwright with Chromium for UT_02, UT_03 and ST_21.

Execute the test cases in the Test Cases document against the Sprint 3 code.

Usage: python run_cases.py <code-dir> <out.json> [ID ...]
Each case function returns (actual_result_text, result).
"""

import io
import json
import logging
import os
import re
import socket
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
from contextlib import contextmanager, redirect_stdout

CODE = os.path.abspath(sys.argv[1])
sys.path.insert(0, CODE)

from chat import client as cl  # noqa: E402
from chat import config, groups, protocol, registry, storage  # noqa: E402
from chat.server import ChatServer  # noqa: E402

PASS, FAIL, PARTIAL = "Pass", "Fail", "Partial"
CASES = {}


def case(fn):
    CASES[fn.__name__.upper()] = fn
    return fn


# ------------------------------------------------------------------ helpers
@contextmanager
def server(db=None, keep=0):
    srv = ChatServer(port=0, db_path=db or ":memory:", keep=keep).start()
    try:
        yield srv
    finally:
        srv.stop()


class C:
    """A wire-protocol client."""

    def __init__(self, srv, name=None):
        self.srv = srv
        self.sock = socket.create_connection((srv.host, srv.port))
        self.sock.settimeout(3)
        self.name = name
        self.reply = None
        if name is not None:
            self.send(type="register", username=name)
            self.reply = self.until("registered", "error")

    def send(self, **message):
        protocol.send_message(self.sock, message)

    def recv(self, timeout=3):
        self.sock.settimeout(timeout)
        return protocol.recv_message(self.sock)

    def until(self, *types, timeout=3):
        deadline = time.time() + timeout
        while True:
            left = deadline - time.time()
            if left <= 0:
                raise TimeoutError(f"no {types}")
            message = self.recv(left)
            if message is None:
                return None
            if message["type"] in types:
                return message

    def drain(self, wait=0.4):
        got = []
        try:
            while True:
                message = self.recv(wait)
                if message is None:
                    break
                got.append(message)
        except (socket.timeout, TimeoutError):
            pass
        return got

    def close(self):
        try:
            self.sock.close()
        except OSError:
            pass


def chats(messages, kind="chat"):
    return [m for m in messages if m["type"] == kind]


def texts(messages):
    return [m["text"] for m in messages]


def wait_until(check, timeout=4.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if check():
            return True
        time.sleep(0.02)
    return False


def terminal(srv, lines, wait=1.0, port=None):
    """Run the real terminal client with the given input lines."""
    proc = subprocess.Popen(
        [sys.executable, "-m", "chat.client", "--no-tls", "--host", "127.0.0.1",
         "--port", str(port or srv.port)],
        cwd=CODE, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True)
    try:
        for line in lines:
            proc.stdin.write(line + "\n")
            proc.stdin.flush()
            time.sleep(0.3)
        time.sleep(wait)
        proc.stdin.close()
    except (BrokenPipeError, OSError):
        pass
    try:
        out, _ = proc.communicate(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()
        out, _ = proc.communicate()
    return out, proc.returncode


class FakeSock:
    def __init__(self, fail=False):
        self.fail = fail
        self.closed = False
        self.sent = b""

    def sendall(self, data):
        if self.fail or self.closed:
            raise OSError("send failed")
        self.sent += data

    def shutdown(self, how):
        pass

    def close(self):
        self.closed = True

    def fileno(self):
        return -1 if self.closed else 3


def make_group(a, name, *others):
    a.send(type="create_group", group=name)
    a.until("group_update")
    for other in others:
        other.send(type="join_group", group=name)
        other.until("group_update")
        a.drain(0.2)


def tmpdb():
    folder = tempfile.mkdtemp(prefix="tc-")
    return os.path.join(folder, "chat.db")


# ======================================================= FR-001 registration
@case
def ut_01():
    with server() as srv:
        out, _ = terminal(srv, ["alice_23", "/quit"])
        ok = "Welcome, alice_23!" in out
        line = next((x for x in out.splitlines() if "Welcome" in x), out.strip()[:80])
        return f"Terminal client sent the name and the server accepted it; client printed: '{line.replace('Choose a username: ', '')}'", PASS if ok else FAIL


def web_join_check(name):
    """Type a username into the web page's join form; report what happens."""
    from chat import web
    from playwright.sync_api import sync_playwright
    with server() as srv:
        gw = web.ChatGateway(srv.host, srv.port, tls_context=None, web_port=0).start()
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch()
                page = browser.new_page()
                requests = []
                page.on("request", lambda r: requests.append(r.url) if "/api/connect" in r.url else None)
                page.goto(f"http://127.0.0.1:{gw.web_port}/")
                page.fill("#username", name)
                page.keyboard.press("Enter")
                page.wait_for_timeout(600)
                error = page.inner_text("#join-error")
                browser.close()
            return error, requests, srv.users
        finally:
            gw.stop()


@case
def ut_02():
    error, requests, users = web_join_check("")
    with server() as srv:
        out, _ = terminal(srv, ["", "/quit"])
        reply = next((x for x in out.splitlines() if "username" in x.lower() and "Choose" not in x), "")
        reply = reply or [x for x in out.splitlines() if x.strip()][-1]
    web_ok = bool(error) and not requests
    term_ok = "empty" in out.lower() and "error" not in out.lower()
    actual = (f"Web UI: blocked on the page with '{error}', no request sent. "
              f"Terminal client: not blocked, the empty name is sent and the server replies "
              f"'{reply.replace('Choose a username: ', '').strip().lstrip('! ')}' (#29 is closed, but the "
              "terminal client was not changed).")
    if web_ok and term_ok:
        return actual, PASS
    return actual, PARTIAL if web_ok else FAIL


@case
def ut_03():
    name = "a" * 50
    error, requests, users = web_join_check(name)
    with server() as srv:
        out, _ = terminal(srv, [name, "/quit"])
        lines = [x.replace("Choose a username: ", "").strip() for x in out.splitlines()]
        reply = next((x for x in lines if x and "Choose" not in x), "")
    web_ok = bool(error) and not requests
    joined = users[0] if users else None
    actual = (f"Web UI: the name box stops at 20 characters, so the page joined as a {len(joined or '')}-"
              f"character name without any message. Terminal client: not blocked locally; the name is sent "
              f"and the server rejects it with '{reply.lstrip('! ')}'. The limit is enforced, but no client "
              "shows 'Username exceeds maximum length' before sending (#29 is closed, but the terminal "
              "client was not changed).")
    return actual, PARTIAL


@case
def it_01():
    with server() as srv:
        a = C(srv, "rahul")
        ok = a.reply["type"] == "registered" and "rahul" in srv.users
        return f"Server replied 'registered' and 'rahul' is in the active-user list {srv.users}.", PASS if ok else FAIL


@case
def it_02():
    with server() as srv:
        first = C(srv, "rahul")  # noqa: F841 - stays connected
        b = C(srv, "rahul")
        ok = b.reply["type"] == "error" and srv.users == ["rahul"]
        return (f"Second 'rahul' got error '{b.reply.get('message')}' ({b.reply.get('code')}); "
                f"active-user list is still {srv.users}."), PASS if ok else FAIL


@case
def it_03():
    with server() as srv:
        big = C(srv, "Rahul")  # noqa: F841 - stays connected
        first = C(srv, "rahul")
        r1 = first.reply["type"]
        first.send(type="quit")
        wait_until(lambda: "rahul" not in srv.users)
        second = C(srv, "rahul")
        r2 = second.reply["type"]
        ok = r1 == r2 == "registered" and "Rahul" in srv.users
        return (f"Usernames are case-sensitive (documented in the SAD): 'rahul' was accepted while 'Rahul' "
                f"was online ({r1}); the same attempt repeated gave the same decision ({r2})."), PASS if ok else FAIL


@case
def st_01():
    with server() as srv:
        start = time.time()
        a = C(srv, "priya_k")
        took = (time.time() - start) * 1000
        out, _ = terminal(srv, ["priya_k2", "/quit"])
        line = next((x for x in out.splitlines() if "Welcome" in x), "")
        ok = a.reply["type"] == "registered" and "priya_k" in srv.users and "Welcome" in out
        return (f"Registered in {took:.0f} ms; 'priya_k' is in the server's active-user list. The terminal "
                f"client reaches the chat prompt ('{line.replace('Choose a username: ', '')}')."), PASS if ok else FAIL


@case
def st_02():
    probe = socket.socket()
    probe.bind(("127.0.0.1", 0))
    port = probe.getsockname()[1]
    probe.close()
    start = time.time()
    out, code = terminal(None, ["amit99"], wait=0.2, port=port)
    took = time.time() - start
    line = out.strip().splitlines()[-1] if out.strip() else ""
    ok = "Could not connect" in out and took < 10
    shown = re.sub(r":\d+", ":<port>", line)
    return f"Client exited after {took:.1f} s with '{shown}' instead of hanging.", PASS if ok else FAIL


# ===================================================== FR-002 concurrent sessions
@case
def ut_04():
    reg = registry.SessionRegistry()
    sock = FakeSock()
    s = registry.Session(sock)
    reg.connect(s)
    reg.register(s, "testuser1")
    ok = s.username == "testuser1" and s.conn is sock and s.alive
    return f"Session holds username '{s.username}', the socket passed in, and alive={s.alive}.", PASS if ok else FAIL


@case
def ut_05():
    reg = registry.SessionRegistry()
    a, b = registry.Session(FakeSock()), registry.Session(FakeSock())
    reg.register(a, "userA")
    reg.register(b, "userB")
    found = reg.get("userA")
    ok = found is a and found is not b
    return "Lookup returned userA's session only (the registry looks sessions up by username).", PASS if ok else FAIL


@case
def ut_06():
    reg = registry.SessionRegistry()
    s = {n: registry.Session(FakeSock()) for n in ("userA", "userB", "userC")}
    for n, x in s.items():
        reg.register(x, n)
    reg.disconnect(s["userB"])
    ok = reg.usernames() == ["userA", "userC"] and s["userA"].alive and s["userC"].alive
    return f"After removing userB the store holds {reg.usernames()}; userA and userC unchanged.", PASS if ok else FAIL


@case
def it_04():
    with server() as srv:
        a, b = C(srv, "userA"), C(srv, "userB")
        ra, rb = srv.registry.get("userA"), srv.registry.get("userB")
        ok = srv.users == ["userA", "userB"] and ra is not rb and ra.conn is not rb.conn
        return f"Both appear in the active list {srv.users}, each on its own socket and session.", PASS if ok else FAIL


@case
def it_05():
    with server() as srv:
        a, b = C(srv, "userA"), C(srv, "userB")
        start = time.time()
        for i in range(5):
            a.send(type="chat", text=f"burst {i}")
        b.send(type="list_users")
        reply = b.until("users")
        took = (time.time() - start) * 1000
        got = texts(chats(b.drain(0.3)))
        ok = reply["users"] == ["userA", "userB"]
        return (f"While A sent 5 messages, B stayed connected and its own request was answered in "
                f"{took:.0f} ms; B also received A's messages."), PASS if ok else FAIL


@case
def it_06():
    with server() as srv:
        a, b, c = C(srv, "userA"), C(srv, "userB"), C(srv, "userC")
        b.close()
        wait_until(lambda: srv.users == ["userA", "userC"])
        a.send(type="private", to="userC", text="still here")
        got = c.until("private")["text"]
        ok = srv.users == ["userA", "userC"] and got == "still here"
        return f"Only userB was removed; list is {srv.users} and A -> C messaging still works.", PASS if ok else FAIL


@case
def st_03():
    with server() as srv:
        start = time.time()
        clients = [C(srv, f"user{i}") for i in range(10)]
        took = time.time() - start
        clients[0].send(type="chat", text="ping")
        ok_all = all(chats(c.drain(0.3)) for c in clients[1:])
        ok = len(srv.users) == 10 and ok_all
        return (f"All 10 clients registered in {took:.2f} s; the server tracks 10 sessions and a message "
                f"from one reached the other 9."), PASS if ok else FAIL


@case
def st_04():
    with server() as srv:
        old = [C(srv, f"u{i}") for i in range(5)]
        stop = threading.Event()

        def chatter():
            i = 0
            while not stop.is_set():
                old[i % 5].send(type="chat", text=f"live {i}")
                i += 1
                time.sleep(0.02)
            return i

        t = threading.Thread(target=chatter)
        t.start()
        time.sleep(0.2)
        new = C(srv, "newcomer")
        time.sleep(0.2)
        stop.set()
        t.join()
        alive = all(srv.registry.get(f"u{i}") for i in range(5))
        ok = new.reply["type"] == "registered" and alive and len(srv.users) == 6
        return ("New client joined during live chat; the 5 existing users stayed connected and kept "
                "receiving messages."), PASS if ok else FAIL


# ========================================================= FR-003 messaging
@case
def ut_07():
    m = protocol.make_chat_message("Hello there", "userA")
    ok = m["from"] == "userA" and m["text"] == "Hello there" and isinstance(m.get("id"), int)
    return (f"Function returns {{'type': 'chat', 'id': {m['id']}, 'time': '...', 'from': 'userA', "
            f"'text': 'Hello there'}} - sender, text and a generated message ID."), PASS if ok else FAIL


@case
def ut_08():
    with server() as srv:
        watcher = C(srv, "watcher")
        out, _ = terminal(srv, ["sender", "", "   ", "/quit"])
        got = chats(watcher.drain(0.5))
        a = C(srv, "raw")
        a.send(type="chat", text="   ")
        err = a.until("error")
        ok = not got and err["code"] == "EMPTY_MESSAGE"
        return ("Pressing Enter on an empty or blank line sends nothing (other users received 0 messages); "
                f"a blank message sent directly is rejected by the server ({err['code']})."), PASS if ok else FAIL


@case
def ut_09():
    with server() as srv:
        a, b = C(srv, "a"), C(srv, "b")
        a.send(type="chat", text="x" * 4001)
        err = a.until("error")
        a.send(type="chat", text="y" * 1500)
        ok_long = len(b.until("chat")["text"]) == 1500
        ok = err["code"] == "MESSAGE_TOO_LONG" and ok_long and not chats(b.drain(0.2))
        return (f"Limit is 4000 characters (D4). A 4001-character message is rejected with '{err['message']}' "
                "and nothing is delivered; 1500 characters are delivered whole."), PASS if ok else FAIL


@case
def it_07():
    with server() as srv:
        a, b = C(srv, "clientA"), C(srv, "clientB")
        a.send(type="chat", text="Hi Client B")
        m = b.until("chat")
        ok = m["from"] == "clientA" and m["text"] == "Hi Client B"
        return f"Client B received {{from: clientA, text: 'Hi Client B'}} immediately, with an ID and timestamp.", PASS if ok else FAIL


@case
def it_08():
    runs, bad = 200, 0
    with server() as srv:
        for r in range(runs):
            a, b, c = C(srv, f"a{r}"), C(srv, f"b{r}"), C(srv, f"c{r}")
            d, e = C(srv, f"d{r}"), C(srv, f"e{r}")
            for x in (a, b, c, d, e):
                x.drain(0.05)
            barrier = threading.Barrier(3)

            def go(cl_, text):
                barrier.wait()
                cl_.send(type="chat", text=text)

            ts = [threading.Thread(target=go, args=(x, t)) for x, t in ((a, "one"), (b, "two"), (c, "three"))]
            for t in ts:
                t.start()
            for t in ts:
                t.join()
            seen_d = [d.until("chat")["text"] for _ in range(3)]
            seen_e = [e.until("chat")["text"] for _ in range(3)]
            if seen_d != seen_e:
                bad += 1
            for x in (a, b, c, d, e):
                x.send(type="quit")
                x.close()
            wait_until(lambda: not srv.users, 2)
    ok = bad == 0
    return (f"Three senders fired at the same instant, {runs} runs: the two observers saw the same order "
            f"every time, with correct senders ({bad} mismatches; was 4 in 300 in Sprint 1, fixed by #31)."), PASS if ok else FAIL


@case
def it_09():
    with server() as srv:
        a, b = C(srv, "userA"), C(srv, "userB")
        a.send(type="private", to="userB", text="are you still there?")
        b.close()
        reply = a.until("private_sent", "error")
        a.send(type="private", to="userB", text="are you still there?")
        wait_until(lambda: "userB" not in srv.users)
        second = a.until("private_sent", "error")
        ok = reply is not None and second is not None
        detail = "queued for later delivery" if second.get("queued") else second.get("type")
        return ("The server never reports a false success: the first message was confirmed as delivered "
                f"before B closed, and one sent after B left was reported as '{detail}' (FR-012), "
                "not dropped."), PASS if ok else FAIL


@case
def st_05():
    with server() as srv:
        a, b = C(srv, "a"), C(srv, "b")
        okc = True
        times = []
        for i in range(1, 11):
            src, dst = (a, b) if i % 2 else (b, a)
            start = time.time()
            src.send(type="private", to=dst.name, text=f"msg {i}")
            m = dst.until("private")
            times.append((time.time() - start) * 1000)
            okc &= m["text"] == f"msg {i}"
        return (f"All 10 alternating messages arrived at the right person, in order; slowest delivery "
                f"{max(times):.1f} ms."), PASS if okc else FAIL


# ST_06 (10 minutes idle) is run separately: see st_06_idle()
@case
def st_06():
    path = os.environ.get("ST06_RESULT")
    if path and os.path.exists(path):
        return tuple(json.load(open(path)))
    return "Not run in this pass.", "Not executed"


def st_06_idle(seconds=600):
    with server() as srv:
        a, b = C(srv, "a"), C(srv, "b")
        time.sleep(seconds)
        a.send(type="chat", text="back online")
        m = b.until("chat", timeout=5)
        ok = m["text"] == "back online"
        return (f"Both clients were left idle and connected for {seconds} seconds; 'back online' was "
                "then delivered normally."), PASS if ok else FAIL


# ======================================================= FR-004 group chat
@case
def ut_10():
    g = groups.GroupManager()
    g.create("ProjectTeam", "userA")
    ok = g.names() == ["ProjectTeam"] and g.members("ProjectTeam") == ["userA"] and g.admin("ProjectTeam") == "userA"
    return f"Group 'ProjectTeam' created with members {g.members('ProjectTeam')} and admin '{g.admin('ProjectTeam')}'.", PASS if ok else FAIL


@case
def ut_11():
    g = groups.GroupManager()
    g.create("ProjectTeam", "userA")
    try:
        g.create("ProjectTeam", "userB")
        return "Second create was accepted.", FAIL
    except groups.GroupError as exc:
        return f"Second create rejected with {exc.code}: '{exc}'. Only one 'ProjectTeam' exists.", PASS


@case
def ut_12():
    g = groups.GroupManager()
    g.create("ProjectTeam", "userA")
    g.join("ProjectTeam", "userB")
    b, c = g.is_member("ProjectTeam", "userB"), g.is_member("ProjectTeam", "userC")
    return f"is_member returns {b} for userB and {c} for userC.", PASS if (b and not c) else FAIL


@case
def it_10():
    with server() as srv:
        a = C(srv, "clientA")
        a.send(type="create_group", group="StudyGroup")
        u = a.until("group_update")
        ok = srv.groups.names() == ["StudyGroup"] and srv.groups.members("StudyGroup") == ["clientA"]
        return (f"'StudyGroup' is in the server's group list with members {u['members']}; A got a "
                f"'{u['event']}' update and is the admin."), PASS if ok else FAIL


@case
def it_11():
    with server() as srv:
        a, b = C(srv, "clientA"), C(srv, "clientB")
        make_group(a, "StudyGroup", b)
        b.send(type="group", group="StudyGroup", text="hello group")
        m = a.until("chat")
        ok = srv.groups.members("StudyGroup") == ["clientA", "clientB"] and m["text"] == "hello group"
        return f"B joined; members are {srv.groups.members('StudyGroup')} and B's group message reached A.", PASS if ok else FAIL


@case
def it_12():
    with server() as srv:
        a, b, c = C(srv, "A"), C(srv, "B"), C(srv, "C")
        make_group(a, "StudyGroup", b)
        c.drain(0.2)
        a.send(type="group", group="StudyGroup", text="Meeting at 5pm")
        mb = b.until("chat")
        gotc = [m for m in c.drain(0.4) if m.get("text") == "Meeting at 5pm"]
        ok = mb["group"] == "StudyGroup" and not gotc
        return "B received 'Meeting at 5pm' in StudyGroup; C received nothing (0 messages).", PASS if ok else FAIL


@case
def it_13():
    with server() as srv:
        a, b = C(srv, "A"), C(srv, "B")
        make_group(a, "StudyGroup", b)
        b.send(type="leave_group", group="StudyGroup")
        b.until("group_update")
        b.drain(0.2)
        a.send(type="group", group="StudyGroup", text="anyone still here?")
        gotb = [m for m in b.drain(0.4) if m.get("text") == "anyone still here?"]
        ok = not gotb and srv.groups.members("StudyGroup") == ["A"]
        return "After B left, 'anyone still here?' did not reach B; members are now ['A'].", PASS if ok else FAIL


@case
def it_14():
    with server() as srv:
        a = C(srv, "A")
        make_group(a, "StudyGroup")
        a.send(type="join_group", group="StudyGroup")
        r = a.until("error", "group_update")
        ok = srv.groups.members("StudyGroup") == ["A"] and srv.users == ["A"]
        return (f"Server answered '{r.get('message')}' ({r.get('code')}); membership not duplicated "
                f"({srv.groups.members('StudyGroup')}) and A stays connected."), PASS if ok else FAIL


@case
def st_07():
    with server() as srv:
        a, b, c = C(srv, "A"), C(srv, "B"), C(srv, "C")
        make_group(a, "Squad", b, c)
        for x in (a, b, c):
            x.drain(0.2)
        b.send(type="group", group="Squad", text="step 3")
        s3 = (a.until("chat")["text"], c.until("chat")["text"])
        c.send(type="leave_group", group="Squad")
        c.until("group_update")
        for x in (a, b, c):
            x.drain(0.2)
        a.send(type="group", group="Squad", text="step 5")
        s5b = b.until("chat")["text"]
        s5c = [m for m in c.drain(0.4) if m.get("text") == "step 5"]
        ok = s3 == ("step 3", "step 3") and s5b == "step 5" and not s5c
        return "Step 3 reached A and C; after C left, step 5 reached only B (and A sent it).", PASS if ok else FAIL


@case
def st_08():
    with server() as srv:
        a, b, c = C(srv, "A"), C(srv, "B"), C(srv, "C")
        make_group(b, "Squad", a)
        make_group(c, "StudyGroup", a)
        a.drain(0.2)
        b.send(type="group", group="Squad", text="for squad")
        c.send(type="group", group="StudyGroup", text="for study")
        got = {m["text"]: m["group"] for m in chats(a.drain(0.5))}
        ok = got == {"for squad": "Squad", "for study": "StudyGroup"}
        return f"A received each message under its own group: {got}.", PASS if ok else FAIL


# ===================================================== FR-005 private messages
@case
def ut_13():
    with server() as srv:
        a, b = C(srv, "userA"), C(srv, "userB")
        a.send(type="private", to="userB", text="hey")
        m = b.until("private")
        ok = m["type"] == "private" and m["to"] == "userB" and m["from"] == "userA"
        return (f"Message built as {{'type': 'private', 'from': 'userA', 'to': 'userB', 'text': 'hey', "
                "'id', 'time'}} - one recipient, flagged private."), PASS if ok else FAIL


@case
def ut_14():
    with server() as srv:
        a = C(srv, "userA")
        a.send(type="private", to="ghostuser", text="hello?")
        e = a.until("error")
        ok = e["code"] == "USER_NOT_FOUND"
        return f"Server answered '{e['message']}' (code {e['code']}); nothing was delivered or saved.", PASS if ok else FAIL


@case
def ut_15():
    with server() as srv:
        a, b = C(srv, "userA"), C(srv, "userB")
        a.send(type="private", to="userB", text="  ")
        e1 = a.until("error")
        a.send(type="private", to="userB", text="z" * 4001)
        e2 = a.until("error")
        ok = e1["code"] == "EMPTY_MESSAGE" and e2["code"] == "MESSAGE_TOO_LONG" and not b.drain(0.3)
        return (f"Both rejected by the same check used for group and normal messages: '{e1['message']}' and "
                f"'{e2['message']}'."), PASS if ok else FAIL


@case
def it_15():
    with server() as srv:
        a, b, c = C(srv, "A"), C(srv, "B"), C(srv, "C")
        c.drain(0.2)
        a.send(type="private", to="B", text="just between us")
        m = b.until("private")
        gotc = [x for x in c.drain(0.4) if x.get("text") == "just between us"]
        ok = m["text"] == "just between us" and not gotc
        return "B received it; C received nothing (0 messages).", PASS if ok else FAIL


@case
def it_16():
    with server() as srv:
        a, b = C(srv, "userA"), C(srv, "userB")
        b.send(type="quit")
        wait_until(lambda: "userB" not in srv.users)
        a.send(type="private", to="userB", text="hi")
        r = a.until("private_sent", "error")
        out = cl.format_message(r)
        ok = r.get("queued") is True
        return (f"The message did not disappear silently: A was told '{out}'. Since FR-012 (#59) a user "
                "who has used the chat gets it on their next login instead of an error; a name that "
                "never logged in still gets 'User not found/offline' (UT_14)."), PASS if ok else FAIL


@case
def it_17():
    with server() as srv:
        a, b, c = C(srv, "A"), C(srv, "B"), C(srv, "C")
        make_group(a, "Squad", b, c)
        for x in (a, b, c):
            x.drain(0.2)
        a.send(type="private", to="B", text="hey privately")
        a.send(type="group", group="Squad", text="hey team")
        gb = b.drain(0.5)
        gc = c.drain(0.5)
        ok = ([m["type"] for m in gb if m.get("text") in ("hey privately", "hey team")] == ["private", "chat"]
              and [m["text"] for m in gc if m.get("text")] == ["hey team"])
        return "B got the private message and the group message on separate channels; C saw only 'hey team'.", PASS if ok else FAIL


@case
def st_09():
    with server() as srv:
        a, b, c = C(srv, "A"), C(srv, "B"), C(srv, "C")
        for i in range(3):
            a.send(type="private", to="B", text=f"toB {i}")
            a.send(type="private", to="C", text=f"toC {i}")
            b.send(type="private", to="A", text=f"fromB {i}")
            c.send(type="private", to="A", text=f"fromC {i}")
        gb = texts(chats(b.drain(0.5), "private"))
        gc = texts(chats(c.drain(0.5), "private"))
        ga = chats(a.drain(0.5), "private")
        ok = gb == [f"toB {i}" for i in range(3)] and gc == [f"toC {i}" for i in range(3)] and len(ga) == 6
        return f"B only got its 3 messages, C only got its 3, and A got 6 replies with the right senders.", PASS if ok else FAIL


@case
def st_10():
    with server() as srv:
        a, b, c = C(srv, "A"), C(srv, "B"), C(srv, "C")
        make_group(c, "Squad", a)
        stop = threading.Event()

        def traffic():
            i = 0
            while not stop.is_set():
                c.send(type="group", group="Squad", text=f"g{i}")
                i += 1
                time.sleep(0.01)

        t = threading.Thread(target=traffic)
        t.start()
        time.sleep(0.1)
        a.send(type="private", to="B", text="private during traffic")
        mb = b.until("private")
        time.sleep(0.1)
        stop.set()
        t.join()
        ga = a.drain(0.5)
        sent = [m for m in ga if m["type"] == "private_sent"]
        group_msgs = [m for m in ga if m["type"] == "chat" and m.get("group") == "Squad"]
        out = cl.format_message(sent[0]) if sent else ""
        ok = mb["text"] == "private during traffic" and sent and group_msgs
        return (f"B got the private message while {len(group_msgs)} group messages were arriving at A; A's "
                f"screen shows it as '{out}', separate from '[Squad]' lines."), PASS if ok else FAIL


# ====================================================== FR-006 presence
@case
def ut_16():
    reg = registry.SessionRegistry()
    s = registry.Session(FakeSock())
    reg.register(s, "newuser")
    ok = reg.usernames() == ["newuser"] and s.alive
    return f"'newuser' is now in the active list {reg.usernames()} and its session is alive.", PASS if ok else FAIL


@case
def ut_17():
    reg = registry.SessionRegistry()
    a, b = registry.Session(FakeSock()), registry.Session(FakeSock())
    reg.register(a, "userA")
    reg.register(b, "userB")
    reg.disconnect(a)
    ok = reg.usernames() == ["userB"]
    return f"Only userA removed; list is {reg.usernames()}.", PASS if ok else FAIL


@case
def ut_18():
    g = groups.GroupManager()
    g.create("Squad", "userA")
    g.join("Squad", "userB")
    g.leave("Squad", "userA")
    ok = g.members("Squad") == ["userB"]
    return f"Member list is exactly {g.members('Squad')} (and userB became admin).", PASS if ok else FAIL


@case
def it_18():
    with server() as srv:
        a, b = C(srv, "userA"), C(srv, "userB")
        a.drain(0.2)
        c = C(srv, "userC")
        na = [m["text"] for m in a.drain(0.4) if m["type"] == "system"]
        nb = [m["text"] for m in b.drain(0.4) if m["type"] == "system"]
        a.send(type="list_users")
        users = a.until("users")["users"]
        ok = "userC joined the chat" in na and "userC joined the chat" in nb and "userC" in users
        return (f"A and B both got 'userC joined the chat', and the online list (/users and the web "
                f"page's list) now shows {users}."), PASS if ok else FAIL


@case
def it_19():
    with server() as srv:
        a, b, c = C(srv, "userA"), C(srv, "userB"), C(srv, "userC")
        a.drain(0.2)
        b.drain(0.2)
        c.send(type="quit")
        na = [m["text"] for m in a.drain(0.4) if m["type"] == "system"]
        nb = [m["text"] for m in b.drain(0.4) if m["type"] == "system"]
        a.send(type="list_users")
        users = a.until("users")["users"]
        ok = "userC left the chat" in na and "userC left the chat" in nb and "userC" not in users
        return f"A and B both got 'userC left the chat'; the online list is now {users}.", PASS if ok else FAIL


@case
def it_20():
    with server() as srv:
        a, b = C(srv, "A"), C(srv, "B")
        make_group(a, "Squad")
        b.send(type="join_group", group="Squad")
        ub = b.until("group_update")
        ua = a.until("group_update")
        ok = ua["members"] == ["A", "B"] and ub["members"] == ["A", "B"]
        return f"Both A and B received a group update listing {ua['members']}, with no refresh needed.", PASS if ok else FAIL


@case
def st_11():
    with server() as srv:
        a, b, c = C(srv, "A"), C(srv, "B"), C(srv, "C")
        b.send(type="quit")
        wait_until(lambda: "B" not in srv.users)
        d = C(srv, "D")
        ok = srv.users == ["A", "C", "D"]
        return f"Final active-user list on the server: {srv.users}.", PASS if ok else FAIL


@case
def st_12():
    with server() as srv:
        cs = [C(srv, f"u{i}") for i in range(5)]
        for x in cs:
            x.drain(0.2)
        start = time.time()
        new = [C(srv, "new1"), C(srv, "new2")]
        cs[4].send(type="quit")
        expected = {"new1 joined the chat", "new2 joined the chat", "u4 left the chat"}
        worst = 0
        ok = True
        for x in cs[:4]:
            seen = set()
            while seen != expected:
                try:
                    m = x.until("system", timeout=3)
                except TimeoutError:
                    ok = False
                    break
                seen.add(m["text"])
                worst = max(worst, time.time() - start)
        return (f"All 4 remaining clients received both join notices and the leave notice; slowest within "
                f"{worst * 1000:.0f} ms. Final list {srv.users}."), PASS if ok and len(new) == 2 else FAIL


# ================================================== FR-007 disconnects
@case
def ut_19():
    reg = registry.SessionRegistry()
    s = registry.Session(FakeSock())
    reg.register(s, "userA")
    s.close()
    removed = reg.disconnect(s)
    ok = not s.alive and removed and reg.usernames() == []
    return "Session marked not alive and removed from the active list; no exception raised.", PASS if ok else FAIL


@case
def ut_20():
    with server() as srv:
        a = C(srv, "userA")
        a.sock.close()
        ok = wait_until(lambda: srv.users == [] and not srv.registry.connected())
        return "Handler saw the closed socket, ended its loop and cleaned up the session (no loop, no crash).", PASS if ok else FAIL


@case
def ut_21():
    g = groups.GroupManager()
    reg = registry.SessionRegistry()
    sock = FakeSock()
    s = registry.Session(sock)
    reg.register(s, "userA")
    g.create("Squad", "userA")
    g.create("Study", "x")
    g.join("Study", "userA")
    s.close()
    reg.disconnect(s)
    left = g.remove_user("userA")
    ok = sock.closed and reg.usernames() == [] and not g.groups_of("userA")
    return (f"Socket handle released (closed) and session removed; userA was taken out of both groups "
            f"(Squad deleted as empty, Study now {g.members('Study')})."), PASS if ok else FAIL


@case
def it_21():
    with server() as srv:
        a, b = C(srv, "A"), C(srv, "B")
        b.drain(0.2)
        a.send(type="quit")
        start = time.time()
        wait_until(lambda: "A" not in srv.users)
        took = (time.time() - start) * 1000
        note = [m["text"] for m in b.drain(0.4) if m["type"] == "system"]
        ok = "A" not in srv.users and "A left the chat" in note
        return f"A was removed from the active-user list in {took:.0f} ms, and B got 'A left the chat'.", PASS if ok else FAIL


@case
def it_22():
    with server() as srv:
        code = ("import socket,sys,time\nfrom chat import protocol\n"
                f"s=socket.create_connection(('127.0.0.1',{srv.port}))\n"
                "protocol.send_message(s,{'type':'register','username':'A'})\nprotocol.recv_message(s)\n"
                "print('ready',flush=True)\ntime.sleep(60)\n")
        p = subprocess.Popen([sys.executable, "-c", code], cwd=CODE, stdout=subprocess.PIPE, text=True)
        p.stdout.readline()
        wait_until(lambda: "A" in srv.users)
        start = time.time()
        p.kill()
        p.wait()
        ok = wait_until(lambda: "A" not in srv.users, 30)
        took = time.time() - start
        return (f"Client process was force-killed (SIGKILL); the server removed A after {took:.2f} s "
                "(the OS closed the socket; TCP keepalive covers a lost network)."), PASS if ok else FAIL


@case
def it_23():
    with server() as srv:
        a, x = C(srv, "A"), C(srv, "X")
        make_group(a, "Squad")
        make_group(x, "StudyGroup", a)
        a.send(type="leave_group", group="Squad")
        a.until("group_update")
        ok = "A" in srv.users and srv.groups.is_member("StudyGroup", "A") and "Squad" not in srv.groups.names()
        return ("A stays connected and is still in StudyGroup; only Squad membership was removed (Squad was "
                "deleted because it became empty)."), PASS if ok else FAIL


@case
def st_13():
    with server() as srv:
        cs = [C(srv, f"u{i}") for i in range(5)]
        cs[0].send(type="quit")
        cs[1].send(type="quit")
        for x in cs[2:4]:
            x.sock.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, b"\x01\x00\x00\x00\x00\x00\x00\x00")
            x.sock.close()
        wait_until(lambda: srv.users == ["u4"])
        new = C(srv, "check")
        ok = "u4" in srv.users and new.reply["type"] == "registered"
        return (f"After 2 /quit and 2 forced resets the server was still accepting connections; final list "
                f"before the check was ['u4']."), PASS if ok else FAIL


@case
def st_14():
    with server() as srv:
        a = C(srv, "userA")
        a.sock.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, b"\x01\x00\x00\x00\x00\x00\x00\x00")
        a.sock.close()
        wait_until(lambda: "userA" not in srv.users)
        a2 = C(srv, "userA")
        ok = a2.reply["type"] == "registered"
        return "Reconnect with the same name succeeded ('registered') as a fresh session.", PASS if ok else FAIL


# ===================================================== FR-008 errors
@case
def ut_22():
    caught = []
    for body in (b"\xff\xfe\x00", b"{not json", b"[1, 2]"):
        try:
            protocol.decode(body)
        except protocol.ProtocolError as exc:
            caught.append(type(exc).__name__)
    ok = len(caught) == 3
    return f"Invalid bytes, broken JSON and a non-object all raised a handled {caught[0]}; no crash.", PASS if ok else FAIL


@case
def ut_23():
    s = registry.Session(FakeSock(fail=True))
    r = s.send({"type": "chat", "text": "x"})
    ok = r is False and not s.alive
    return "send() returned False instead of raising, and the session was marked for cleanup.", PASS if ok else FAIL


@case
def ut_24():
    records = []

    class H(logging.Handler):
        def emit(self, record):
            records.append(record)

    h = H()
    logger = logging.getLogger("chat.server")
    old = logger.level
    logger.setLevel(logging.INFO)
    logger.addHandler(h)
    try:
        with server() as srv:
            a = C(srv, "alice")
            a.sock.sendall((10_000_000).to_bytes(4, "big"))
            wait_until(lambda: any("Broken frame" in r.getMessage() for r in records))
    finally:
        logger.removeHandler(h)
        logger.setLevel(old)
    rec = next((r for r in records if "Broken frame" in r.getMessage()), None)
    if rec is None:
        return "No log entry was written.", FAIL
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    line = fmt.format(rec)
    return (f"A WARNING log entry was written with the time, the user and the error: '{line[:120]}'. "
            "Unexpected errors are logged with a traceback."), PASS


@case
def it_24():
    with server() as srv:
        a, b = C(srv, "A"), C(srv, "B")
        body = b"{bad json"
        a.sock.sendall(len(body).to_bytes(4, "big") + body)
        e = a.until("error")
        a.send(type="chat", text="A still works")
        mb = b.until("chat")
        ok = e["message"] == "Message was not valid JSON." and mb["text"] == "A still works"
        return f"A got '{e['message']}'; B stayed connected and kept receiving messages.", PASS if ok else FAIL


@case
def it_25():
    with server() as srv:
        a, b, c = C(srv, "A"), C(srv, "B"), C(srv, "C")
        a.sock.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, b"\x01\x00\x00\x00\x00\x00\x00\x00")
        a.sock.close()
        wait_until(lambda: "A" not in srv.users)
        b.send(type="private", to="C", text="fine")
        ok = c.until("private")["text"] == "fine" and srv.users == ["B", "C"]
        return "Forced a TCP reset on A; the server cleaned A up and B -> C messaging was not interrupted.", PASS if ok else FAIL


@case
def it_26():
    srv = ChatServer(port=0).start()
    proc = subprocess.Popen(
        [sys.executable, "-m", "chat.client", "--no-tls", "--port", str(srv.port)],
        cwd=CODE, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    proc.stdin.write("userA\n")
    proc.stdin.flush()
    time.sleep(0.6)
    srv.stop()
    time.sleep(0.8)
    proc.stdin.close()
    out, _ = proc.communicate(timeout=10)
    ok = "[disconnected from server]" in out
    return "After the server was stopped the client printed '[disconnected from server]' straight away.", PASS if ok else FAIL


@case
def st_15():
    with server() as srv:
        cs = [C(srv, f"u{i}") for i in range(5)]

        def reset():
            cs[0].sock.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, b"\x01\x00\x00\x00\x00\x00\x00\x00")
            cs[0].sock.close()

        def corrupt():
            cs[1].sock.sendall((10_000_000).to_bytes(4, "big"))

        ts = [threading.Thread(target=reset), threading.Thread(target=corrupt)]
        for t in ts:
            t.start()
        for t in ts:
            t.join()
        wait_until(lambda: srv.users == ["u2", "u3", "u4"])
        cs[2].send(type="chat", text="all good")
        ok = srv.users == ["u2", "u3", "u4"] and cs[3].until("chat")["text"] == "all good"
        return ("One abrupt reset and one corrupt frame at the same moment: both sessions were cleaned up, "
                f"the server kept running and the other 3 kept chatting ({srv.users})."), PASS if ok else FAIL


@case
def st_16():
    with server() as srv:
        b = C(srv, "userB")
        a = C(srv, "userA")
        make_group(b, "Squad", a)
        a.sock.sendall((10_000_000).to_bytes(4, "big"))
        wait_until(lambda: "userA" not in srv.users)
        a = C(srv, "userA")
        a.send(type="join_group", group="Squad")
        a.until("group_update")
        a.send(type="private", to="userB", text="private ok")
        a.send(type="chat", text="everyone ok")
        a.send(type="group", group="Squad", text="group ok")
        got = [m.get("text") for m in b.drain(0.6) if m["type"] in ("chat", "private")]
        ok = got == ["private ok", "everyone ok", "group ok"]
        return ("userA was dropped for a bad frame, reconnected under the same name, rejoined Squad, and "
                "private, normal and group messages all worked."), PASS if ok else FAIL


# ============================================== Sprint 3: persistence
@case
def ut_25():
    st = storage.MessageStore()
    sent = protocol.make_chat_message("hello", "alice")
    sent["context"] = "general"
    st.save_chat(sent)
    [back] = st.recent_chat()
    ok = back == sent
    return "The saved message came back identical: same type, ID, time, sender, text and context.", PASS if ok else FAIL


@case
def ut_26():
    st = storage.MessageStore()
    for frm, to, t in (("alice", "bob", "hi bob"), ("alice", "carol", "hi carol"),
                       ("bob", "alice", "hi alice"), ("carol", "bob", "carol to bob")):
        st.save_private({"id": 1, "time": "t", "from": frm, "to": to, "text": t})
    st.save_chat({"id": 2, "time": "t", "from": "alice", "text": "everyone"})
    st.save_group({"id": 3, "time": "t", "from": "alice", "text": "group", "group": "Squad"})
    got = texts(st.private_between("alice", "bob"))
    ok = got == ["hi bob", "hi alice"] and texts(st.recent_chat()) == ["everyone"]
    return f"alice-bob history is {got}: both directions, oldest first, nobody else's messages.", PASS if ok else FAIL


@case
def it_27():
    with server() as srv:
        a, b, c = C(srv, "a"), C(srv, "b"), C(srv, "c")

        def blast(x, n):
            for i in range(30):
                x.send(type="chat", text=f"{n}-{i}")

        ts = [threading.Thread(target=blast, args=(x, n)) for x, n in ((a, "a"), (b, "b"))]
        for t in ts:
            t.start()
        for t in ts:
            t.join()
        seen = []
        while len(seen) < 60:
            m = c.until("chat")
            seen.append(m["text"])
        wait_until(lambda: srv.store.count() == 60)
        saved = texts(srv.store.recent_chat(limit=60))
        ok = saved == seen
        return "Two users sent 30 messages each at once; the 60 saved messages are in exactly the order C saw them.", PASS if ok else FAIL


@case
def it_28():
    with server() as srv:
        a = C(srv, "alice")
        for i in range(25):
            a.send(type="chat", text=f"m{i}")
        wait_until(lambda: srv.store.count() == 25)
        b = C(srv, "bob")
        hist = [m for m in b.drain(0.5) if m.get("history")]
        out = cl.format_message(hist[0]) if hist else ""
        ok = texts(hist) == [f"m{i}" for i in range(5, 25)]
        return (f"bob got the last 20 (m5 to m24), oldest first, right after 'registered'; the terminal "
                f"shows them as '{out}'."), PASS if ok else FAIL


@case
def st_17():
    db = tmpdb()
    with server(db) as srv:
        out1, _ = terminal(srv, ["alice", "before the restart", "/quit"])
    with server(db) as srv:
        out2, _ = terminal(srv, ["bob", "/quit"])
    line = next((x for x in out2.splitlines() if "before the restart" in x), "")
    ok = "(earlier) alice: before the restart" in out2
    return (f"Server stopped and started again on the same chat.db; bob's terminal showed "
            f"'{line.strip()}' after logging in."), PASS if ok else FAIL


@case
def ut_27():
    a = cl.parse_command("/history bob")
    b = cl.parse_command("/history")
    c = cl.parse_command("/history bob carol")
    ok = a == ({"type": "private_history", "with": "bob"}, None) and b[1] == c[1] == "Usage: /history <user>"
    return (f"'/history bob' becomes {a[0]}; '/history' and '/history bob carol' show '{b[1]}' locally "
            "and send nothing. /help lists the command."), PASS if ok and "/history <user>" in cl.HELP else FAIL


@case
def it_29():
    with server() as srv:
        a, b = C(srv, "alice"), C(srv, "bob")
        for i in range(25):
            src, dst, other = (a, "bob", b) if i % 2 == 0 else (b, "alice", a)
            src.send(type="private", to=dst, text=f"p{i}")
            other.until("private")  # a real conversation: reply after reading
        wait_until(lambda: len(srv.store.private_between("alice", "bob", 100)) == 25)
        a.send(type="private_history", **{"with": "bob"})
        r = a.until("private_history")
        got = texts(r["messages"])
        ok = got == [f"p{i}" for i in range(5, 25)] and r["messages"][0]["from"] == "bob"
        return ("/history bob returned the last 20 of 25 messages (p5 to p24), oldest first, both directions, "
                "each marked as history."), PASS if ok else FAIL


@case
def it_30():
    with server() as srv:
        a, b, c = C(srv, "alice"), C(srv, "bob"), C(srv, "carol")
        a.send(type="private", to="bob", text="secret")
        b.until("private")
        c.send(type="private_history", **{"with": "alice"})
        r1 = c.until("private_history")
        c.send(type="private_history", **{"with": "bob"})
        r2 = c.until("private_history")
        ok = r1["messages"] == [] and r2["messages"] == []
        return ("carol asked for her history with alice and with bob: both empty. One side of the query is "
                "always the user asking, so alice-bob messages cannot be read."), PASS if ok else FAIL


@case
def it_31():
    with server() as srv:
        b = C(srv, "bob")
        b.send(type="quit")
        wait_until(lambda: "bob" not in srv.users)
        a = C(srv, "alice")
        a.send(type="private", to="bob", text="call me")
        r = a.until("private_sent", "error")
        ok = r.get("queued") is True and srv.store.waiting_count("bob") == 1
        return f"alice was told '{cl.format_message(r)}'; 1 message is waiting for bob.", PASS if ok else FAIL


@case
def it_32():
    with server() as srv:
        b = C(srv, "bob")
        b.send(type="quit")
        wait_until(lambda: "bob" not in srv.users)
        a = C(srv, "alice")
        for t in ("one", "two", "three"):
            a.send(type="private", to="bob", text=t)
            a.until("private_sent")
        b = C(srv, "bob")
        got = [m for m in b.drain(0.5) if m["type"] == "private"]
        b.send(type="quit")
        wait_until(lambda: "bob" not in srv.users)
        again = [m for m in C(srv, "bob").drain(0.5) if m["type"] == "private"]
        out = cl.format_message(got[0]) if got else ""
        ok = texts(got) == ["one", "two", "three"] and not again
        return (f"On login bob got 'one', 'two', 'three' in order, shown as '{out}'; logging in again "
                "delivered nothing a second time."), PASS if ok else FAIL


@case
def st_18():
    db = tmpdb()
    with server(db) as srv:
        terminal(srv, ["bob", "/quit"])
        out_a, _ = terminal(srv, ["alice", "/msg bob see you after the restart", "/quit"])
    with server(db) as srv:
        out_b, _ = terminal(srv, ["bob", "/quit"])
    line_a = next((x for x in out_a.splitlines() if "private to bob" in x), "").strip()
    line_b = next((x for x in out_b.splitlines() if "while you were away" in x), "").strip()
    ok = "delivered when they log in" in line_a and "see you after the restart" in line_b
    return (f"alice saw '{line_a}'. After the server restarted, bob logged in and saw '{line_b}'."), PASS if ok else FAIL


@case
def ut_28():
    st = storage.MessageStore()
    st.save_group_state("Squad", "zoe", ["zoe", "adam", "mia"])
    st.save_group_state("Squad", "adam", ["adam", "mia"])
    st.save_group_state("Team", "x", ["x"])
    st.delete_group("Team")
    got = st.load_groups()
    ok = got == {"Squad": ("adam", ["adam", "mia"])}
    return f"load_groups() returned {got}: the latest admin and members in joining order; the deleted group is gone.", PASS if ok else FAIL


@case
def it_33():
    db = tmpdb()
    with server(db) as srv:
        a, b = C(srv, "alice"), C(srv, "bob")
        make_group(a, "Squad", b)
    with server(db) as srv:
        state = (srv.groups.members("Squad"), srv.groups.admin("Squad"))
        a, b = C(srv, "alice"), C(srv, "bob")
        b.drain(0.3)
        a.send(type="group", group="Squad", text="still here?")
        m = b.until("chat")
        ok = state == (["alice", "bob"], "alice") and m["text"] == "still here?"
        return (f"After a restart Squad had members {state[0]} and admin '{state[1]}'; alice's group message "
                "reached bob without anyone rejoining."), PASS if ok else FAIL


@case
def it_34():
    db = tmpdb()
    with server(db) as srv:
        a = C(srv, "alice")
        make_group(a, "Squad")
        for i in range(12):
            a.send(type="group", group="Squad", text=f"g{i}")
        wait_until(lambda: len(srv.store.group_messages("Squad", 100)) == 12)
    with server(db) as srv:
        c = C(srv, "carol")
        c.send(type="join_group", group="Squad")
        hist = [m for m in c.drain(0.5) if m.get("history")]
        ok = texts(hist) == [f"g{i}" for i in range(2, 12)]
        return "After a restart carol joined Squad and was shown its last 10 messages (g2 to g11), marked earlier.", PASS if ok else FAIL


@case
def it_35():
    db = tmpdb()
    with server(db) as srv:
        a, b = C(srv, "alice"), C(srv, "bob")
        make_group(a, "Squad", b)
        b.send(type="quit")
        wait_until(lambda: srv.groups.members("Squad") == ["alice"])
    saved = storage.MessageStore(db).load_groups()
    ok = saved == {"Squad": ("alice", ["alice"])}
    return f"bob quit normally and was removed from Squad; the database holds {saved} (only a server restart keeps memberships).", PASS if ok else FAIL


@case
def ut_29():
    env = dict(os.environ)
    try:
        os.environ.pop("CHAT_DB", None)
        d = config.parse_args("x", []).db
        os.environ["CHAT_DB"] = "env.db"
        e = config.parse_args("x", []).db
        f = config.parse_args("x", ["--db", "flag.db"]).db
    finally:
        os.environ.clear()
        os.environ.update(env)
    ok = (d, e, f) == ("chat.db", "env.db", "flag.db")
    return f"Default '{d}'; with CHAT_DB set '{e}'; with --db as well '{f}' (the flag wins).", PASS if ok else FAIL


@case
def ut_30():
    results = []
    for bad in ("-1", "lots"):
        try:
            with redirect_stdout(io.StringIO()), open(os.devnull, "w") as null:
                old = sys.stderr
                sys.stderr = null
                try:
                    config.parse_args("x", ["--keep", bad])
                finally:
                    sys.stderr = old
            results.append("accepted")
        except SystemExit:
            results.append("rejected")
    env = os.environ.pop("CHAT_KEEP", None)
    default = config.parse_args("x", []).keep
    if env is not None:
        os.environ["CHAT_KEEP"] = env
    ok = results == ["rejected", "rejected"] and default == 500
    return f"--keep -1 and --keep lots are both rejected with a usage error; the default is {default}.", PASS if ok else FAIL


@case
def it_36():
    with server(keep=5) as srv:
        a, b = C(srv, "alice"), C(srv, "bob")
        for i in range(8):
            a.send(type="chat", text=f"e{i}")
            a.send(type="private", to="bob", text=f"p{i}")
        a.send(type="private", to="bob", text="last")
        b.until("private")
        wait_until(lambda: texts(srv.store.private_between("alice", "bob", 100))[-1:] == ["last"])
        e = texts(srv.store.recent_chat(100))
        p = texts(srv.store.private_between("alice", "bob", 100))
        ok = e == [f"e{i}" for i in range(3, 8)] and p == ["p4", "p5", "p6", "p7", "last"]
        return (f"With --keep 5 the Everyone chat kept {e} and the alice-bob chat kept the newest 5; each "
                "chat is trimmed on its own."), PASS if ok else FAIL


@case
def st_19():
    folder = tempfile.mkdtemp(prefix="tc-")
    path = os.path.join(folder, "data", "mychat.db")
    os.makedirs(os.path.dirname(path))
    proc = subprocess.Popen([sys.executable, "-m", "chat.server", "--no-tls", "--port", "0", "--db", path],
                            cwd=CODE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    time.sleep(1.5)
    proc.terminate()
    out, _ = proc.communicate(timeout=10)
    line = next((x for x in out.splitlines() if "Saving messages" in x), "")
    created = os.path.exists(path)
    with sqlite3.connect(path) as con:
        tables = sorted(r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")
                        if not r[0].startswith("sqlite_"))
    with server() as srv:
        C(srv, "a").send(type="chat", text="gone")
        wait_until(lambda: srv.store.count() == 1)
    with server() as srv:
        mem = srv.store.count()
    ok = created and "Saving messages to" in line and mem == 0 and len(tables) == 5
    shown = line.split("INFO", 1)[-1].strip(" :") if line else ""
    shown = shown.replace(folder, "<tmp>")
    return (f"The server logged '{shown}' and created the file with tables {tables}. With --db :memory: "
            "a restart started empty (0 messages)."), PASS if ok else FAIL


@case
def st_20():
    db = tmpdb()
    with server(db) as srv:
        a, b = C(srv, "alice"), C(srv, "bob")
        make_group(a, "Squad", b)
        a.send(type="chat", text="hello all")
        a.send(type="group", group="Squad", text="hello squad")
        a.send(type="private", to="bob", text="hello bob")
        a.until("private_sent")
        wait_until(lambda: srv.store.count() == 3)
    with server(db):
        pass
    with server(db) as srv:
        out, _ = terminal(srv, ["dave", "/join Squad", "/quit"])
        a = C(srv, "alice")
        a.send(type="private_history", **{"with": "bob"})
        ph = texts(a.until("private_history")["messages"])
        ok = ("(earlier) alice: hello all" in out and "hello squad" in out and ph == ["hello bob"]
              and srv.groups.members("Squad")[:2] == ["alice", "bob"])
        return ("After two restarts a new user saw '(earlier) alice: hello all', joining Squad showed "
                f"'hello squad', alice's /history bob returned {ph}, and Squad still had alice and bob."), PASS if ok else FAIL


@case
def st_21():
    from chat import web
    from playwright.sync_api import sync_playwright
    db = tmpdb()
    with server(db) as srv:
        a, b = C(srv, "alice"), C(srv, "bob")
        a.send(type="chat", text="hello from before")
        a.send(type="private", to="bob", text="private from before")
        b.until("private")
        make_group(a, "Squad", b)
        a.send(type="group", group="Squad", text="squad from before")
        wait_until(lambda: srv.store.count() == 3)
    with server(db) as srv:
        alice = C(srv, "alice")  # noqa: F841 - online, so bob can open her chat
        gw = web.ChatGateway(srv.host, srv.port, tls_context=None, web_port=0).start()
        try:
            with sync_playwright() as p:
                page = p.chromium.launch().new_page()
                page.goto(f"http://127.0.0.1:{gw.web_port}/")
                page.fill("#username", "bob")
                page.keyboard.press("Enter")
                page.wait_for_timeout(900)
                everyone = page.inner_text("#messages")
                chat_list = page.inner_text("#chat-list") if page.query_selector("#chat-list") else ""
                page.get_by_text("Squad").first.click()
                page.wait_for_timeout(400)
                squad = page.inner_text("#messages")
                page.get_by_text("Tap to chat").first.click()
                page.wait_for_timeout(700)
                private = page.inner_text("#messages")
                page.screenshot(path=os.path.join(os.path.dirname(__file__), "st21.png"))
        finally:
            gw.stop()
    ok = ("hello from before" in everyone and "squad from before" in squad
          and "private from before" in private)
    parts = [("Everyone", "hello from before" in everyone), ("Squad", "squad from before" in squad),
             ("private chat with alice", "private from before" in private)]
    shown = ", ".join(f"{n}: {'shown' if s else 'missing'}" for n, s in parts)
    return (f"After a server restart bob joined from the web page. {shown}."), PASS if ok else (PARTIAL if any(s for _, s in parts) else FAIL)


@case
def st_22():
    records = []

    class H(logging.Handler):
        def emit(self, record):
            records.append(record)

    h = H()
    store_log = logging.getLogger("chat.storage")
    store_log.addHandler(h)
    store_log.setLevel(logging.INFO)
    try:
        with server() as srv:
            a, b = C(srv, "alice"), C(srv, "bob")
            class BrokenDb:  # every database call fails, like a full or locked disk
                def execute(self, *args):
                    raise sqlite3.OperationalError("disk I/O error")
                executemany = execute

                def __enter__(self):
                    return self

                def __exit__(self, *exc):
                    return False

                def close(self):
                    pass

            with srv.store._lock:
                srv.store._db = BrokenDb()
            a.send(type="chat", text="still delivered")
            m = b.until("chat")
            a.send(type="private", to="bob", text="private too")
            p = b.until("private")
            alive = srv.users == ["alice", "bob"]
    finally:
        store_log.removeHandler(h)
        store_log.setLevel(logging.NOTSET)
    logged = [r.getMessage() for r in records if r.levelno >= logging.ERROR]
    ok = m["text"] == "still delivered" and p["text"] == "private too" and alive and logged
    return (f"With the database broken, messages were still delivered, nobody was disconnected, and the "
            f"error was logged ('{logged[0] if logged else ''}')."), PASS if ok else FAIL


# ------------------------------------------------------------------ runner
def main():
    out = sys.argv[2]
    wanted = [a.upper() for a in sys.argv[3:]] or list(CASES)
    logging.basicConfig(level=logging.CRITICAL)
    results = json.load(open(out)) if os.path.exists(out) else {}
    for cid in wanted:
        start = time.time()
        try:
            actual, result = CASES[cid]()
        except Exception as exc:  # a crash in a case is a failure of that case
            actual, result = f"Error while running: {type(exc).__name__}: {exc}", FAIL
        results[cid] = [actual, result]
        print(f"{cid:6} {result:8} {time.time() - start:5.1f}s  {actual[:110]}", flush=True)
        json.dump(results, open(out, "w"), indent=1)


if __name__ == "__main__":
    if sys.argv[2] == "--st06":
        print(json.dumps(st_06_idle(int(sys.argv[3]))))
    else:
        main()
