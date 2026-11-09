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
    /quit                  leave the chat
    /help                  show commands
"""

import ssl
import sys
import threading
from datetime import datetime

from chat import config, protocol, tls

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
  /quit                  leave the chat
  /help                  show this help"""

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
    if kind == "users":
        names = message["users"]
        return f"* Online ({len(names)}): {', '.join(names)}"
    if kind == "system":
        return f"* {message['text']}"
    if kind == "error":
        return f"! {message['message']}"
    return str(message)


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
    if command == "/quit":
        return {"type": "quit"}, None
    if command == "/help":
        return None, HELP
    return None, f"Unknown command {command}. Type /help for commands."


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


def receive_loop(sock):
    while True:
        try:
            message = protocol.recv_message(sock)
        except (OSError, protocol.ProtocolError):
            message = None
        if message is None:
            print("\n[disconnected from server]")
            return
        print(format_message(message))


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
