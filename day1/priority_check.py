"""Does --scheduling-policy priority reorder the waiting queue? Fill all max-num-seqs slots with long
requests of staggered length (so slots free one at a time), then queue low-priority requests before
one high-priority request; report finish order and finish times.
usage: python3 day1/priority_check.py [base_url] [max_num_seqs]
"""
import json, sys, threading, time, urllib.request

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000"
SLOTS = int(sys.argv[2]) if len(sys.argv) > 2 else 8
MODEL = [m["id"] for m in json.load(urllib.request.urlopen(BASE + "/v1/models"))["data"] if m.get("parent") is None][0]
done = []


def send(tag, max_tokens, priority):
    body = {"model": MODEL, "messages": [{"role": "user", "content": f"Write a long story about {tag}."}],
            "max_tokens": max_tokens, "min_tokens": max_tokens, "temperature": 0, "priority": priority}
    req = urllib.request.Request(BASE + "/v1/chat/completions", json.dumps(body).encode(), {"Content-Type": "application/json"})
    status = urllib.request.urlopen(req, timeout=600).status
    done.append((tag, status, time.perf_counter() - T0))


T0 = time.perf_counter()
threads = [threading.Thread(target=send, args=(f"filler{i}", 1000 + 300 * i, 0)) for i in range(SLOTS)]
for t in threads: t.start()
time.sleep(2)
for i in range(3):
    threads.append(threading.Thread(target=send, args=(f"low{i}", 20, 10))); threads[-1].start(); time.sleep(0.5)
threads.append(threading.Thread(target=send, args=("high", 20, -10))); threads[-1].start()
for t in threads: t.join()
assert all(st == 200 for _, st, _ in done)
for tag, _, t in done: print(f"  {t:7.2f} s  {tag}")
order = [tag for tag, _, _ in done if not tag.startswith("filler")]
print("finish order of queued requests:", order)
print("high finished before every low:", order.index("high") == 0)
