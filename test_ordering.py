"""IT_08 (#31): messages sent at the same moment reach every user in the same order."""

import threading

PER_SENDER = 100


def collect_chats(client, count):
    texts = []
    while len(texts) < count:
        message = client.recv()
        assert message is not None, "connection closed early"
        if message["type"] == "chat":
            texts.append(message["text"])
    return texts


def test_all_receivers_see_the_same_order(server, connect):
    senders = [connect("alice"), connect("bob"), connect("carol")]
    receivers = [connect("dave"), connect("erin"), connect("frank")]
    total = PER_SENDER * len(senders)

    def blast(client, name):
        for i in range(PER_SENDER):
            client.send({"type": "chat", "text": f"{name}-{i}"})

    threads = [threading.Thread(target=blast, args=(c, n))
               for c, n in zip(senders, ["alice", "bob", "carol"])]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    orders = [collect_chats(r, total) for r in receivers]
    assert orders[0] == orders[1] == orders[2]


def test_each_senders_messages_stay_in_sending_order(server, connect):
    alice, bob, carol = connect("alice"), connect("bob"), connect("carol")

    def blast(client, name):
        for i in range(PER_SENDER):
            client.send({"type": "chat", "text": f"{name}-{i}"})

    threads = [threading.Thread(target=blast, args=(alice, "alice")),
               threading.Thread(target=blast, args=(bob, "bob"))]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    received = collect_chats(carol, 2 * PER_SENDER)
    for name in ("alice", "bob"):
        mine = [t for t in received if t.startswith(name)]
        assert mine == [f"{name}-{i}" for i in range(PER_SENDER)]


def test_group_members_see_the_same_order(server, connect):
    alice, bob, carol, dave = (connect(n) for n in ("alice", "bob", "carol", "dave"))
    alice.send({"type": "create_group", "group": "Squad"})
    alice.recv_until("group_update")
    for c in (bob, carol, dave):
        c.send({"type": "join_group", "group": "Squad"})
        c.recv_until("group_update")

    def blast(client, name):
        for i in range(PER_SENDER):
            client.send({"type": "group", "group": "Squad", "text": f"{name}-{i}"})

    threads = [threading.Thread(target=blast, args=(alice, "alice")),
               threading.Thread(target=blast, args=(bob, "bob"))]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert collect_chats(carol, 2 * PER_SENDER) == collect_chats(dave, 2 * PER_SENDER)
