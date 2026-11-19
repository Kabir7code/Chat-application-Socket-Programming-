"""Terminal chat client.

Commands:
    <text>                 send to everyone
    /msg <user> <text>     private message to one user
    /create <group>        create a group (you become its admin)
    /join <group>          join a group
    /add <group> <user>    add someone to your group (admin only)
    /leave <group>         leave a group
    /g <group> <text>      message everyone in a group
    /users                 list who is online
    /history <user>        your last private messages with a user
    /file <path>           send an image, video, audio or document to everyone
    /pfile <user> <path>   send a file privately
    /gfile <group> <path>  send a file to a group
    /get <id>              download a file into the downloads/ folder
    /quit                  leave the chat
    /help                  show commands
"""

import base64
import os
import secrets
import ssl
import sys
import threading
from datetime import datetime

from chat import config, files, protocol, tls

HELP = """Commands:
  <text>                 send to everyone
  /msg <user> <text>     private message to one user
  /create <group>        create a group (you become its admin)
  /join <group>          join a group
  /add <group> <user>    add someone to your group (admin only)
  /leave <group>         leave a group
  /g <group> <text>      message everyone in a group
  /users                 list who is online
  /history <user>        your last private messages with a user
  /file <path>           send an image, video, audio or document to everyone
  /pfile <user> <path>   send a file privately
  /gfile <group> <path>  send a file to a group
  /get <id>              download a file into the downloads/ folder
  /quit                  leave the chat
  /help                  show this help
Files: images up to 5 MB, documents and audio up to 10 MB, videos up to 25 MB."""

# command -> (message type, field names, usage text). The last field takes
# the rest of the line, so group messages can contain spaces.
GROUP_COMMANDS = {
    "/create": ("create_group", ["group"], "/create <group>"),
    "/join": ("join_group", ["group"], "/join <group>"),
    "/leave": ("leave_group", ["group"], "/leave <group>"),
    "/add": ("add_member", ["group", "username"], "/add <group> <user>"),
    "/g": ("group", ["group", "text"], "/g <group> <text>"),
}


def time_prefix(message):
    """FR-009 (#13): "[14:05] " in the reader's local time, or "" if the
    message has no time (or a time we cannot read)."""
    try:
        sent = datetime.fromisoformat(message["time"]).astimezone()
    except (KeyError, TypeError, ValueError):
        return ""
    return sent.strftime("[%H:%M] ")


def format_message(message):
    kind = message["type"]
    when = time_prefix(message)
    if kind == "chat" and message.get("context") == "group":
        earlier = " (earlier)" if message.get("history") else ""
        return f"{when}[{message['group']}]{earlier} {message['from']}: {message['text']}"
    if kind == "chat":
        earlier = "(earlier) " if message.get("history") else ""  # FR-011 (#56)
        return f"{when}{earlier}{message['from']}: {message['text']}"
    if kind == "group_update":
        members = ", ".join(message["members"]) or "none"
        return f"* [{message['group']}] {message['text']} (members: {members})"
    if kind == "private":
        away = " (while you were away)" if message.get("offline") else ""  # FR-012 (#59)
        return f"{when}[private] {message['from']}{away}: {message['text']}"
    if kind == "private_sent":
        later = " (offline - delivered when they log in)" if message.get("queued") else ""
        return f"{when}[private to {message['to']}] {message['text']}{later}"
    if kind == "private_history":  # FR-012 (#57)
        return format_private_history(message)
    if kind in ("file", "file_sent"):
        return format_file(message)
    if kind in ("file_ready", "file_data", "file_data_start", "file_data_end"):
        return ""  # file transfer steps; the client handles these itself
    if kind == "users":
        names = message["users"]
        return f"* Online ({len(names)}): {', '.join(names)}"
    if kind == "system":
        return f"* {message['text']}"
    if kind == "error":
        return f"! {message['message']}"
    return str(message)


def format_file(message):
    """A file someone sent, or the confirmation that yours was sent."""
    when = time_prefix(message)
    info = message["file"]
    where = {"group": f"[{message.get('group')}] ", "private": "[private] "}.get(
        message.get("context"), "")
    if message["type"] == "file_sent":
        to = {"group": f" to {message.get('group')}", "private": f" to {message.get('to')}"}.get(
            message.get("context"), " to everyone")
        return f"{when}* You sent {message['text']}{to}"
    earlier = "(earlier) " if message.get("history") else ""
    return f"{when}{where}{earlier}{message['from']} sent {message['text']} - /get {info['id']}"


def format_private_history(message):
    """FR-012 (#57): the reply to /history <user>, one line per message."""
    other, messages = message["with"], message["messages"]
    if not messages:
        return f"* No private messages with {other} yet."
    lines = [f"* Private messages with {other} (last {len(messages)}):"]
    for item in messages:
        lines.append(f"  {time_prefix(item)}{item['from']}: {item['text']}")
    return "\n".join(lines)


def parse_command(line):
    """Turn a typed line into a message dict, or a string to show locally.

    Returns (message, local_text); exactly one of them is not None, except
    for /quit which returns ({"type": "quit"}, None).
    """
    if not line.startswith("/"):
        return {"type": "chat", "text": line}, None
    command, _, rest = line.partition(" ")
    if command == "/msg":
        recipient, _, text = rest.strip().partition(" ")
        if not recipient or not text.strip():
            return None, "Usage: /msg <user> <text>"
        return {"type": "private", "to": recipient, "text": text}, None
    if command in GROUP_COMMANDS:
        kind, fields, usage = GROUP_COMMANDS[command]
        parts = rest.strip().split(None, len(fields) - 1)
        if len(parts) != len(fields) or not parts[-1].strip():
            return None, f"Usage: {usage}"
        return {"type": kind, **dict(zip(fields, parts))}, None
    if command == "/users":
        return {"type": "list_users"}, None
    if command == "/history":  # FR-012 (#57)
        user = rest.strip()
        if not user or " " in user:
            return None, "Usage: /history <user>"
        return {"type": "private_history", "with": user}, None
    if command in ("/file", "/pfile", "/gfile"):
        return parse_file_command(command, rest)
    if command == "/get":
        file_id = rest.strip()
        if not file_id or " " in file_id:
            return None, "Usage: /get <id>"
        return {"type": "file_get", "id": file_id}, None
    if command == "/quit":
        return {"type": "quit"}, None
    if command == "/help":
        return None, HELP
    return None, f"Unknown command {command}. Type /help for commands."


def parse_file_command(command, rest):
    """/file <path>, /pfile <user> <path> or /gfile <group> <path>. The result
    is a local request (type "_send_file"): the client reads the file and
    sends it in pieces with send_file()."""
    rest = rest.strip()
    if command == "/file":
        if not rest:
            return None, "Usage: /file <path>"
        return {"type": "_send_file", "context": "general", "path": rest}, None
    who, _, path = rest.partition(" ")
    usage = "/pfile <user> <path>" if command == "/pfile" else "/gfile <group> <path>"
    if not who or not path.strip():
        return None, f"Usage: {usage}"
    if command == "/pfile":
        return {"type": "_send_file", "context": "private", "to": who, "path": path.strip()}, None
    return {"type": "_send_file", "context": "group", "group": who, "path": path.strip()}, None


def send_file(sock, request):
    """Check a file and send it in pieces. Returns the text to show."""
    path = os.path.expanduser(request["path"])
    if not os.path.isfile(path):
        return f"! No such file: {request['path']}"
    size = os.path.getsize(path)
    try:
        kind, name = files.check(os.path.basename(path), size)
    except files.FileRejected as exc:
        return f"! {exc.message}"
    token = secrets.token_hex(8)
    start = {"type": "file_start", "upload": token, "name": name, "size": size,
             "context": request["context"]}
    for field in ("to", "group"):
        if field in request:
            start[field] = request[field]
    protocol.send_message(sock, start)
    with open(path, "rb") as handle:
        while True:
            data = handle.read(files.CHUNK_BYTES)
            if not data:
                break
            protocol.send_message(sock, {"type": "file_chunk", "upload": token,
                                         "data": base64.b64encode(data).decode("ascii")})
    protocol.send_message(sock, {"type": "file_end", "upload": token})
    return f"* Sending {files.describe(kind, name, size)}..."


class Downloads:
    """Puts downloaded files together in the downloads/ folder."""

    def __init__(self, folder="downloads"):
        self.folder = folder
        self._open = {}  # file id -> (handle, path)

    def handle(self, message):
        """Deal with a file_data_* message; returns text to show, or None."""
        kind, file_id = message["type"], message.get("id")
        if kind == "file_data_start":
            os.makedirs(self.folder, exist_ok=True)
            path = self._free_path(files.safe_name(message["name"]))
            self._open[file_id] = (open(path, "wb"), path)
            return f"* Downloading {message['name']}..."
        if file_id not in self._open:
            return None
        handle, path = self._open[file_id]
        if kind == "file_data":
            handle.write(base64.b64decode(message["data"]))
            return None
        handle.close()
        del self._open[file_id]
        return f"* Saved {path}"

    def _free_path(self, name):
        stem, extension = os.path.splitext(name)
        path, n = os.path.join(self.folder, name), 1
        while os.path.exists(path):
            path = os.path.join(self.folder, f"{stem} ({n}){extension}")
            n += 1
        return path


def register(sock):
    """Ask for a username until the server accepts one (UC-01)."""
    while True:
        try:
            username = input("Choose a username: ").strip()
        except EOFError:
            return None
        protocol.send_message(sock, {"type": "register", "username": username})
        reply = protocol.recv_message(sock)
        if reply is None:
            return None
        if reply["type"] == "registered":
            others = [u for u in reply["users"] if u != reply["username"]]
            print(f"Welcome, {reply['username']}! Online: {', '.join(others) or 'nobody yet'}")
            print("Type /help for commands.")
            return reply["username"]
        print(format_message(reply))


def receive_loop(sock, downloads=None):
    downloads = downloads or Downloads()
    while True:
        try:
            message = protocol.recv_message(sock)
        except (OSError, protocol.ProtocolError):
            message = None
        if message is None:
            print("\n[disconnected from server]")
            return
        if message["type"].startswith("file_data"):
            text = downloads.handle(message)
        else:
            text = format_message(message)
        if text:
            print(text)


def main():
    args = config.parse_args("Connect to the chat server.")
    try:
        sock = tls.connect(args.host, args.port, config.client_tls(args))
    except ssl.SSLCertVerificationError as exc:
        sys.exit(f"Server certificate could not be verified ({exc.verify_message}). "
                 "Check that --cafile is the server's certificate.")
    except OSError as exc:
        sys.exit(f"Could not connect to {args.host}:{args.port} ({exc})")
    try:
        if register(sock) is None:
            return
        threading.Thread(target=receive_loop, args=(sock,), daemon=True).start()
        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue
            message, local_text = parse_command(line)
            if local_text:
                print(local_text)
                continue
            if message["type"] == "_send_file":
                print(send_file(sock, message))
                continue
            protocol.send_message(sock, message)
            if message["type"] == "quit":
                break
    except KeyboardInterrupt:
        pass
    except OSError:
        print("[connection lost]")
    finally:
        try:
            protocol.send_message(sock, {"type": "quit"})
        except OSError:
            pass
        sock.close()


if __name__ == "__main__":
    main()
