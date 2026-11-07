"""FR-011 (#50): persistent message store.

Every chat, private and group message the server delivers is saved in an
SQLite database, so nothing is lost when the server restarts. Uses only
Python's built-in sqlite3 module.

One connection is shared by all client threads and guarded by a lock:
SQLite allows one writer at a time anyway, and chat traffic is small.
The tables are created automatically the first time a database is opened.

    store = MessageStore("chat.db")      # a file that survives restarts
    store = MessageStore()               # ":memory:", throwaway (tests)

A storage error is logged and reported as False, never raised: a problem
with the database must not stop messages from being delivered.
"""

import logging
import sqlite3
import threading

log = logging.getLogger("chat.storage")

MEMORY = ":memory:"

SCHEMA = """
CREATE TABLE IF NOT EXISTS messages (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,  -- order the server saved them
    msg_id    INTEGER,                            -- the protocol message ID
    time      TEXT    NOT NULL,                   -- ISO 8601, UTC
    kind      TEXT    NOT NULL CHECK (kind IN ('chat', 'private', 'group')),
    sender    TEXT    NOT NULL,
    recipient TEXT,                               -- private messages only
    grp       TEXT,                               -- group messages only
    text      TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_messages_kind    ON messages (kind, id);
CREATE INDEX IF NOT EXISTS idx_messages_private ON messages (kind, sender, recipient, id);
CREATE INDEX IF NOT EXISTS idx_messages_group   ON messages (kind, grp, id);
"""


class MessageStore:
    def __init__(self, path=MEMORY):
        self.path = path
        self._lock = threading.Lock()
        self._db = sqlite3.connect(path, check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        with self._lock, self._db:
            if path != MEMORY:
                # Readers do not block the writer, and a crash cannot
                # leave the file half-written.
                self._db.execute("PRAGMA journal_mode=WAL")
            self._db.executescript(SCHEMA)

    # ------------------------------------------------------------- saving
    def save_chat(self, message):
        """A message to everyone (context "general")."""
        return self._save("chat", message)

    def save_private(self, message):
        """A delivered private message: needs "from" and "to"."""
        return self._save("private", message, recipient=message.get("to"))

    def save_group(self, message):
        """A group message: needs "group"."""
        return self._save("group", message, group=message.get("group"))

    def _save(self, kind, message, recipient=None, group=None):
        row = (message.get("id"), message.get("time"), kind, message.get("from"),
               recipient, group, message.get("text"))
        try:
            with self._lock, self._db:
                self._db.execute(
                    "INSERT INTO messages (msg_id, time, kind, sender, recipient, grp, text)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?)", row)
            return True
        except sqlite3.Error:
            log.exception("Could not save %s message from %s", kind, message.get("from"))
            return False

    # ------------------------------------------------------------ loading
    def recent_chat(self, limit=20):
        """The last `limit` messages to everyone, oldest first."""
        return self._recent("kind = 'chat'", (), limit)

    def private_between(self, user_a, user_b, limit=20):
        """The last `limit` private messages between two users (both
        directions), oldest first. Nobody else's messages are included."""
        return self._recent(
            "kind = 'private' AND ((sender = ? AND recipient = ?)"
            " OR (sender = ? AND recipient = ?))",
            (user_a, user_b, user_b, user_a), limit)

    def group_messages(self, group, limit=10):
        """The last `limit` messages in a group, oldest first."""
        return self._recent("kind = 'group' AND grp = ?", (group,), limit)

    def count(self):
        with self._lock:
            return self._db.execute("SELECT COUNT(*) FROM messages").fetchone()[0]

    def _recent(self, where, params, limit):
        query = (f"SELECT * FROM (SELECT * FROM messages WHERE {where} ORDER BY id DESC LIMIT ?)"
                 " ORDER BY id ASC")
        with self._lock:
            rows = self._db.execute(query, (*params, int(limit))).fetchall()
        return [to_message(row) for row in rows]

    def close(self):
        with self._lock:
            self._db.close()


def to_message(row):
    """Turn a database row back into the message the protocol uses."""
    message = {"id": row["msg_id"], "time": row["time"], "from": row["sender"], "text": row["text"]}
    if row["kind"] == "private":
        message.update(type="private", to=row["recipient"])
    elif row["kind"] == "group":
        message.update(type="chat", context="group", group=row["grp"])
    else:
        message.update(type="chat", context="general")
    return message
