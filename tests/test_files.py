"""Sending images, videos, audio and documents (chat/files.py)."""

import base64
import os
import socket
import threading

import pytest

from chat import client, files, protocol
from chat.server import ChatServer

from conftest import WireClient

MB = 1024 * 1024


def upload(sender, name, data, token="u1", chunk=files.CHUNK_BYTES, **target):
    """Send a file the way the clients do: start, pieces, end."""
    start = {"type": "file_start", "upload": token, "name": name, "size": len(data),
             "context": "general", **target}
    sender.send(start)
    for at in range(0, len(data), chunk):
        sender.send({"type": "file_chunk", "upload": token,
                     "data": base64.b64encode(data[at:at + chunk]).decode()})
    sender.send({"type": "file_end", "upload": token})


def download(receiver, file_id):
    """Ask for a file and put the pieces back together."""
    receiver.send({"type": "file_get", "id": file_id})
    first = receiver.recv_until_any("file_data_start", "error")
    if first["type"] == "error":
        return first
    data = b""
    while True:
        message = receiver.recv()
        if message["type"] == "file_data":
            data += base64.b64decode(message["data"])
        elif message["type"] == "file_data_end":
            return data


def recv_until_any(self, *types):
    while True:
        message = self.recv()
        if message is None or message["type"] in types:
            return message


WireClient.recv_until_any = recv_until_any


def drain(c, wait=0.4):
    got = []
    c.sock.settimeout(wait)
    try:
        while True:
            message = c.recv()
            if message is None:
                break
            got.append(message)
    except socket.timeout:
        pass
    c.sock.settimeout(3.0)
    return got


def make_group(admin, name, *members):
    admin.send({"type": "create_group", "group": name})
    admin.recv_until("group_update")
    for m in members:
        m.send({"type": "join_group", "group": name})
        m.recv_until("group_update")


DATA = os.urandom(100_000)  # more than 3 pieces


# --------------------------------------------------------------- the rules
@pytest.mark.parametrize("name, kind", [
    ("cat.png", "image"), ("Photo.JPG", "image"), ("a.webp", "image"),
    ("notes.pdf", "document"), ("plan.docx", "document"), ("data.csv", "document"),
    ("clip.mp4", "video"), ("clip.webm", "video"), ("clip.MOV", "video"),
    ("song.mp3", "audio"), ("voice.m4a", "audio"), ("note.WAV", "audio"), ("a.ogg", "audio"),
    ("a.aac", "audio"),
])
def test_allowed_types(name, kind):
    assert files.check(name, 1000)[0] == kind


@pytest.mark.parametrize("name", ["virus.exe", "script.sh", "page.html", "archive.zip",
                                  "noextension"])
def test_other_types_are_refused(name):
    with pytest.raises(files.FileRejected) as err:
        files.check(name, 1000)
    assert err.value.code == "FILE_TYPE_NOT_ALLOWED"


@pytest.mark.parametrize("name, limit", [("a.png", 5), ("a.pdf", 10), ("a.mp4", 25), ("a.mp3", 10)])
def test_size_limits(name, limit):
    assert files.check(name, limit * MB)  # exactly the limit is fine
    with pytest.raises(files.FileRejected) as err:
        files.check(name, limit * MB + 1)
    assert err.value.code == "FILE_TOO_LARGE"
    assert f"{limit} MB" in err.value.message


def test_limit_message_names_the_kind():
    with pytest.raises(files.FileRejected) as err:
        files.check("song.mp3", 11 * MB)
    assert err.value.message.startswith("Audio files are limited to 10 MB")


@pytest.mark.parametrize("size", [0, -5, "10", None, True])
def test_bad_sizes_are_refused(size):
    with pytest.raises(files.FileRejected):
        files.check("a.png", size)


def test_names_lose_folders_and_odd_characters():
    assert files.safe_name("../../etc/passwd.png") == "passwd.png"
    assert files.safe_name("C:\\Users\\me\\cat.png") == "cat.png"
    assert files.safe_name("my <script>.pdf") == "my _script_.pdf"
    assert files.safe_name(".hidden.png") == "hidden.png"
    assert len(files.safe_name("x" * 300 + ".pdf")) == files.NAME_LENGTH


def test_every_piece_fits_in_one_frame():
    piece = next(files.chunks(os.urandom(files.CHUNK_BYTES)))
    message = {"type": "file_chunk", "upload": "x" * 40, "data": piece}
    assert len(protocol.encode(message)) < protocol.MAX_FRAME_BYTES


def test_describe():
    assert files.describe("image", "cat.png", 120 * 1024) == "[image] cat.png (120 KB)"
    assert files.human_size(3 * MB) == "3.0 MB"


# ------------------------------------------------------------- the server
def test_file_to_everyone(server, connect):
    alice, bob = connect("alice"), connect("bob")
    upload(alice, "cat.png", DATA)
    sent = alice.recv_until("file_sent")
    got = bob.recv_until("file")
    assert sent["upload"] == "u1" and sent["file"] == got["file"]
    assert got["from"] == "alice" and got["context"] == "general"
    assert got["file"]["name"] == "cat.png" and got["file"]["kind"] == "image"
    assert got["file"]["size"] == len(DATA)
    assert download(bob, got["file"]["id"]) == DATA


def test_file_ready_is_sent_before_the_pieces(server, connect):
    alice = connect("alice")
    alice.send({"type": "file_start", "upload": "u1", "name": "a.png", "size": 10})
    assert alice.recv()["type"] == "file_ready"


def test_private_file_reaches_only_the_recipient(server, connect):
    alice, bob, carol = connect("alice"), connect("bob"), connect("carol")
    drain(carol, 0.2)
    upload(alice, "notes.pdf", DATA, context="private", to="bob")
    got = bob.recv_until("file")
    assert got["context"] == "private" and got["to"] == "bob"
    assert not [m for m in drain(carol) if m["type"] == "file"]
    assert download(carol, got["file"]["id"])["code"] == "FILE_NOT_FOUND"
    assert download(bob, got["file"]["id"]) == DATA
    assert download(alice, got["file"]["id"]) == DATA  # the sender can too


def test_audio_file_to_a_group(server, connect):
    alice, bob = connect("alice"), connect("bob")
    make_group(alice, "Squad", bob)
    voice = bytes(range(256)) * 300  # about 75 KB, several pieces
    upload(alice, "voice note.m4a", voice, context="group", group="Squad")
    got = bob.recv_until("file")
    assert got["file"]["kind"] == "audio" and got["file"]["name"] == "voice note.m4a"
    assert got["text"].startswith("[audio] voice note.m4a")
    assert download(bob, got["file"]["id"]) == voice


def test_private_file_to_offline_user_is_refused(server, connect):
    alice = connect("alice")
    upload(alice, "notes.pdf", DATA, context="private", to="nobody")
    error = alice.recv_until("error")
    assert error["code"] == "USER_NOT_FOUND" and error["upload"] == "u1"
    assert not [m for m in drain(alice) if m["type"] == "file_sent"]


def test_group_file_reaches_members_only(server, connect):
    alice, bob, carol = connect("alice"), connect("bob"), connect("carol")
    make_group(alice, "Squad", bob)
    drain(carol, 0.2)
    upload(alice, "clip.mp4", DATA, context="group", group="Squad")
    got = bob.recv_until("file")
    assert got["group"] == "Squad" and got["context"] == "group"
    assert not [m for m in drain(carol) if m["type"] == "file"]
    assert download(carol, got["file"]["id"])["code"] == "FILE_NOT_FOUND"
    assert download(bob, got["file"]["id"]) == DATA


def test_non_member_cannot_send_to_a_group(server, connect):
    alice, carol = connect("alice"), connect("carol")
    make_group(alice, "Squad")
    upload(carol, "a.png", DATA, context="group", group="Squad")
    assert carol.recv_until("error")["code"] == "NOT_A_MEMBER"


def test_too_large_is_refused_before_any_data(server, connect):
    alice, bob = connect("alice"), connect("bob")
    alice.send({"type": "file_start", "upload": "u1", "name": "big.png", "size": 6 * MB})
    error = alice.recv_until("error")
    assert error["code"] == "FILE_TOO_LARGE" and "5 MB" in error["message"]
    alice.send({"type": "file_chunk", "upload": "u1", "data": base64.b64encode(b"x").decode()})
    alice.send({"type": "file_end", "upload": "u1"})
    assert not [m for m in drain(bob) if m["type"] == "file"]
    assert not [m for m in drain(alice) if m["type"] in ("file_sent", "error")]


def test_wrong_type_is_refused(server, connect):
    alice = connect("alice")
    upload(alice, "tool.exe", DATA)
    assert alice.recv_until("error")["code"] == "FILE_TYPE_NOT_ALLOWED"


def test_more_data_than_announced_is_refused(server, connect):
    alice, bob = connect("alice"), connect("bob")
    alice.send({"type": "file_start", "upload": "u1", "name": "a.png", "size": 10})
    alice.send({"type": "file_chunk", "upload": "u1", "data": base64.b64encode(b"x" * 11).decode()})
    assert alice.recv_until("error")["code"] == "FILE_TOO_LARGE"
    alice.send({"type": "file_end", "upload": "u1"})
    assert not [m for m in drain(bob) if m["type"] == "file"]


def test_incomplete_file_is_refused(server, connect):
    alice, bob = connect("alice"), connect("bob")
    alice.send({"type": "file_start", "upload": "u1", "name": "a.png", "size": 100})
    alice.send({"type": "file_chunk", "upload": "u1", "data": base64.b64encode(b"x" * 50).decode()})
    alice.send({"type": "file_end", "upload": "u1"})
    assert alice.recv_until("error")["code"] == "FILE_INCOMPLETE"
    assert not [m for m in drain(bob) if m["type"] == "file"]


def test_bad_base64_is_refused(server, connect):
    alice = connect("alice")
    alice.send({"type": "file_start", "upload": "u1", "name": "a.png", "size": 10})
    alice.send({"type": "file_chunk", "upload": "u1", "data": "not base64!!"})
    assert alice.recv_until("error")["code"] == "BAD_UPLOAD"


def test_at_most_two_uploads_at_once(server, connect):
    alice = connect("alice")
    for token in ("a", "b", "c"):
        alice.send({"type": "file_start", "upload": token, "name": "a.png", "size": 10})
    replies = [alice.recv_until_any("file_ready", "error") for _ in range(3)]
    assert [r["type"] for r in replies] == ["file_ready", "file_ready", "error"]
    assert replies[2]["code"] == "TOO_MANY_UPLOADS"


@pytest.mark.parametrize("file_id", ["0" * 32, "../../etc/passwd", "", None])
def test_unknown_or_bad_file_ids(server, connect, file_id):
    alice = connect("alice")
    alice.send({"type": "file_get", "id": file_id})
    assert alice.recv_until("error")["code"] == "FILE_NOT_FOUND"


def test_must_be_registered(server, connect):
    stranger = connect()
    upload(stranger, "a.png", DATA)
    assert stranger.recv_until("error")["code"] == "NOT_REGISTERED"


def test_unfinished_upload_is_thrown_away_on_disconnect(server, connect):
    alice = connect("alice")
    alice.send({"type": "file_start", "upload": "u1", "name": "a.png", "size": 1000})
    alice.recv_until("file_ready")
    alice.send({"type": "file_chunk", "upload": "u1", "data": base64.b64encode(b"x" * 10).decode()})
    alice.close()
    deadline = threading.Event()
    for _ in range(50):
        if not os.listdir(server.files.folder):
            break
        deadline.wait(0.05)
    assert os.listdir(server.files.folder) == []


def test_files_are_stored_under_a_random_name(server, connect):
    alice = connect("alice")
    upload(alice, "../../escape.png", DATA)
    sent = alice.recv_until("file_sent")
    assert sent["file"]["name"] == "escape.png"
    assert os.listdir(server.files.folder) == [sent["file"]["id"]]


def test_new_users_see_earlier_files_in_the_history(server, connect):
    alice = connect("alice")
    upload(alice, "cat.png", DATA)
    alice.recv_until("file_sent")
    carol = connect("carol")
    earlier = [m for m in drain(carol) if m.get("history")]
    assert [m["type"] for m in earlier] == ["file"]
    assert earlier[0]["file"]["name"] == "cat.png"
    assert download(carol, earlier[0]["file"]["id"]) == DATA


def test_files_survive_a_server_restart(tmp_path):
    db = str(tmp_path / "chat.db")
    srv = ChatServer(port=0, db_path=db).start()
    alice = WireClient(srv)
    alice.send({"type": "register", "username": "alice"})
    alice.recv_until("registered")
    upload(alice, "notes.pdf", DATA)
    file_id = alice.recv_until("file_sent")["file"]["id"]
    srv.stop()
    assert os.path.isdir(str(tmp_path / "chat_files"))

    srv = ChatServer(port=0, db_path=db).start()
    try:
        bob = WireClient(srv)
        bob.send({"type": "register", "username": "bob"})
        bob.recv_until("registered")
        earlier = [m for m in drain(bob) if m.get("history")]
        assert earlier[0]["file"]["id"] == file_id
        assert download(bob, file_id) == DATA
    finally:
        srv.stop()


def test_temporary_files_folder_is_removed_on_stop():
    srv = ChatServer(port=0).start()
    folder = srv.files.folder
    srv.stop()
    assert not os.path.exists(folder)


# ------------------------------------------------------- terminal client
def test_file_commands_are_parsed():
    assert client.parse_command("/file ~/Pictures/cat.png")[0] == {
        "type": "_send_file", "context": "general", "path": "~/Pictures/cat.png"}
    assert client.parse_command("/pfile bob my notes.pdf")[0] == {
        "type": "_send_file", "context": "private", "to": "bob", "path": "my notes.pdf"}
    assert client.parse_command("/gfile Squad clip.mp4")[0]["group"] == "Squad"
    assert client.parse_command("/get abc")[0] == {"type": "file_get", "id": "abc"}
    assert client.parse_command("/file")[1] == "Usage: /file <path>"
    assert client.parse_command("/pfile bob")[1] == "Usage: /pfile <user> <path>"
    assert client.parse_command("/get")[1] == "Usage: /get <id>"
    for command in ("/file", "/pfile", "/gfile", "/get"):
        assert command in client.HELP


def test_file_messages_are_shown():
    info = {"id": "f" * 32, "kind": "image", "name": "cat.png", "size": 1000}
    message = {"type": "file", "from": "alice", "file": info, "context": "group",
               "group": "Squad", "text": "[image] cat.png (1000 B)"}
    assert client.format_message(message) == \
        f"[Squad] alice sent [image] cat.png (1000 B) - /get {'f' * 32}"
    sent = {**message, "type": "file_sent", "context": "private", "to": "bob"}
    assert client.format_message(sent) == "* You sent [image] cat.png (1000 B) to bob"
    assert client.format_message({"type": "file_data", "id": "x", "data": "AAAA"}) == ""


def test_client_sends_and_downloads_a_file(server, connect, tmp_path):
    original = tmp_path / "photo.png"
    original.write_bytes(DATA)
    bob = connect("bob")
    alice = WireClient(server)
    alice.send({"type": "register", "username": "alice"})
    alice.recv_until("registered")
    shown = client.send_file(alice.sock, {"type": "_send_file", "context": "general",
                                          "path": str(original)})
    assert shown.startswith("* Sending [image] photo.png")
    file_id = bob.recv_until("file")["file"]["id"]

    downloads = client.Downloads(str(tmp_path / "downloads"))
    bob.send({"type": "file_get", "id": file_id})
    lines = []
    while True:
        message = bob.recv()
        text = downloads.handle(message)
        if text:
            lines.append(text)
        if message["type"] == "file_data_end":
            break
    saved = tmp_path / "downloads" / "photo.png"
    assert saved.read_bytes() == DATA
    assert lines == ["* Downloading photo.png...", f"* Saved {saved}"]


def test_client_checks_files_before_sending(tmp_path):
    big = tmp_path / "big.png"
    big.write_bytes(b"x" * (5 * MB + 1))
    assert "limited to 5 MB" in client.send_file(None, {"context": "general", "path": str(big)})
    assert "No such file" in client.send_file(None, {"context": "general", "path": "nope.png"})
    exe = tmp_path / "a.exe"
    exe.write_bytes(b"x")
    assert "cannot be sent" in client.send_file(None, {"context": "general", "path": str(exe)})


def test_downloads_never_overwrite(tmp_path):
    downloads = client.Downloads(str(tmp_path))
    for n in range(2):
        downloads.handle({"type": "file_data_start", "id": str(n), "name": "a.png"})
        piece = base64.b64encode(b"x").decode()
        downloads.handle({"type": "file_data", "id": str(n), "data": piece})
        downloads.handle({"type": "file_data_end", "id": str(n)})
    assert sorted(os.listdir(tmp_path)) == ["a (1).png", "a.png"]
