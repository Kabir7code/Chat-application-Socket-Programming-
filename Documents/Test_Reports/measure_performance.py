"""Part-3: 20-user delivery-time measurement (NFR-001, NFR-002).

Run from the repository root: python Documents/Test_Reports/measure_performance.py . /tmp/load.db
"""
import json, socket, statistics, sys, threading, time
sys.path.insert(0, sys.argv[1])
from chat import protocol, tls
from chat.server import ChatServer
from chat import make_cert  # noqa


def run(tls_on=False):
    ctx_srv = ctx_cli = None
    srv = ChatServer(port=0, db_path=sys.argv[2]).start()
    users = 20
    socks = []
    for i in range(users):
        s = socket.create_connection((srv.host, srv.port)); s.settimeout(5)
        protocol.send_message(s, {"type": "register", "username": f"user{i}"})
        while protocol.recv_message(s)["type"] != "registered":
            pass
        socks.append(s)
    # everyone in one group, plus private messages
    protocol.send_message(socks[0], {"type": "create_group", "group": "Load"})
    for s in socks[1:]:
        protocol.send_message(s, {"type": "join_group", "group": "Load"})
    time.sleep(1.0)
    lat = {"group": [], "private": []}
    lost = {"group": 0, "private": 0}
    stop = threading.Event()
    received = {i: [] for i in range(users)}

    def reader(i, s):
        s.settimeout(0.5)
        while not stop.is_set():
            try:
                m = protocol.recv_message(s)
            except (socket.timeout, OSError):
                continue
            if m is None:
                return
            if m.get("type") in ("chat", "private") and m.get("text", "").startswith("t="):
                received[i].append((time.time(), m))

    ts = [threading.Thread(target=reader, args=(i, s), daemon=True) for i, s in enumerate(socks)]
    for t in ts:
        t.start()
    sent = []
    start = time.time()
    rounds = 10
    for r in range(rounds):
        for i, s in enumerate(socks):
            now = time.time()
            if i % 2 == 0:
                protocol.send_message(s, {"type": "group", "group": "Load", "text": f"t={now} g {i} {r}"})
                sent.append(("group", i, r, now))
            else:
                to = (i + 1) % users
                protocol.send_message(s, {"type": "private", "to": f"user{to}", "text": f"t={now} p {i} {r} {to}"})
                sent.append(("private", i, r, now))
        time.sleep(0.05)
    time.sleep(2)
    stop.set()
    elapsed = time.time() - start
    for i in range(users):
        for when, m in received[i]:
            sent_at = float(m["text"].split()[0][2:])
            kind = "private" if m["type"] == "private" else "group"
            lat[kind].append((when - sent_at) * 1000)
    expected_group = (users // 2) * rounds * (users - 1)
    expected_private = (users // 2) * rounds
    got_group = len(lat["group"]); got_private = len(lat["private"])
    srv.stop()
    out = {"users": users, "rounds": rounds, "messages_sent": len(sent),
           "group_deliveries_expected": expected_group, "group_deliveries": got_group,
           "private_deliveries_expected": expected_private, "private_deliveries": got_private,
           "elapsed_s": round(elapsed, 2)}
    for k, v in lat.items():
        v.sort()
        out[k] = {"median_ms": round(statistics.median(v), 1), "p95_ms": round(v[int(len(v) * .95)], 1),
                  "max_ms": round(max(v), 1)}
    return out


print(json.dumps(run(), indent=1))
