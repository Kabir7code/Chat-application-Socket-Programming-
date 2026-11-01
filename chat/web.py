"""Web gateway: use the chat from a browser (NFR-004, #16).

A browser cannot open a raw TCP/TLS socket, so this small HTTP server sits in
between. Each browser tab gets one normal chat connection to the chat server,
and messages are relayed both ways:

    browser --HTTP--> gateway --TCP/TLS--> chat server

    POST /api/connect     {username}         open a connection and register
    POST /api/send        {session, message} forward one protocol message
    POST /api/command     {session, line}    run a typed line, e.g. /join Squad
    POST /api/disconnect  {session}          leave the chat
    GET  /api/events?session=...             Server-Sent Events stream

Run the chat server first, then:  python -m chat.web
"""

import argparse
import json
import logging
import queue
import secrets
import socket
import ssl
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from chat import client, config, protocol, tls
from chat.server import MAX_TEXT_LENGTH

log = logging.getLogger("chat.web")

DEFAULT_WEB_HOST = "127.0.0.1"
DEFAULT_WEB_PORT = 8080
HEARTBEAT_SECONDS = 5  # a write to a closed tab fails, which is how we notice it left
REGISTER_TIMEOUT = 10  # seconds to wait for the chat server to answer a register
STREAM_GRACE_SECONDS = 30  # a session that never opens its event stream is closed
MAX_BODY_BYTES = 128 * 1024

STATIC_DIR = Path(__file__).parent / "static"
# Only these files are ever served, so a path like /../setup.cfg cannot reach anything.
STATIC_FILES = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/index.html": ("index.html", "text/html; charset=utf-8"),
    "/app.js": ("app.js", "text/javascript; charset=utf-8"),
    "/style.css": ("style.css", "text/css; charset=utf-8"),
}


class ConnectError(Exception):
    """The chat connection could not be opened, or the username was refused."""

    def __init__(self, message, status):
        super().__init__(message)
        self.message = message
        self.status = status


def with_display(message):
    """Add the same text the terminal client would print."""
    return {**message, "display": client.format_message(message)}


class WebSession:
    """One browser tab and its connection to the chat server."""

    def __init__(self, token, username, sock):
        self.token = token
        self.username = username
        self.sock = sock
        self.users_at_join = []
        self.events = queue.Queue()
        self.groups = set()
        self.streaming = False
        self.grace_timer = None
        self._send_lock = threading.Lock()

    def send(self, message):
        with self._send_lock:
            protocol.send_message(self.sock, message)

    def read_loop(self):
        """Move messages from the chat server to the queue the browser reads."""
        try:
            while True:
                message = protocol.recv_message(self.sock)
                if message is None:
                    return
                if message["type"] == "group_update":
                    self._track_group(message)
                self.events.put(with_display(message))
        except (OSError, ValueError, protocol.ProtocolError) as exc:
            log.debug("connection for %s ended: %s", self.username, exc)
        finally:
            self.events.put({"type": "disconnected"})

    def _track_group(self, update):
        if self.username in update.get("members", []):
            self.groups.add(update["group"])
        else:
            self.groups.discard(update["group"])

    def echo(self, message):
        """The chat server does not send people their own messages back (the
        terminal already shows what was typed), so add a copy for the sender.
        Skipped when the server is going to refuse the message, so the sender
        only sees the error."""
        text = message.get("text")
        if not isinstance(text, str) or not text.strip() or len(text) > MAX_TEXT_LENGTH:
            return
        copy = {"type": "chat", "self": True, "time": protocol.timestamp(),
                "from": self.username, "text": text}
        if message["type"] == "chat":
            copy["context"] = "general"
        elif message["type"] == "group" and message.get("group") in self.groups:
            copy.update(context="group", group=message["group"])
        else:
            return
        self.events.put(with_display(copy))


class ChatGateway:
    def __init__(self, chat_host, chat_port, tls_context=None,
                 web_host=DEFAULT_WEB_HOST, web_port=DEFAULT_WEB_PORT):
        self.chat_host = chat_host
        self.chat_port = chat_port
        self.tls_context = tls_context
        self.web_host = web_host
        self.web_port = web_port
        self._sessions = {}
        self._lock = threading.Lock()
        self._httpd = None

    # ------------------------------------------------------------ lifecycle
    def start(self):
        """Start serving in a background thread."""
        self._httpd = ThreadingHTTPServer((self.web_host, self.web_port), make_handler(self))
        self.web_port = self._httpd.server_address[1]  # real port if 0 was given
        threading.Thread(target=self._httpd.serve_forever, kwargs={"poll_interval": 0.05},
                         daemon=True).start()
        return self

    def stop(self):
        self._httpd.shutdown()
        self._httpd.server_close()
        with self._lock:
            sessions = list(self._sessions.values())
        for session in sessions:
            self.close_session(session)

    # ------------------------------------------------------------- sessions
    def open_session(self, username):
        sock, registered, early_messages = self._connect_and_register(username)
        session = WebSession(secrets.token_urlsafe(24), registered["username"], sock)
        session.users_at_join = registered["users"]
        for message in early_messages:
            session.events.put(with_display(message))
        with self._lock:
            self._sessions[session.token] = session
        threading.Thread(target=session.read_loop, daemon=True).start()
        session.grace_timer = threading.Timer(
            STREAM_GRACE_SECONDS, self._close_if_not_streaming, args=(session,))
        session.grace_timer.daemon = True
        session.grace_timer.start()
        return session

    def _connect_and_register(self, username):
        where = f"{self.chat_host}:{self.chat_port}"
        try:
            sock = tls.connect(self.chat_host, self.chat_port, self.tls_context)
        except ssl.SSLCertVerificationError as exc:
            raise ConnectError(f"Server certificate could not be verified "
                               f"({exc.verify_message}).", 502) from exc
        except OSError as exc:
            raise ConnectError(f"Could not reach the chat server at {where}.", 502) from exc
        try:
            sock.settimeout(REGISTER_TIMEOUT)
            protocol.send_message(sock, {"type": "register", "username": username})
            # Someone else's message can arrive just before our own "registered".
            early_messages = []
            while True:
                reply = protocol.recv_message(sock)
                if reply is None:
                    raise ConnectError("The chat server closed the connection.", 502)
                if reply["type"] == "error":
                    raise ConnectError(reply["message"], 400)
                if reply["type"] == "registered":
                    sock.settimeout(None)
                    return sock, reply, early_messages
                early_messages.append(reply)
        except ConnectError:
            sock.close()
            raise
        except (OSError, protocol.ProtocolError) as exc:
            sock.close()
            raise ConnectError(f"No answer from the chat server at {where}.", 502) from exc

    def get_session(self, token):
        with self._lock:
            return self._sessions.get(token)

    def close_session(self, session):
        """Leave the chat. Safe to call more than once."""
        with self._lock:
            if self._sessions.pop(session.token, None) is None:
                return
        if session.grace_timer is not None:
            session.grace_timer.cancel()
        try:
            session.send({"type": "quit"})
        except (OSError, protocol.ProtocolError):
            pass
        try:
            session.sock.shutdown(socket.SHUT_RDWR)  # wakes up the reader thread
        except OSError:
            pass
        session.sock.close()

    def _close_if_not_streaming(self, session):
        if not session.streaming:
            log.info("closing %s: its event stream never opened", session.username)
            self.close_session(session)

    # --------------------------------------------------------------- relay
    def forward(self, session, message):
        if message["type"] == "quit":
            self.close_session(session)
            return
        session.send(message)
        session.echo(message)

    def run_command(self, session, line):
        """Handle a typed line with the terminal client's own parser.
        Returns the text to show locally, if any."""
        message, local_text = client.parse_command(line.strip())
        if message is not None:
            self.forward(session, message)
        return local_text


def make_handler(gateway):
    class Handler(BaseHTTPRequestHandler):
        server_version = "ChatGateway"

        def log_message(self, format, *args):
            log.debug("%s %s", self.address_string(), format % args)

        # ---------------------------------------------------------- replies
        def send_json(self, status, payload):
            body = json.dumps(payload).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def read_json(self):
            """The JSON object in the request body, or None after replying with
            an error. Requiring the JSON content type stops other websites from
            posting to this local server: browsers will not send that across
            sites without a permission check that this server never grants."""
            content_type = self.headers.get("Content-Type", "").split(";")[0].strip()
            if content_type != "application/json":
                self.send_json(415, {"error": "Content-Type must be application/json."})
                return None
            try:
                length = int(self.headers.get("Content-Length", ""))
            except ValueError:
                self.send_json(400, {"error": "Missing Content-Length."})
                return None
            if not 0 <= length <= MAX_BODY_BYTES:
                self.send_json(413, {"error": "Request too large."})
                return None
            try:
                payload = json.loads(self.rfile.read(length))
            except ValueError:
                self.send_json(400, {"error": "Body is not valid JSON."})
                return None
            if not isinstance(payload, dict):
                self.send_json(400, {"error": "Body must be a JSON object."})
                return None
            return payload

        def find_session(self, token):
            session = gateway.get_session(token) if isinstance(token, str) else None
            if session is None:
                self.send_json(404, {"error": "Unknown session."})
            return session

        # -------------------------------------------------------------- GET
        def do_GET(self):
            url = urlsplit(self.path)
            if url.path == "/api/events":
                self.stream_events(parse_qs(url.query).get("session", [None])[0])
            elif url.path in STATIC_FILES:
                self.serve_static(url.path)
            elif url.path == "/favicon.ico":  # browsers ask for it on their own
                self.send_response(204)
                self.end_headers()
            else:
                self.send_json(404, {"error": "Not found."})

        def serve_static(self, path):
            name, content_type = STATIC_FILES[path]
            body = (STATIC_DIR / name).read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-cache")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Security-Policy", "default-src 'self'")
            self.end_headers()
            self.wfile.write(body)

        def stream_events(self, token):
            session = self.find_session(token)
            if session is None:
                return
            with gateway._lock:
                already_open = session.streaming
                session.streaming = True
            if already_open:
                self.send_json(409, {"error": "This session already has an event stream."})
                return
            if session.grace_timer is not None:
                session.grace_timer.cancel()
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            try:
                while True:
                    try:
                        event = session.events.get(timeout=HEARTBEAT_SECONDS)
                    except queue.Empty:
                        self.wfile.write(b": keepalive\n\n")
                        continue
                    self.wfile.write(f"data: {json.dumps(event)}\n\n".encode("utf-8"))
                    if event["type"] == "disconnected":
                        return
            except OSError:
                log.debug("event stream for %s dropped", session.username)
            finally:
                gateway.close_session(session)

        # ------------------------------------------------------------- POST
        def do_POST(self):
            routes = {
                "/api/connect": self.api_connect,
                "/api/send": self.api_send,
                "/api/command": self.api_command,
                "/api/disconnect": self.api_disconnect,
            }
            route = routes.get(urlsplit(self.path).path)
            if route is None:
                self.send_json(404, {"error": "Not found."})
                return
            payload = self.read_json()
            if payload is not None:
                route(payload)

        def api_connect(self, payload):
            username = payload.get("username")
            if not isinstance(username, str):
                self.send_json(400, {"error": "Username is required."})
                return
            try:
                session = gateway.open_session(username)
            except ConnectError as exc:
                self.send_json(exc.status, {"error": exc.message})
                return
            self.send_json(200, {
                "session": session.token,
                "username": session.username,
                "users": session.users_at_join,
                "encrypted": gateway.tls_context is not None,
            })

        def relay(self, action):
            """Run an action that writes to the chat server, reporting failures."""
            try:
                return action(), None
            except protocol.ProtocolError as exc:
                self.send_json(400, {"error": str(exc)})
            except OSError:
                self.send_json(502, {"error": "Disconnected from server."})
            return None, True

        def api_send(self, payload):
            session = self.find_session(payload.get("session"))
            if session is None:
                return
            message = payload.get("message")
            if not isinstance(message, dict) or not isinstance(message.get("type"), str):
                self.send_json(400, {"error": "message must be an object with a type."})
                return
            _, failed = self.relay(lambda: gateway.forward(session, message))
            if not failed:
                self.send_json(200, {"ok": True})

        def api_command(self, payload):
            session = self.find_session(payload.get("session"))
            if session is None:
                return
            line = payload.get("line")
            if not isinstance(line, str):
                self.send_json(400, {"error": "line must be text."})
                return
            local_text, failed = self.relay(lambda: gateway.run_command(session, line))
            if failed:
                return
            reply = {"ok": True, "quit": gateway.get_session(session.token) is None}
            if local_text:
                reply["local"] = local_text
            self.send_json(200, reply)

        def api_disconnect(self, payload):
            session = self.find_session(payload.get("session"))
            if session is not None:
                gateway.close_session(session)
                self.send_json(200, {"ok": True})

    return Handler


def parse_args(argv=None):
    """The gateway's own flags, plus the usual --host/--port/--cafile/--no-tls
    for the chat server it connects to."""
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--web-host", default=DEFAULT_WEB_HOST,
                        help=f"address for the web page (default {DEFAULT_WEB_HOST})")
    parser.add_argument("--web-port", type=int, default=DEFAULT_WEB_PORT,
                        help=f"port for the web page (default {DEFAULT_WEB_PORT})")
    web_args, rest = parser.parse_known_args(argv)
    if "-h" in rest or "--help" in rest:
        print(parser.format_help())
    args = config.parse_args("Serve the chat as a web page.", rest)
    args.web_host, args.web_port = web_args.web_host, web_args.web_port
    return args


def main():
    args = parse_args()
    gateway = ChatGateway(args.host, args.port, config.client_tls(args),
                          args.web_host, args.web_port).start()
    if args.web_host in ("127.0.0.1", "localhost"):
        print(f"Open http://localhost:{gateway.web_port} in your browser", flush=True)
    else:
        print(f"Open http://localhost:{gateway.web_port} in your browser "
              f"(or http://<this machine's IP>:{gateway.web_port} from another one)")
        print("Warning: anyone on this network can open this page, and traffic between "
              "the browser and this gateway is not encrypted.")
    print(f"Chat server: {args.host}:{args.port}, "
          f"{'encrypted (TLS)' if gateway.tls_context else 'NOT encrypted'}", flush=True)
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        print("\nShutting down.")
    finally:
        gateway.stop()


if __name__ == "__main__":
    main()
