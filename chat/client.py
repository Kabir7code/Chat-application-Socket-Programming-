"""Terminal chat client.

Commands:
    <text>                 send to everyone
    /msg <user> <text>     private message to one user
    /create <group>        create a group (you become its admin)
    /join <group>          join a group
    /add <group> <user>    add someone to your group (admin only)
    /leave <group>         leave a group
    /g <group> <text>      message everyone in a group
    /quit                  leave the chat
    /help                  show commands
"""

import socket
import sys
import threading

from chat import config, protocol

HELP = """Commands:
  <text>                 send to everyone
  /msg <user> <text>     private message to one user
  /create <group>        create a group (you become its admin)
  /join <group>          join a group
  /add <group> <user>    add someone to your group (admin only)
  /leave <group>         leave a group
  /g <group> <text>      message everyone in a group
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


def format_message(message):
    kind = message["type"]
    if kind == "chat" and message.get("context") == "group":
        return f"[{message['group']}] {message['from']}: {message['text']}"
    if kind == "chat":
        return f"{message['from']}: {message['text']}"
    if kind == "group_update":
        members = ", ".join(message["members"]) or "none"
        return f"* [{message['group']}] {message['text']} (members: {members})"
    if kind == "private":
        return f"[private] {message['from']}: {message['text']}"
    if kind == "private_sent":
        return f"[private to {message['to']}] {message['text']}"
    if kind == "system":
        return f"* {message['text']}"
    if kind == "error":
        return f"! {message['message']}"
    return str(message)


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
        sock = socket.create_connection((args.host, args.port))
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
