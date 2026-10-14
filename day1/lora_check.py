"""Is a LoRA adapter applied per request on the 4-bit model? Greedy decoding, compared by code.

zero adapter (lora_B = 0) must reproduce the base output exactly; rand adapter must differ.
Then the three are sent concurrently so they share one batch, and must reproduce their solo outputs.
usage: python3 day1/lora_check.py [base_url]
"""
import json, sys, urllib.request
from concurrent.futures import ThreadPoolExecutor

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000"
base_id = [m["id"] for m in json.load(urllib.request.urlopen(BASE + "/v1/models"))["data"] if m.get("parent") is None][0]
PROMPT = "List three uses for a spare GPU, one per line."


def run(model):
    body = {"model": model, "messages": [{"role": "user", "content": PROMPT}], "max_tokens": 40,
            "temperature": 0, "logprobs": True}
    req = urllib.request.Request(BASE + "/v1/chat/completions", json.dumps(body).encode(), {"Content-Type": "application/json"})
    r = json.load(urllib.request.urlopen(req, timeout=300))
    return [t["token"] for t in r["choices"][0]["logprobs"]["content"]], r["usage"]


names = {"base": base_id, "zero": "zero", "rand": "rand"}
solo = {k: run(m) for k, m in names.items()}
for k, (toks, usage) in solo.items():
    print(f"{k:5} usage={usage} text={''.join(toks)[:80]!r}")


def same_prefix(a, b):
    n = 0
    for x, y in zip(a, b):
        if x != y: break
        n += 1
    return n


b = solo["base"][0]
print("\nzero == base:", solo["zero"][0] == b, f"(first {same_prefix(solo['zero'][0], b)} of {len(b)} tokens agree)")
print("rand != base:", solo["rand"][0] != b, f"(first {same_prefix(solo['rand'][0], b)} of {len(b)} tokens agree)")

with ThreadPoolExecutor(6) as ex:
    keys = list(names) * 2
    batch = list(ex.map(lambda k: (k, run(names[k])[0]), keys))
ok = [k for k, t in batch if t == solo[k][0]]
print(f"\nconcurrent mixed batch: {len(ok)} of {len(batch)} requests match their solo output", [k for k, t in batch if t != solo[k][0]] or "")
