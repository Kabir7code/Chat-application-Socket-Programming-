# Chat-application-Socket-Programming-

A real-time client-server chat application built using Socket Programming that enables multiple users to communicate over a network. The project demonstrates how network sockets can be used to establish connections, exchange messages, and manage communication between clients and a server.

## Requirements

- Python 3.10 or newer
- No third-party packages are needed to run the app (standard library only)
- The `openssl` command, once, to create the encryption certificate (included with macOS, Linux and Git for Windows)

## Running it

Open one terminal for the server and one terminal per user.

**1. Create the certificate (first time only)**

```bash
python -m chat.make_cert
```

This creates `certs/server.crt` and `certs/server.key`. All traffic between clients and the server is encrypted with TLS. The `certs/` folder is in `.gitignore`, so each machine makes its own.

**2. Start the server**

```bash
python -m chat.server
```

```
Chat server listening on 127.0.0.1:5000 with TLS
```

**3. Start a client in each other terminal**

```bash
python -m chat.client
```

Each client asks for a username. Usernames must be unique and 1–20 letters, digits or underscores.

### Choosing the host and port

Both programs accept the same options. Command-line flags win over environment variables, which win over the defaults.

| Setting | Flag | Environment variable | Default |
|---|---|---|---|
| Server address | `--host` | `CHAT_HOST` | `127.0.0.1` |
| Server port | `--port` | `CHAT_PORT` | `5000` |
| Server certificate | `--cert` | `CHAT_CERT` | `certs/server.crt` |
| Server private key | `--key` | `CHAT_KEY` | `certs/server.key` |
| Certificate the client trusts | `--cafile` | `CHAT_CAFILE` | `certs/server.crt` |
| Turn encryption off (debugging only) | `--no-tls` | `CHAT_NO_TLS=1` | encryption on |

To chat across machines on the same network, create the certificate for the server's IP, start the server with `--host 0.0.0.0`, and give each client a copy of `server.crt` (never the `.key`):

```bash
# on the server machine (IP 192.168.1.20)
python -m chat.make_cert --host 192.168.1.20
python -m chat.server --host 0.0.0.0 --port 6000

# on each client machine, with server.crt copied over
python -m chat.client --host 192.168.1.20 --port 6000 --cafile server.crt
```

The client checks the server's certificate, so it will refuse to connect to a server that is not ours.

## Commands

| Type this | What happens |
|---|---|
| `any text` | Sends the message to everyone online |
| `/msg <user> <text>` | Sends a private message that only `<user>` sees |
| `/create <group>` | Creates a group; you become its admin |
| `/join <group>` | Joins an existing group |
| `/add <group> <user>` | Adds an online user to your group (admin only) |
| `/g <group> <text>` | Sends a message to everyone in the group |
| `/leave <group>` | Leaves the group |
| `/quit` | Leaves the chat (others are told you left) |
| `/help` | Shows the list of commands |

## Sample session

Three users, recorded from a real run. Bob first tries a name that is taken, sends Alice a private message and quits; Carol messages a user who does not exist, then her client is killed to simulate a crash.

**Alice**
```
Choose a username: alice
Welcome, alice! Online: nobody yet
Type /help for commands.
* bob joined the chat
* carol joined the chat
hi everyone!
[private] bob: this is just for you
* bob left the chat
* carol left the chat
```

**Bob**
```
Choose a username: alice
! Username already taken.
Choose a username: bob
Welcome, bob! Online: alice
* carol joined the chat
alice: hi everyone!
/msg alice this is just for you
[private to alice] this is just for you
/quit
```

**Carol**
```
Choose a username: carol
Welcome, carol! Online: alice, bob
alice: hi everyone!
/msg dave are you there?
! User not found/offline
* bob left the chat
```

Carol never sees Bob's private message, and the server keeps running after her client crashes.

### Group chat

Alice creates a group and adds Carol, Bob joins and later leaves. Every change shows the updated member list.

**Alice**
```
/create Squad
* [Squad] Group Squad created. You are the admin. (members: alice)
* [Squad] bob joined Squad (members: alice, bob)
/add Squad carol
* [Squad] alice added carol to Squad (members: alice, bob, carol)
[Squad] carol: thanks for adding me
* [Squad] bob left Squad (members: alice, carol)
```

**Bob**
```
/join Squad
* [Squad] bob joined Squad (members: alice, bob)
/add Squad carol
! Only the group admin can add members.
/leave Squad
* [Squad] You left Squad (members: alice, carol)
```

Group names are 1-30 letters, digits, underscores or hyphens. Only members can send to a group. If the admin leaves, the next member becomes admin, and an empty group is deleted.

## Project layout

```
chat/
  protocol.py   message framing: 4-byte length + JSON, shared by client and server
  server.py     multi-client server, one thread per client
  registry.py   thread-safe list of connected and registered users
  groups.py     group chat: members, admin, create/join/add/leave
  client.py     terminal client and command parsing
  config.py     host, port and TLS settings
  tls.py        TLS encryption for client and server sockets
  make_cert.py  creates the self-signed server certificate
tests/          automated tests (pytest)
Documents/      SRS, use-case diagram and flows, test cases
```

## How it works

- **Framing.** TCP is a byte stream, so every message is sent as a 4-byte length followed by a JSON body. Long or rapid messages always arrive whole and separate.
- **Concurrency.** The server starts one thread per client. Shared state lives in a lock-protected registry, and each socket has its own send lock so two threads never write to it at once.
- **Groups.** Group membership is kept on the server, so a group message is only ever sent to current members. Leaving or disconnecting removes you from every group.
- **Encryption.** Every connection is wrapped in TLS (1.2 or newer). A test captures the raw network bytes during a chat and checks that no message text, usernames or JSON can be read from them.
- **Registration first.** A socket must register a unique username before it can send anything.
- **Failure isolation.** Bad input, crashes or a failed send on one client never affect anyone else. TCP keepalive detects clients that vanish without closing the connection.

## Running the tests

```bash
pip install -r requirements-dev.txt
pytest
flake8 chat tests
```

GitHub Actions runs the same checks on every push and pull request (see `.github/workflows/ci.yml`).

## Team

| Member | GitHub |
|---|---|
| Kabir | [@Kabir7code](https://github.com/Kabir7code) |
| Keerthana | [@KeerthanaK0304](https://github.com/KeerthanaK0304) |
| Josh | [@jjosh2005](https://github.com/jjosh2005) |

Work is tracked on the [project board](https://github.com/users/Kabir7code/projects/2).
