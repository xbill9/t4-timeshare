"""Split each tenant's request time into waiting for a gateway slot and time inside vLLM, from a ledger.
usage: python3 day3/queue_split.py <ledger.jsonl>
"""
import json, statistics as st, sys
rows = [json.loads(l) for l in open(sys.argv[1]) if l.strip()]
for t in sorted({r["tenant"] for r in rows if r.get("tenant") and "refused" not in r}):
    r = [x for x in rows if x.get("tenant") == t and "refused" not in x]
    q = [x["queue_ms"] / 1e3 for x in r]; g = [(x["total_ms"] - x["queue_ms"]) / 1e3 for x in r]
    print(f"{t}: {len(r)} requests  gateway slot wait median {st.median(q):.2f} s max {max(q):.2f} s"
          f"  |  inside vLLM median {st.median(g):.2f} s max {max(g):.2f} s")
