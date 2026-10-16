"""M1 noisy neighbour through the t4-gateway: same workload as day2/m1_direct.py, but every request
carries its tenant's key and no model or priority; the gateway decides both.
Also snapshots vLLM's own prompt and generation token counters before and after, for the ledger check.

Tenants B and C each send one ~512-token request every INTERVAL seconds (open loop, streamed, 64 output
tokens). Phase "quiet": B and C alone. Phase "flood": tenant A also keeps A_CONC requests of ~4096
tokens in flight, 128 output tokens each. Every prompt starts with a random tag, so no prefix-cache hits.
All percentiles computed here; raw per-request rows go to the JSON file.
usage: python3 day3/m1_gateway.py <out.json> [--seconds 180] [--interval 2] [--a-conc 4] [--phases flood]
"""
import argparse, json, random, statistics, threading, time, urllib.request

ap = argparse.ArgumentParser()
ap.add_argument("out"); ap.add_argument("--base", default="http://127.0.0.1:8000")
ap.add_argument("--gateway", default="http://127.0.0.1:8080"); ap.add_argument("--seconds", type=float, default=180)
ap.add_argument("--interval", type=float, default=2.0); ap.add_argument("--a-conc", type=int, default=4)
ap.add_argument("--phases", default="flood")
args = ap.parse_args()
BASE = args.base
MODEL = [m["id"] for m in json.load(urllib.request.urlopen(BASE + "/v1/models"))["data"] if m.get("parent") is None][0]
WORDS = ("ledger invoice shipment carton pallet refund customer account balance warehouse order "
         "supplier quantity price discount freight backorder").split()
rng = random.SystemRandom()
lock = threading.Lock()
rows = []
KEYS = {"A": "demo-key-A", "B": "demo-key-B", "C": "demo-key-C"}


def metric(name):
    return sum(float(l.rsplit(" ", 1)[1]) for l in urllib.request.urlopen(BASE + "/metrics").read().decode().splitlines()
               if l.startswith(name) and not l.startswith("#"))


COUNTERS = ("vllm:prompt_tokens_total", "vllm:generation_tokens_total")


def text_of(words):
    return "%016x " % rng.getrandbits(64) + " ".join(rng.choice(WORDS) for _ in range(words))


def calibrate(target):
    words = target
    for _ in range(6):
        n = json.load(urllib.request.urlopen(urllib.request.Request(
            BASE + "/tokenize", json.dumps({"model": MODEL, "messages": [{"role": "user", "content": text_of(words) + "\nSummarise."}]}).encode(),
            {"Content-Type": "application/json"})))["count"]
        if abs(n - target) <= 8: break
        words = round(words * target / n)
    return words


def one(tenant, phase, words, max_tokens, priority):
    body = {"messages": [{"role": "user", "content": text_of(words) + "\nSummarise."}],
            "max_tokens": max_tokens, "min_tokens": max_tokens, "temperature": 0, "stream": True,
            "stream_options": {"include_usage": True}}
    req = urllib.request.Request(args.gateway + "/v1/chat/completions", json.dumps(body).encode(),
                                 {"Content-Type": "application/json", "Authorization": "Bearer " + KEYS[tenant]})
    t0 = time.perf_counter(); ttft = None; usage = None; status = 0
    try:
        with urllib.request.urlopen(req, timeout=900) as r:
            status = r.status
            for line in r:
                if not line.startswith(b"data: {"): continue
                c = json.loads(line[6:])
                if ttft is None and c.get("choices") and c["choices"][0]["delta"].get("content"):
                    ttft = time.perf_counter() - t0
                if c.get("usage"): usage = c["usage"]
    except Exception as e:
        status = repr(e)
    with lock:
        rows.append({"tenant": tenant, "phase": phase, "start": t0 - T0, "ttft": ttft,
                     "total": time.perf_counter() - t0, "status": status, "usage": usage})


def steady(tenant, phase, words, stop):
    nxt = time.perf_counter() + rng.uniform(0, args.interval)
    ts = []
    while nxt < stop:
        time.sleep(max(0, nxt - time.perf_counter()))
        t = threading.Thread(target=one, args=(tenant, phase, words, 64, 0)); t.start(); ts.append(t)
        nxt += args.interval
    for t in ts: t.join()


def flood(phase, words, stop):
    while time.perf_counter() < stop:
        one("A", phase, words, 128, 10)


def pct(v, p):
    v = sorted(v); k = (len(v) - 1) * p; f = int(k)
    return v[f] + (v[min(f + 1, len(v) - 1)] - v[f]) * (k - f)


w512, w4096 = calibrate(512), calibrate(4096)
print(f"model {MODEL}; words for 512 tokens: {w512}, for 4096: {w4096}; through {args.gateway}")
before = {c: metric(c) for c in COUNTERS}
T0 = time.perf_counter()
for phase in args.phases.split(","):
    stop = time.perf_counter() + args.seconds
    ths = [threading.Thread(target=steady, args=(t, phase, w512, stop)) for t in "BC"]
    if phase == "flood":
        ths += [threading.Thread(target=flood, args=(phase, w4096, stop)) for _ in range(args.a_conc)]
    for t in ths: t.start()
    for t in ths: t.join()
    for tenant in "ABC":
        rs = [r for r in rows if r["phase"] == phase and r["tenant"] == tenant]
        if not rs: continue
        ok = [r for r in rs if r["status"] == 200 and r["ttft"] is not None]
        tt, tot = [r["ttft"] for r in ok], [r["total"] for r in ok]
        print(f"[{phase:5}] {tenant}: {len(ok)}/{len(rs)} ok  first token median {pct(tt,.5):7.2f} s  95th {pct(tt,.95):7.2f} s"
              f"  max {max(tt):7.2f} s | total median {pct(tot,.5):7.2f} s  95th {pct(tot,.95):7.2f} s")
    time.sleep(5)
after = {c: metric(c) for c in COUNTERS}
vllm_tokens = {c: int(after[c] - before[c]) for c in COUNTERS}
print("vLLM counters over the run:", vllm_tokens)
json.dump({"args": vars(args), "model": MODEL, "vllm_tokens": vllm_tokens, "rows": rows}, open(args.out, "w"), indent=1)
