"""#10 (NFR-004): host/port settings shared by the server and the client.

Nothing is hard-coded in the server or client any more; both read from here.

Priority: command-line flag > environment variable > default.

    python -m chat.server --host 0.0.0.0 --port 6000
    CHAT_PORT=6000 python -m chat.client

Traffic is encrypted with TLS by default (NFR-005). Run
`python -m chat.make_cert` once to create certs/server.crt and server.key.
`--no-tls` turns encryption off, for debugging only.
"""

import argparse
import os

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 5000
DEFAULT_CERT = os.path.join("certs", "server.crt")
DEFAULT_KEY = os.path.join("certs", "server.key")


def parse_args(description, argv=None):
    """Read --host and --port, falling back to env vars, then defaults.

    `argv` is only passed in tests; normally argparse reads sys.argv.
    """
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
    parser.add_argument(
        "--no-tls",
        action="store_true",
        default=os.environ.get("CHAT_NO_TLS") == "1",
        help="turn off encryption, for debugging only (env CHAT_NO_TLS=1)",
    )
    parser.add_argument(
        "--cert",
        default=os.environ.get("CHAT_CERT", DEFAULT_CERT),
        help=f"server certificate (env CHAT_CERT, default {DEFAULT_CERT})",
    )
    parser.add_argument(
        "--key",
        default=os.environ.get("CHAT_KEY", DEFAULT_KEY),
        help=f"server private key (env CHAT_KEY, default {DEFAULT_KEY})",
    )
    parser.add_argument(
        "--cafile",
        default=os.environ.get("CHAT_CAFILE", DEFAULT_CERT),
        help=f"certificate the client trusts (env CHAT_CAFILE, default {DEFAULT_CERT})",
    )
    return parser.parse_args(argv)


def server_tls(args):
    """TLS context for the server, or None if --no-tls. Exits with a clear
    message if the certificate files are missing."""
    if args.no_tls:
        return None
    from chat import tls
    for path in (args.cert, args.key):
        if not os.path.exists(path):
            raise SystemExit(f"{path} not found. Run `python -m chat.make_cert` first "
                             "(or use --no-tls to run without encryption).")
    return tls.server_context(args.cert, args.key)


def client_tls(args):
    """TLS context for a client, or None if --no-tls."""
    if args.no_tls:
        return None
    from chat import tls
    if not os.path.exists(args.cafile):
        raise SystemExit(f"{args.cafile} not found. Copy server.crt from the server machine "
                         "and pass it with --cafile (or use --no-tls).")
    return tls.client_context(args.cafile)
