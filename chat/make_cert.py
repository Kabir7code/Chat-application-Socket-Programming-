"""Create a self-signed certificate for the chat server.

    python -m chat.make_cert                      # for this computer only
    python -m chat.make_cert --host 192.168.1.20  # also valid for that IP

Writes certs/server.crt and certs/server.key. Give server.crt (never the
.key) to everyone who runs a client; they pass it with --cafile, or keep
it at certs/server.crt where the client looks by default.

Uses the openssl command, which comes with macOS, Linux and Git for Windows.
"""

import argparse
import ipaddress
import os
import shutil
import subprocess
import sys


def subject_alt_names(hosts):
    names = ["DNS:localhost", "IP:127.0.0.1"]
    for host in hosts:
        try:
            ipaddress.ip_address(host)
            entry = f"IP:{host}"
        except ValueError:
            entry = f"DNS:{host}"
        if entry not in names:
            names.append(entry)
    return names


def make_cert(out_dir, hosts, days=365):
    openssl = shutil.which("openssl")
    if openssl is None:
        sys.exit("openssl was not found. Install it (or Git for Windows) and try again.")
    os.makedirs(out_dir, exist_ok=True)
    cert, key = os.path.join(out_dir, "server.crt"), os.path.join(out_dir, "server.key")
    subprocess.run(
        [openssl, "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-sha256",
         "-days", str(days), "-subj", "/CN=chat-server",
         "-addext", "subjectAltName=" + ",".join(subject_alt_names(hosts)),
         "-keyout", key, "-out", cert],
        check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    return cert, key


def main():
    parser = argparse.ArgumentParser(
        description="Create a self-signed certificate for the chat server.")
    parser.add_argument("--host", action="append", default=[],
                        help="extra IP address or hostname clients will use (repeatable)")
    parser.add_argument("--out", default="certs", help="output folder (default: certs)")
    args = parser.parse_args()
    cert, key = make_cert(args.out, args.host)
    print(f"Created {cert} and {key}")
    print(f"Valid for: {', '.join(subject_alt_names(args.host))}")
    print(f"Share {cert} with everyone running a client. Keep {key} private.")


if __name__ == "__main__":
    main()
