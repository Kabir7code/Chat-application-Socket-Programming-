"""Host/port configuration shared by the server and the client (#10).

Priority: command-line flag > environment variable > default.

    python -m chat.server --host 0.0.0.0 --port 6000
    CHAT_PORT=6000 python -m chat.client
"""

import argparse
import os

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 5000


def parse_args(description, argv=None):
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument(
        "--host",
        default=os.environ.get("CHAT_HOST", DEFAULT_HOST),
        help=f"server address (env CHAT_HOST, default {DEFAULT_HOST})",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.environ.get("CHAT_PORT", DEFAULT_PORT)),
        help=f"server port (env CHAT_PORT, default {DEFAULT_PORT})",
    )
    return parser.parse_args(argv)
