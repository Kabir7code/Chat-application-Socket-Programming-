"""NFR-004 (#14): the server uses the logging module instead of print()."""

import logging
import pathlib
import time

from chat import server as server_module

SERVER_SOURCE = pathlib.Path(server_module.__file__).read_text()


def wait_for(caplog, text, timeout=3.0):
    """Log records come from server threads, so wait for them to appear."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if any(text in r.getMessage() for r in caplog.records):
            return True
        time.sleep(0.02)
    return False


def test_server_has_no_print_calls():
    code = [line for line in SERVER_SOURCE.splitlines() if not line.strip().startswith("#")]
    assert not any("print(" in line for line in code)


def test_server_uses_its_own_logger():
    assert server_module.log.name == "chat.server"


def test_connection_is_logged(server, connect, caplog):
    caplog.set_level(logging.INFO, logger="chat.server")
    connect()
    assert wait_for(caplog, "Connection from 127.0.0.1")


def test_registration_is_logged(server, connect, caplog):
    caplog.set_level(logging.INFO, logger="chat.server")
    connect("alice")
    assert wait_for(caplog, "alice registered")


def test_leaving_is_logged(server, connect, caplog):
    caplog.set_level(logging.INFO, logger="chat.server")
    alice = connect("alice")
    alice.send({"type": "quit"})
    assert wait_for(caplog, "alice left")


def test_broken_frame_is_logged_as_warning(server, connect, caplog):
    caplog.set_level(logging.INFO, logger="chat.server")
    client = connect("alice")
    client.sock.sendall((10_000_000).to_bytes(4, "big"))  # claims a 10 MB frame
    assert wait_for(caplog, "Broken frame from alice")
    record = next(r for r in caplog.records if "Broken frame" in r.getMessage())
    assert record.levelno == logging.WARNING


def test_unexpected_error_is_logged_with_traceback(server, connect, caplog, monkeypatch):
    caplog.set_level(logging.INFO, logger="chat.server")

    def broken(*_args):
        raise RuntimeError("boom")

    monkeypatch.setattr(server, "_deliver_chat", broken)
    alice = connect("alice")
    alice.send({"type": "chat", "text": "hi"})
    assert alice.recv_until("error")["code"] == "SERVER_ERROR"  # session survives
    assert wait_for(caplog, "Error handling 'chat' from alice")
    record = next(r for r in caplog.records if "Error handling" in r.getMessage())
    assert record.levelno == logging.ERROR
    assert record.exc_info is not None  # the traceback is kept


def test_log_level_comes_from_environment(monkeypatch):
    root = logging.getLogger()
    saved_level, saved_handlers = root.level, root.handlers[:]
    root.handlers = []
    try:
        monkeypatch.setenv("CHAT_LOG_LEVEL", "warning")
        server_module.setup_logging()
        assert root.level == logging.WARNING
    finally:
        root.handlers = saved_handlers
        root.setLevel(saved_level)


def test_unknown_log_level_falls_back_to_info(monkeypatch):
    root = logging.getLogger()
    saved_level, saved_handlers = root.level, root.handlers[:]
    root.handlers = []
    try:
        monkeypatch.setenv("CHAT_LOG_LEVEL", "LOUD")
        server_module.setup_logging()
        assert root.level == logging.INFO
    finally:
        root.handlers = saved_handlers
        root.setLevel(saved_level)
