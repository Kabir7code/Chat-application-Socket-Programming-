"""Thread-safe shared state for the server (#9, NFR-002).

Every client has its own handler thread, and all of them read and change the
same set of sessions. Without locks two clients could register the same
username at the same moment, or two threads could write to one socket at
once and interleave their bytes.
"""

import threading

from chat import protocol


class Session:
    """One connected client."""

    def __init__(self, conn):
        self.conn = conn
        self.username = None
        self._send_lock = threading.Lock()
        self.alive = True

    def send(self, message):
        """Send a message. Returns False if this client is unreachable."""
        if not self.alive:
            return False
        try:
            with self._send_lock:  # one writer at a time keeps frames intact
                protocol.send_message(self.conn, message)
            return True
        except OSError:
            self.close()
            return False

    def close(self):
        self.alive = False
        try:
            self.conn.close()
        except OSError:
            pass


class SessionRegistry:
    def __init__(self):
        self._lock = threading.Lock()
        self._connected = set()
        self._by_username = {}

    def connect(self, session):
        with self._lock:
            self._connected.add(session)

    def register(self, session, username):
        """Claim a username atomically. Returns False if it is taken."""
        with self._lock:
            if username in self._by_username:
                return False
            self._by_username[username] = session
            session.username = username
            return True

    def disconnect(self, session):
        """Forget a session. Returns True if it was a registered user."""
        with self._lock:
            self._connected.discard(session)
            if session.username and self._by_username.get(session.username) is session:
                del self._by_username[session.username]
                return True
            return False

    def get(self, username):
        with self._lock:
            return self._by_username.get(username)

    def registered(self):
        """Snapshot of registered sessions, safe to loop over without the lock."""
        with self._lock:
            return list(self._by_username.values())

    def usernames(self):
        with self._lock:
            return sorted(self._by_username)

    def connected(self):
        with self._lock:
            return list(self._connected)
