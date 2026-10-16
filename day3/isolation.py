"""Isolation checks through the gateway. Each verdict is computed from status codes, outputs and
vLLM's /metrics prefix-cache counters.

usage: python3 day3/isolation.py [gateway] [vllm]
"""
import json, secrets, sys, urllib.error, urllib.request

GW = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8080"
VLLM = sys.argv[2] if len(sys.argv) > 2 else "http://127.0.0.1:8000"
KEYS = {"A": "demo-key-A", "B": "demo-key-B", "C": "demo-key-C"}


def call(content, key=None, max_tokens=24, **extra):
    h = {"Content-Type": "application/json"}
    if key: h["Authorization"] = "Bearer " + key
    body = {"messages": [{"role": "user", "content": content}], "max_tokens": max_tokens, "temperature": 0, **extra}
    try:
        with urllib.request.urlopen(urllib.request.Request(GW + "/v1/chat/completions", json.dumps(body).encode(), h)) as r:
            return r.status, json.load(r)
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


def metric(name):
    return sum(float(l.rsplit(" ", 1)[1]) for l in urllib.request.urlopen(VLLM + "/metrics").read().decode().splitlines()
               if l.startswith(name) and not l.startswith("#"))


checks = []
def check(label, ok, detail):
    checks.append(ok); print(f"{'PASS' if ok else 'FAIL'}  {label}: {detail}")


s, _ = call("hi")
check("no key", s == 401, s)
s, _ = call("hi", key="not-a-key")
check("unknown key", s == 401, s)
s, _ = call("hi", key=KEYS["B"], model="rand")
check("B asks for C's adapter", s == 403, s)
s, _ = call("hi", key=KEYS["B"], model="gpt-5")
check("B asks for a model that is not served", s == 404, s)

q = "List three uses for a spare GPU."
s, b = call(q, key=KEYS["B"]); base_text, b_model = b["choices"][0]["message"]["content"], b["model"]
s, c = call(q, key=KEYS["C"]); c_text, c_model = c["choices"][0]["message"]["content"], c["model"]
check("B gets the base model", b_model != "rand", b_model)
check("C gets its own adapter by default", c_model == "rand", c_model)
check("C's answer differs from the base model's", c_text != base_text, f"{c_text[:40]!r} vs {base_text[:40]!r}")

# Prefix cache: B repeats a long prompt (hits), A sends the same prompt (must not hit B's cache).
long = f"{secrets.token_hex(8)} " + "Invoice line for carton 42. " * 300 + "How many lines?"


def hits(tenant):
    h0 = metric("vllm:prefix_cache_hits_total")
    s, _ = call(long, key=KEYS[tenant], max_tokens=1)
    return int(metric("vllm:prefix_cache_hits_total") - h0)


b1, b2, a1 = hits("B"), hits("B"), hits("A")
check("B's repeat is served from B's cache", b2 > 0, f"{b2} hit tokens (first send {b1})")
check("A sending B's prompt gets none of B's cache", a1 == 0, f"{a1} hit tokens")
print(f"{sum(checks)} of {len(checks)} pass")
