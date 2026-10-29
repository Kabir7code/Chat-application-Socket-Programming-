"""Chat server: accepts many clients at once, one thread per client (FR-002).

Every client must register a unique username first (FR-001, NFR-005). After
that, chat lines are delivered in real time to everyone else (FR-003),
private messages go to one user only (FR-005), group messages go only to the
group's members (FR-004), and other users are told when someone joins or
leaves (FR-006). A client that quits, crashes or sends bad
data is cleaned up without affecting anyone else (FR-007, FR-008).
"""

import re
import socket
import sys
import threading
import time
import traceback

from chat import config, protocol, tls
from chat.groups import GroupError, GroupManager
from chat.registry import Session, SessionRegistry

USERNAME_PATTERN = re.compile(r"^[A-Za-z0-9_]{1,20}$")
MAX_TEXT_LENGTH = 4000

# Detect peers that vanish without closing the connection (cable pulled,
# laptop asleep): the OS probes an idle connection and gives up after
# about IDLE + INTERVAL * COUNT seconds.
KEEPALIVE_IDLE = 10
KEEPALIVE_INTERVAL = 5
KEEPALIVE_COUNT = 3


def system_message(event, username, text):
    return {"type": "system", "event": event, "username": username, "text": text}


def error_message(code, text):
    return {"type": "error", "code": code, "message": text}


def enable_keepalive(conn):
    conn.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
    for name, value in (
        ("TCP_KEEPIDLE", KEEPALIVE_IDLE),
        ("TCP_KEEPINTVL", KEEPALIVE_INTERVAL),
        ("TCP_KEEPCNT", KEEPALIVE_COUNT),
    ):
        if hasattr(socket, name):  # not every OS exposes every option
            conn.setsockopt(socket.IPPROTO_TCP, getattr(socket, name), value)


class ChatServer:
    def __init__(self, host=config.DEFAULT_HOST, port=config.DEFAULT_PORT, tls_context=None):
        self.host = host
        self.port = port
        self.tls_context = tls_context  # None = unencrypted (tests, debugging)
        self.registry = SessionRegistry()
        self.groups = GroupManager()
        self._listener = None
        self._running = threading.Event()

    # Read-only views, handy for tests and debugging.
    @property
    def clients(self):
        return self.registry.connected()

    @property
    def users(self):
        return self.registry.usernames()

    # ------------------------------------------------------------ lifecycle
    def start(self):
        """Bind and start accepting connections in a background thread."""
        self._listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._listener.bind((self.host, self.port))
        self._listener.listen()
        self.port = self._listener.getsockname()[1]  # real port if 0 was given
        self._running.set()
        threading.Thread(target=self._accept_loop, daemon=True).start()
        return self

    def serve_forever(self):
        self.start()
        mode = "with TLS" if self.tls_context else "WITHOUT encryption"
        print(f"Chat server listening on {self.host}:{self.port} {mode}")
        try:
            while self._running.is_set():
                time.sleep(0.5)
        except KeyboardInterrupt:
            print("\nShutting down.")
        finally:
            self.stop()

    def stop(self):
        self._running.clear()
        if self._listener:
            self._listener.close()
        for session in self.registry.connected():
            session.close()

    # -------------------------------------------------------------- workers
    def _accept_loop(self):
        while self._running.is_set():
            try:
                conn, _addr = self._listener.accept()
            except OSError:
                break  # listener closed
            enable_keepalive(conn)
            session = Session(conn)
            self.registry.connect(session)
            threading.Thread(target=self._handle_client, args=(session,), daemon=True).start()

    def _handle_client(self, session):
        try:
            if self.tls_context is not None:
                try:
                    session.conn = tls.wrap_server_side(self.tls_context, session.conn)
                except OSError:
                    return  # failed or timed-out handshake; nothing was registered
            while session.alive:
                try:
                    message = protocol.recv_message(session.conn)
                except protocol.FrameError:
                    session.send(error_message("MALFORMED", "Invalid frame; disconnecting."))
                    break  # stream is out of sync, cannot continue
                except protocol.ProtocolError:
                    session.send(error_message("MALFORMED", "Message was not valid JSON."))
                    continue
                except OSError:
                    break  # connection reset, timed out, or closed (FR-007)
                if message is None or message["type"] == "quit":
                    break
                try:
                    self._dispatch(session, message)
                except Exception:  # one bad message must not kill the session (FR-008)
                    traceback.print_exc(file=sys.stderr)
                    session.send(error_message("SERVER_ERROR", "Could not process message."))
        finally:
            self._disconnect(session)

    def _disconnect(self, session):
        was_registered = self.registry.disconnect(session)
        session.close()
        if was_registered:
            name = session.username
            for group, remaining in self.groups.remove_user(name).items():
                self._group_update(remaining, "left", group, name, f"{name} left {group}")
            self._broadcast(system_message("leave", name, f"{name} left the chat"))

    # ------------------------------------------------------------- features
    def _dispatch(self, session, message):
        kind = message["type"]
        if session.username is None:
            if kind == "register":
                self._register(session, message.get("username", ""))
            else:  # NFR-005: only registered sockets may send messages
                session.send(error_message("NOT_REGISTERED", "Register a username first."))
            return
        if kind == "register":
            session.send(error_message("ALREADY_REGISTERED", "You are already registered."))
        elif kind == "chat":
            self._deliver_chat(session, message.get("text"))
        elif kind == "private":
            self._deliver_private(session, message.get("to"), message.get("text"))
        elif kind in GROUP_HANDLERS:
            try:
                GROUP_HANDLERS[kind](self, session, message)
            except GroupError as exc:
                session.send(error_message(exc.code, exc.message))
        else:
            session.send(error_message("UNKNOWN_TYPE", f"Unknown message type '{kind}'."))

    def _register(self, session, username):
        username = str(username).strip()
        if not USERNAME_PATTERN.match(username):
            session.send(error_message(
                "INVALID_USERNAME",
                "Username must be 1-20 letters, digits or underscores.",
            ))
            return
        if not self.registry.register(session, username):
            session.send(error_message("USERNAME_TAKEN", "Username already taken."))
            return
        session.send({
            "type": "registered",
            "username": username,
            "users": self.registry.usernames(),
        })
        self._broadcast(
            system_message("join", username, f"{username} joined the chat"),
            exclude=session,
        )

    def _valid_text(self, session, text):
        if not isinstance(text, str) or not text.strip():
            session.send(error_message("EMPTY_MESSAGE", "Message text is empty."))
            return False
        if len(text) > MAX_TEXT_LENGTH:
            session.send(error_message(
                "MESSAGE_TOO_LONG", f"Messages are limited to {MAX_TEXT_LENGTH} characters."
            ))
            return False
        return True

    def _deliver_chat(self, session, text):
        if not self._valid_text(session, text):
            return
        message = protocol.make_chat_message(text, session.username)
        message["context"] = "general"
        self._broadcast(message, exclude=session)

    def _deliver_private(self, session, recipient_name, text):
        """FR-005: only the sender and the recipient ever see it."""
        if not self._valid_text(session, text):
            return
        recipient = self.registry.get(str(recipient_name))
        message_id = protocol.new_message_id()
        if recipient is None or not recipient.send({
            "type": "private",
            "id": message_id,
            "from": session.username,
            "to": recipient_name,
            "text": text,
        }):
            session.send(error_message("USER_NOT_FOUND", "User not found/offline"))
            return
        session.send({"type": "private_sent", "id": message_id, "to": recipient_name, "text": text})

    # --------------------------------------------------------- groups (FR-004)
    def _create_group(self, session, message):
        group = str(message.get("group", "")).strip()
        members = self.groups.create(group, session.username)
        self._group_update(members, "created", group, session.username,
                           f"Group {group} created. You are the admin.")

    def _join_group(self, session, message):
        group = str(message.get("group", ""))
        members = self.groups.join(group, session.username)
        self._group_update(members, "joined", group, session.username,
                           f"{session.username} joined {group}")

    def _add_member(self, session, message):
        group, user = str(message.get("group", "")), str(message.get("username", ""))
        if self.registry.get(user) is None:
            raise GroupError("USER_NOT_FOUND", "User not found/offline")
        members = self.groups.add(group, session.username, user)
        self._group_update(members, "added", group, user,
                           f"{session.username} added {user} to {group}")

    def _leave_group(self, session, message):
        group = str(message.get("group", ""))
        remaining = self.groups.leave(group, session.username)
        session.send(self._group_update_message(remaining, "left", group, session.username,
                                                f"You left {group}"))
        self._group_update(remaining, "left", group, session.username,
                           f"{session.username} left {group}")

    def _deliver_group(self, session, message):
        group, text = str(message.get("group", "")), message.get("text")
        if not self.groups.is_member(group, session.username):
            self.groups.members(group)  # raises GROUP_NOT_FOUND if it does not exist
            raise GroupError("NOT_A_MEMBER", f"You are not a member of '{group}'.")
        if not self._valid_text(session, text):
            return
        chat = protocol.make_chat_message(text, session.username)
        chat.update(context="group", group=group)
        self._send_to(self.groups.members(group), chat, exclude=session.username)

    def _group_update_message(self, members, event, group, username, text):
        return {"type": "group_update", "event": event, "group": group, "username": username,
                "members": members, "text": text}

    def _group_update(self, members, event, group, username, text):
        """Tell every current member what changed, with the new member list."""
        self._send_to(members, self._group_update_message(members, event, group, username, text))

    def _send_to(self, usernames, message, exclude=None):
        for name in usernames:
            if name != exclude:
                recipient = self.registry.get(name)
                if recipient is not None:
                    recipient.send(message)

    def _broadcast(self, message, exclude=None):
        """Send to every registered user except `exclude`. A recipient whose
        socket has failed is skipped; their own thread cleans them up."""
        for session in self.registry.registered():
            if session is not exclude:
                session.send(message)


GROUP_HANDLERS = {
    "create_group": ChatServer._create_group,
    "join_group": ChatServer._join_group,
    "add_member": ChatServer._add_member,
    "leave_group": ChatServer._leave_group,
    "group": ChatServer._deliver_group,
}


def main():
    args = config.parse_args("Run the chat server.")
    ChatServer(args.host, args.port, config.server_tls(args)).serve_forever()


if __name__ == "__main__":
    main()
