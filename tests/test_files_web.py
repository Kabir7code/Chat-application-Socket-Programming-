"""Sending files from the web page (through the web gateway)."""

import base64
import os
import pathlib
import urllib.request

from chat import files, web

from test_web import Tab, base_url, gateway  # noqa: F401 - gateway is a fixture

APP_JS = (pathlib.Path(web.__file__).parent / "static" / "app.js").read_text()
INDEX = (pathlib.Path(web.__file__).parent / "static" / "index.html").read_text()


def test_file_goes_through_the_gateway(server, gateway):  # noqa: F811
    alice, bob = Tab(gateway, "alice"), Tab(gateway, "bob")
    try:
        data = os.urandom(70_000)
        alice.send(type="file_start", upload="w1", name="cat.png", size=len(data))
        for piece in files.chunks(data):
            alice.send(type="file_chunk", upload="w1", data=piece)
        alice.send(type="file_end", upload="w1")
        sent = alice.wait_for_type("file_sent")
        assert "* You sent [image] cat.png" in sent["display"]
        got = bob.wait_for_type("file")
        assert got["display"].endswith(f"/get {got['file']['id']}")
        bob.send(type="file_get", id=got["file"]["id"])
        events = bob.wait_for(lambda e: e["type"] == "file_data_end")
        pieces = [base64.b64decode(e["data"]) for e in events if e["type"] == "file_data"]
        assert b"".join(pieces) == data
        assert all(e["display"] == "" for e in events if e["type"] == "file_data")
    finally:
        alice.close()
        bob.close()


def test_typing_file_in_the_page_explains_the_button(server, gateway):  # noqa: F811
    alice = Tab(gateway, "alice")
    try:
        assert "paperclip" in alice.command("/file /etc/passwd")["local"]
    finally:
        alice.close()


def test_page_policy_allows_only_its_own_blob_media(gateway):  # noqa: F811
    with urllib.request.urlopen(base_url(gateway) + "/", timeout=3) as response:
        policy = response.headers["Content-Security-Policy"]
    assert "default-src 'self'" in policy
    assert "img-src 'self' blob:" in policy and "media-src 'self' blob:" in policy


def test_page_has_the_attach_button_and_same_limits():
    assert 'id="attach"' in INDEX and 'id="file-input"' in INDEX
    for kind, (extensions, limit) in files.KINDS.items():
        assert f"{kind}: {{ extensions:" in APP_JS
        assert f"limit: {limit // files.MB} }}" in APP_JS
        for extension in extensions:
            assert f'"{extension}"' in APP_JS
    assert f"const CHUNK_BYTES = {files.CHUNK_BYTES // 1024} * 1024;" in APP_JS
