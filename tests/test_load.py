"""NFR-002 (#20): the server supports 20 users at the same time."""

import threading
import time

USERS = 20


def connect_many(connect, count=USERS):
    clients = [connect(f"user{i}") for i in range(count)]
    return clients


def wait_for_chat(client, text):
    while True:
        message = client.recv()
        if message is None:
            return None
        if message["type"] == "chat" and message["text"] == text:
            return message


def test_twenty_users_can_register(server, connect):
    connect_many(connect)
    assert len(server.users) == USERS


def test_message_reaches_all_nineteen_others(server, connect):
    clients = connect_many(connect)
    sender, others = clients[0], clients[1:]

    sender.send({"type": "chat", "text": "hello everyone"})

    for client in others:
        message = wait_for_chat(client, "hello everyone")
        assert message is not None
        assert message["from"] == "user0"
    sender.assert_silent()  # the sender does not get their own message back


def test_twenty_users_sending_at_once(server, connect):
    clients = connect_many(connect)
    expected = {f"from user{i}" for i in range(USERS)}

    threads = [
        threading.Thread(target=c.send, args=({"type": "chat", "text": f"from user{i}"},))
        for i, c in enumerate(clients)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    # every user receives the 19 messages from everyone else
    for i, client in enumerate(clients):
        got = set()
        deadline = time.time() + 5
        while len(got) < USERS - 1 and time.time() < deadline:
            message = client.recv()
            if message and message["type"] == "chat":
                got.add(message["text"])
        assert got == expected - {f"from user{i}"}


def test_twenty_users_can_be_reached_privately(server, connect):
    clients = connect_many(connect)
    for i in range(1, USERS):
        clients[0].send({"type": "private", "to": f"user{i}", "text": f"hi {i}"})
    for i in range(1, USERS):
        message = clients[i].recv_until("private")
        assert message["text"] == f"hi {i}"
