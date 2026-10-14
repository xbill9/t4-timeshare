"""What does one prompt token cost the T4, measured in output tokens? Sets w in the bucket charge
w x prompt_tokens + max_tokens.

Prefill: one request at a time, max_tokens=1, prompt lengths from 256 to 8192 tokens. Each prompt
starts with a random tag so the prefix cache cannot help, and the cache hit counter is checked to prove it.
Decode: one request at a time, a ~64-token prompt with 256 output tokens minus the same with 1.
Prefill is fitted as a + b*n + c*n^2 (attention makes it superlinear). All fits and ratios are computed here.
usage: python3 day1/prefill_cost.py [base_url] [repeats]
"""
import json, random, statistics, sys, time, urllib.request

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000"
REPEATS = int(sys.argv[2]) if len(sys.argv) > 2 else 5
MODEL = [m["id"] for m in json.load(urllib.request.urlopen(BASE + "/v1/models"))["data"] if m.get("parent") is None][0]
WORDS = ("ledger invoice shipment carton pallet refund customer account balance warehouse order "
         "supplier quantity price discount freight invoice backorder").split()
rng = random.SystemRandom()  # a fixed seed repeats the last run's prompts, which the prefix cache then serves


def post(path, body):
    req = urllib.request.Request(BASE + path, json.dumps(body).encode(), {"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=900) as r:
        return json.load(r)


def metric(name):
    return sum(float(l.rsplit(" ", 1)[1]) for l in urllib.request.urlopen(BASE + "/metrics").read().decode().splitlines()
               if l.startswith(name) and not l.startswith("#"))


def prompt_of(n_tokens):
    """A chat prompt whose templated length is close to n_tokens, starting with a unique tag."""
    tag = "%016x" % rng.getrandbits(64)
    words = n_tokens
    while True:
        text = tag + " " + " ".join(rng.choice(WORDS) for _ in range(words)) + "\nSummarise."
        msgs = [{"role": "user", "content": text}]
        n = post("/tokenize", {"model": MODEL, "messages": msgs})["count"]
        if abs(n - n_tokens) <= max(8, n_tokens // 100):
            return msgs, n
        words = max(1, round(words * n_tokens / n))


def timed(msgs, max_tokens):
    h0 = metric("vllm:prefix_cache_hits_total")
    t0 = time.perf_counter()
    r = post("/v1/chat/completions", {"model": MODEL, "messages": msgs, "max_tokens": max_tokens,
                                       "min_tokens": max_tokens, "temperature": 0})
    dt = time.perf_counter() - t0
    return dt, r["usage"], int(metric("vllm:prefix_cache_hits_total") - h0)


print("model:", MODEL, "repeats:", REPEATS)
timed(prompt_of(512)[0], 1)  # warm-up, not recorded

rows = []
for target in (256, 512, 1024, 2048, 4096, 8192):
    for _ in range(REPEATS):
        msgs, n = prompt_of(target)
        dt, usage, hits = timed(msgs, 1)
        assert usage["prompt_tokens"] == n, (usage, n)
        rows.append((n, dt, hits))
    ts = [dt for m, dt, _ in rows if abs(m - target) <= max(8, target // 100)]
    print(f"prompt ~{target:5}: median {statistics.median(ts)*1000:8.1f} ms  min {min(ts)*1000:8.1f}  max {max(ts)*1000:8.1f}")

print("cache hit tokens across all prefill requests:", sum(h for *_, h in rows))
xs, ys = [n for n, _, _ in rows], [dt for _, dt, _ in rows]


def solve3(m, v):
    """Gaussian elimination on a 3x3 system."""
    m = [r[:] + [b] for r, b in zip(m, v)]
    for i in range(3):
        p = max(range(i, 3), key=lambda r: abs(m[r][i])); m[i], m[p] = m[p], m[i]
        for r in range(3):
            if r != i:
                f = m[r][i] / m[i][i]; m[r] = [a - f * b for a, b in zip(m[r], m[i])]
    return [m[i][3] / m[i][i] for i in range(3)]


# least squares t = a + b*n + c*n^2, weighted by 1/t so short prompts count as much as long ones
w8 = [1 / y ** 2 for y in ys]
basis = [[1, x, x * x] for x in xs]
A = [[sum(w * u[i] * u[j] for w, u in zip(w8, basis)) for j in range(3)] for i in range(3)]
B = [sum(w * u[i] * y for w, u, y in zip(w8, basis, ys)) for i in range(3)]
qa, qb, qc = solve3(A, B)
worst = max(abs((qa + qb * x + qc * x * x) / y - 1) for x, y in zip(xs, ys))
print(f"prefill fit over {len(rows)} requests: {qa*1000:.1f} ms + {qb*1e6:.2f} us x n + {qc*1e9:.4f} ns x n^2;"
      f" worst error {worst*100:.1f}%")

dec = []
for _ in range(REPEATS):
    msgs, n = prompt_of(64)
    t1, _, _ = timed(msgs, 1)
    msgs2 = [{"role": "user", "content": "%016x" % rng.getrandbits(64) + msgs[0]["content"][16:]}]
    t256, u, _ = timed(msgs2, 256)
    assert u["completion_tokens"] == 256, u
    dec.append((t256 - t1) / 255)
tpot = statistics.median(dec)
print(f"decode: median {tpot*1000:.2f} ms per output token over {REPEATS} pairs (256 tokens minus 1 token, same length prompt)")
print("prefill time of one request, in output tokens of decode time:")
equiv = {}
for n in (256, 512, 1024, 2048, 4096, 8192, 16000):
    t = qa + qb * n + qc * n * n
    equiv[n] = t / tpot
    print(f"  {n:6} prompt tokens: {t*1000:9.1f} ms = {t/tpot:8.1f} output tokens = {t/tpot/n:.3f} per prompt token")
json.dump({"rows": rows, "fit_s": [qa, qb, qc], "fit_worst_rel_error": worst, "decode_ms_per_token": tpot * 1000,
           "decode_samples_ms": [d * 1000 for d in dec], "output_token_equivalent": equiv},
          open("day1/prefill_cost.json", "w"), indent=1)
