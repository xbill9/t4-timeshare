"""Per-tenant bill from the gateway ledger, plus a check of the ledger against vLLM's own counters.

Each served request is priced in estimated GPU seconds: prefill time from the day-1 quadratic fit
(day1/prefill_cost.json) plus decode time per output token. A tenant's share of the month's GPU cost
is its share of those seconds. Every figure here is computed; nothing is typed in.

usage: python3 day3/bill.py <ledger.jsonl> [--run day3/m1_gateway.json] [--monthly-usd X]
"""
import argparse, collections, json

ap = argparse.ArgumentParser()
ap.add_argument("ledger"); ap.add_argument("--run"); ap.add_argument("--monthly-usd", type=float)
ap.add_argument("--fit", default="day1/prefill_cost.json")
args = ap.parse_args()

fit = json.load(open(args.fit))
a, b, c = fit["fit_s"]
decode_s = fit["decode_ms_per_token"] / 1e3


def gpu_seconds(prompt, out):
    return a + b * prompt + c * prompt * prompt + decode_s * out


rows = [json.loads(l) for l in open(args.ledger) if l.strip()]
t = collections.defaultdict(lambda: collections.Counter())
for r in rows:
    k = t[r.get("tenant") or "(no key)"]
    if "refused" in r:
        k["refused"] += 1
        continue
    k["requests"] += 1
    k["ok"] += r["status"] == 200
    k["prompt"] += r["prompt_tokens"] or 0
    k["output"] += r["completion_tokens"] or 0
    k["no_usage"] += r["prompt_tokens"] is None
    k["gpu_s"] += gpu_seconds(r["prompt_tokens"] or 0, r["completion_tokens"] or 0)

total_gpu = sum(k["gpu_s"] for k in t.values())
total_tok = sum(k["prompt"] + k["output"] for k in t.values())
hdr = f"{'tenant':8} {'requests':>8} {'refused':>7} {'prompt tok':>11} {'output tok':>11} {'token share':>11} {'GPU s':>9} {'GPU share':>9}"
if args.monthly_usd: hdr += f" {'bill USD':>9}"
print(hdr)
for name in sorted(t):
    k = t[name]
    tok_share = (k["prompt"] + k["output"]) / total_tok if total_tok else 0
    gpu_share = k["gpu_s"] / total_gpu if total_gpu else 0
    line = (f"{name:8} {k['requests']:8d} {k['refused']:7d} {k['prompt']:11,d} {k['output']:11,d} "
            f"{tok_share:11.1%} {k['gpu_s']:9.1f} {gpu_share:9.1%}")
    if args.monthly_usd: line += f" {gpu_share * args.monthly_usd:9.2f}"
    print(line)
missing = sum(k["no_usage"] for k in t.values())
print(f"served requests with no usage reported: {missing}")

if args.run:
    run = json.load(open(args.run))["vllm_tokens"]
    led_p = sum(k["prompt"] for k in t.values())
    led_o = sum(k["output"] for k in t.values())
    print(f"ledger vs vLLM counters: prompt {led_p:,d} vs {run['vllm:prompt_tokens_total']:,d}, "
          f"output {led_o:,d} vs {run['vllm:generation_tokens_total']:,d}; "
          f"match: {led_p == run['vllm:prompt_tokens_total'] and led_o == run['vllm:generation_tokens_total']}")
