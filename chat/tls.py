"""TLS encryption between client and server (NFR-005, #22).

The server presents a certificate and every byte after the handshake is
encrypted, so someone capturing traffic on the network cannot read the
chat. The client checks the server's certificate against a trusted copy
(by default certs/server.crt), so it cannot be fooled by another server
pretending to be ours.

Create the certificate once with:  python -m chat.make_cert
"""

import socket
import ssl

HANDSHAKE_TIMEOUT = 10  # seconds a client gets to finish the TLS handshake


def server_context(certfile, keyfile):
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.load_cert_chain(certfile, keyfile)
    return context


def client_context(cafile):
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)  # verifies cert and hostname
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.load_verify_locations(cafile)
    return context


def wrap_server_side(context, conn):
    """Do the server half of the handshake on an accepted socket.

    Runs on the client's own handler thread, so a slow or broken client
    cannot hold up anyone else. Raises OSError (ssl.SSLError is one) if
    the handshake fails or takes too long.
    """
    conn.settimeout(HANDSHAKE_TIMEOUT)
    tls_conn = context.wrap_socket(conn, server_side=True)
    tls_conn.settimeout(None)
    return tls_conn


def connect(host, port, context=None):
    """Open a connection to the server, encrypted if a context is given."""
    sock = socket.create_connection((host, port))
    if context is None:
        return sock
    try:
        return context.wrap_socket(sock, server_hostname=host)
    except OSError:
        sock.close()
        raise
