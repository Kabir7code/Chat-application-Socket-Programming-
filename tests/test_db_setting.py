"""NFR-004 (#55): where the server keeps its database (--db / CHAT_DB)."""

import logging

from chat import config, server


def test_default_database_file(monkeypatch):
    monkeypatch.delenv("CHAT_DB", raising=False)
    assert config.parse_args("x", []).db == "chat.db"


def test_database_from_environment(monkeypatch):
    monkeypatch.setenv("CHAT_DB", "from_env.db")
    assert config.parse_args("x", []).db == "from_env.db"


def test_flag_beats_environment(monkeypatch):
    monkeypatch.setenv("CHAT_DB", "from_env.db")
    assert config.parse_args("x", ["--db", "from_flag.db"]).db == "from_flag.db"


def test_memory_database_is_allowed():
    assert config.parse_args("x", ["--db", ":memory:"]).db == ":memory:"


def test_tests_use_a_throwaway_database(server):
    assert server.store.path == ":memory:"


def test_main_passes_the_database_to_the_server(monkeypatch, tmp_path, caplog):
    path = str(tmp_path / "mine.db")
    started = {}

    class FakeServer:
        def __init__(self, host, port, tls_context, db_path):
            started.update(host=host, port=port, tls=tls_context, db=db_path)

        def serve_forever(self):
            pass

    monkeypatch.setattr(server, "ChatServer", FakeServer)
    monkeypatch.setattr(server, "setup_logging", lambda: None)
    monkeypatch.setattr("sys.argv", ["chat.server", "--no-tls", "--port", "0", "--db", path])
    caplog.set_level(logging.INFO, logger="chat.server")

    server.main()

    assert started == {"host": "127.0.0.1", "port": 0, "tls": None, "db": path}
    assert f"Saving messages to {path}" in caplog.text


def test_server_creates_the_database_file(tmp_path):
    path = tmp_path / "data" / "chat.db"
    path.parent.mkdir()
    srv = server.ChatServer(port=0, db_path=str(path)).start()
    srv.stop()
    assert path.exists()
