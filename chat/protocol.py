"""Wire protocol shared by the client and the server.

TCP is a byte stream: one recv() can return half a message or two messages
glued together. Every message is therefore sent as a frame:

    [4-byte big-endian length][UTF-8 JSON body]

The receiver reads exactly 4 bytes, then exactly `length` bytes, so messages
always arrive whole and separate (NFR-003).
"""

import itertools
import json
import struct
import threading

HEADER = struct.Struct("!I")
MAX_FRAME_BYTES = 64 * 1024  # largest message body we accept


class ProtocolError(Exception):
    """A frame arrived whole but its content is invalid. The stream is still
    in sync, so the connection can carry on."""


class FrameError(ProtocolError):
    """The framing itself is broken. The stream can no longer be trusted, so
    the connection must be closed."""


def encode(message):
    """Turn a message dict into one framed byte string."""
    body = json.dumps(message, ensure_ascii=False).encode("utf-8")
    if len(body) > MAX_FRAME_BYTES:
        raise ProtocolError(f"message too large ({len(body)} bytes)")
    return HEADER.pack(len(body)) + body


def decode(body):
    """Turn a frame body back into a message dict."""
    try:
        message = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProtocolError(f"invalid JSON: {exc}") from exc
    if not isinstance(message, dict) or "type" not in message:
        raise ProtocolError("message must be an object with a 'type' field")
    return message


def send_message(sock, message):
    """Send one message dict over a socket."""
    sock.sendall(encode(message))


def _recv_exact(sock, size):
    """Read exactly `size` bytes, or return None if the peer closed first."""
    chunks = []
    remaining = size
    while remaining:
        chunk = sock.recv(remaining)
        if not chunk:
            return None
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def recv_message(sock):
    """Receive one message dict. Returns None when the connection closes."""
    header = _recv_exact(sock, HEADER.size)
    if header is None:
        return None
    (length,) = HEADER.unpack(header)
    if length > MAX_FRAME_BYTES:
        raise FrameError(f"frame too large ({length} bytes)")
    body = _recv_exact(sock, length)
    if body is None:
        return None
    return decode(body)


_ids = itertools.count(1)
_ids_lock = threading.Lock()


def new_message_id():
    """Next message ID. IDs only go up, so they also show the order the
    server handled messages in."""
    with _ids_lock:
        return next(_ids)


def make_chat_message(text, sender):
    """Build the message a server delivers for a chat line (UT_07)."""
    return {"type": "chat", "id": new_message_id(), "from": sender, "text": text}
