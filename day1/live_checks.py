"""Day-1 checks that run against a live vLLM endpoint: streamed usage, cache salt, priority.

usage: python3 day1/live_checks.py [base_url]
Every verdict is computed here from vLLM's own responses and /metrics counters.
"""
import json, sys, urllib.request, urllib.error

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000"
MODEL = json.load(urllib.request.urlopen(BASE + "/v1/models"))["data"][0]["id"]


def post(path, body):
    req = urllib.request.Request(BASE + path, json.dumps(body).encode(), {"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=300) as r:
            return r.status, r.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()


def metric(name):
    """Sum of every sample of a counter in /metrics."""
    total = 0.0
    for line in urllib.request.urlopen(BASE + "/metrics").read().decode().splitlines():
        if line.startswith(name) and not line.startswith("#"):
            total += float(line.rsplit(" ", 1)[1])
    return total


def chat(content, max_tokens=8, **extra):
    return post("/v1/chat/completions", {"model": MODEL, "messages": [{"role": "user", "content": content}],
                                          "max_tokens": max_tokens, "temperature": 0, **extra})


print("model:", MODEL)

# 1. usage on streamed responses
status, body = chat("Say hello.", stream=True, stream_options={"include_usage": True})
chunks = [json.loads(l[6:]) for l in body.splitlines() if l.startswith("data: {")]
usage = [c["usage"] for c in chunks if c.get("usage")]
print("\n[stream usage] status", status, "chunks", len(chunks), "chunks with usage", len(usage))
print("  last usage:", usage[-1] if usage else None)
status, body = chat("Say hello.", stream=True)
chunks = [json.loads(l[6:]) for l in body.splitlines() if l.startswith("data: {")]
print("  without include_usage, chunks with usage:", sum(1 for c in chunks if c.get("usage")))

# 2. cache salt: same long prompt, measure prefix-cache hit tokens per request from /metrics
HITS, QUERIES = "vllm:prefix_cache_hits_total", "vllm:prefix_cache_queries_total"
prompt = "Ledger line. " * 400 + "How many ledger lines are there?"


def hit_tokens(**extra):
    h0, q0 = metric(HITS), metric(QUERIES)
    status, body = chat(prompt, max_tokens=1, **extra)
    assert status == 200, body
    return int(metric(HITS) - h0), int(metric(QUERIES) - q0)


print("\n[cache salt] (hit tokens, queried tokens) per request")
print("  salt=A first  :", hit_tokens(cache_salt="tenant-A-day1"))
print("  salt=A repeat :", hit_tokens(cache_salt="tenant-A-day1"))
print("  salt=B        :", hit_tokens(cache_salt="tenant-B-day1"))
print("  no salt       :", hit_tokens())
print("  no salt repeat:", hit_tokens())

# 3. priority field under the running scheduling policy
status, body = chat("Say hello.", priority=5)
print("\n[priority] priority=5 status", status, body[:200] if status != 200 else "accepted")
