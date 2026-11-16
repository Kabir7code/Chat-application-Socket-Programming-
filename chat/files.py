"""Sending images, videos and documents.

What is allowed (checked by the clients before sending and again by the server):

    kind       extensions                                          largest file
    image      .jpg .jpeg .png .gif .webp                          5 MB
    document   .pdf .doc .docx .xls .xlsx .ppt .pptx .txt .csv     10 MB
    video      .mp4 .webm .mov                                     25 MB

A file never travels in one message: every frame on the wire is still limited
to 64 KB (protocol.MAX_FRAME_BYTES, SR-5). The sender splits the file into
32 KB pieces, base64-encoded:

    file_start {upload, name, size, context, to/group}   -> server checks it
    file_chunk {upload, data}  (repeated)
    file_end   {upload}                                  -> server saves it and
                                                            sends a "file" message
Anyone allowed to see that message can download the file the same way:

    file_get {id}  ->  file_data_start, file_data (repeated), file_data_end

The server keeps uploaded files in a folder next to its database, under a
random name; the original file name is only kept as text.
"""

import base64
import os
import re
import secrets
import shutil
import tempfile
import threading

MB = 1024 * 1024
KINDS = {
    "image": ({".jpg", ".jpeg", ".png", ".gif", ".webp"}, 5 * MB),
    "document": ({".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".txt", ".csv"},
                 10 * MB),
    "video": ({".mp4", ".webm", ".mov"}, 25 * MB),
}
CHUNK_BYTES = 32 * 1024  # raw bytes per piece; about 43 KB once base64-encoded
MAX_UPLOADS_PER_USER = 2  # files one connection may be sending at the same time
NAME_LENGTH = 100
FILE_ID = re.compile(r"^[0-9a-f]{32}$")


class FileRejected(Exception):
    """A file that may not be sent. `code` goes back to the client."""

    def __init__(self, code, message):
        super().__init__(message)
        self.code = code
        self.message = message


def kind_of(name):
    """'image', 'document' or 'video' for an allowed file name, else None."""
    extension = os.path.splitext(str(name))[1].lower()
    for kind, (extensions, _) in KINDS.items():
        if extension in extensions:
            return kind
    return None


def safe_name(name):
    """The file name without any folder part or unusual characters."""
    name = os.path.basename(str(name).replace("\\", "/")).strip()
    name = re.sub(r"[^A-Za-z0-9._ ()-]", "_", name)
    stem, extension = os.path.splitext(name)
    stem = stem.lstrip(".") or "file"
    return stem[: NAME_LENGTH - len(extension)] + extension


def check(name, size):
    """Return (kind, safe name) for a file that may be sent, or raise FileRejected."""
    kind = kind_of(name)
    if kind is None:
        allowed = ", ".join(sorted(e for extensions, _ in KINDS.values() for e in extensions))
        raise FileRejected("FILE_TYPE_NOT_ALLOWED",
                           f"This file type cannot be sent. Allowed: {allowed}")
    limit = KINDS[kind][1]
    if not isinstance(size, int) or isinstance(size, bool) or size <= 0:
        raise FileRejected("EMPTY_FILE", "The file is empty.")
    if size > limit:
        raise FileRejected("FILE_TOO_LARGE",
                           f"{kind.capitalize()}s are limited to {limit // MB} MB "
                           f"(this file is {human_size(size)}).")
    return kind, safe_name(name)


def human_size(size):
    if size >= MB:
        return f"{size / MB:.1f} MB"
    if size >= 1024:
        return f"{size / 1024:.0f} KB"
    return f"{size} B"


def describe(kind, name, size):
    """The text shown for a file message, e.g. '[image] cat.png (120 KB)'."""
    return f"[{kind}] {name} ({human_size(size)})"


def chunks(data):
    """Split bytes into base64 text pieces that each fit in one frame."""
    for start in range(0, len(data), CHUNK_BYTES):
        yield base64.b64encode(data[start:start + CHUNK_BYTES]).decode("ascii")


class Upload:
    """A file one client is in the middle of sending."""

    def __init__(self, file_id, kind, name, size, target, path):
        self.file_id, self.kind, self.name, self.size = file_id, kind, name, size
        self.target = target  # ("general", None) / ("private", user) / ("group", group)
        self.path = path
        self.received = 0
        self.handle = open(path, "wb")

    def write(self, data):
        if self.received + len(data) > self.size:
            raise FileRejected("FILE_TOO_LARGE", "More data arrived than the file size given.")
        self.handle.write(data)
        self.received += len(data)

    def finish(self):
        self.handle.close()
        if self.received != self.size:
            raise FileRejected("FILE_INCOMPLETE",
                               f"Only {self.received} of {self.size} bytes arrived.")

    def discard(self):
        try:
            self.handle.close()
        finally:
            try:
                os.remove(self.path)
            except OSError:
                pass


class FileStore:
    """Where the server keeps uploaded files: a folder named after the database
    (chat.db -> chat_files/), or a temporary folder for an in-memory database."""

    def __init__(self, db_path):
        self.temporary = db_path == ":memory:"
        if self.temporary:
            self.folder = tempfile.mkdtemp(prefix="chat-files-")
        else:
            self.folder = os.path.splitext(os.path.abspath(db_path))[0] + "_files"
            os.makedirs(self.folder, exist_ok=True)
        self._lock = threading.Lock()
        self._uploads = {}  # (session id, upload token) -> Upload

    def path(self, file_id):
        if not FILE_ID.match(str(file_id)):
            raise FileRejected("FILE_NOT_FOUND", "File not found.")
        return os.path.join(self.folder, file_id)

    def start(self, owner, token, kind, name, size, target):
        with self._lock:
            mine = [key for key in self._uploads if key[0] == owner]
            if len(mine) >= MAX_UPLOADS_PER_USER:
                raise FileRejected("TOO_MANY_UPLOADS",
                                   "Wait for your other files to finish sending.")
            if (owner, token) in self._uploads:
                raise FileRejected("BAD_UPLOAD", "That upload has already started.")
            file_id = secrets.token_hex(16)
            upload = Upload(file_id, kind, name, size, target, self.path(file_id) + ".part")
            self._uploads[(owner, token)] = upload
            return upload

    def get_upload(self, owner, token):
        with self._lock:
            return self._uploads.get((owner, token))

    def end_upload(self, owner, token):
        """Remove a finished upload from the in-progress list and keep the file."""
        with self._lock:
            upload = self._uploads.pop((owner, token), None)
        if upload is None:
            return None
        try:
            upload.finish()
        except FileRejected:
            upload.discard()
            raise
        os.replace(upload.path, self.path(upload.file_id))
        return upload

    def abort(self, owner, token=None):
        """Throw away one upload, or all of a connection's uploads."""
        with self._lock:
            keys = [k for k in self._uploads if k[0] == owner and (token is None or k[1] == token)]
            uploads = [self._uploads.pop(k) for k in keys]
        for upload in uploads:
            upload.discard()

    def read_chunks(self, file_id):
        with open(self.path(file_id), "rb") as handle:
            while True:
                data = handle.read(CHUNK_BYTES)
                if not data:
                    return
                yield base64.b64encode(data).decode("ascii")

    def close(self):
        if self.temporary:
            shutil.rmtree(self.folder, ignore_errors=True)
