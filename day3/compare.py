"""M1 noisy neighbour, flood phase: direct FCFS, direct with priority, and through the gateway.
Percentiles computed from the per-request rows each run saved.
usage: python3 day3/compare.py
"""
import json
RUNS = [("quiet, no A (direct)", "day2/m1_direct.fcfs.json", "quiet"),
        ("direct, first come first served", "day2/m1_direct.fcfs.json", "flood"),
        ("direct, A at low priority", "day2/m1_direct.priority.json", "flood"),
        ("gateway: priority + A capped at 1", "day3/m1_gateway.json", "flood")]


def pct(v, p):
    v = sorted(v); k = (len(v) - 1) * p; f = int(k)
    return v[f] + (v[min(f + 1, len(v) - 1)] - v[f]) * (k - f)


print(f"{'run':36} {'B+C first token median':>23} {'95th':>7} {'max':>7} {'B+C done':>9} {'A done':>7}")
for label, path, phase in RUNS:
    rows = [r for r in json.load(open(path))["rows"] if r["phase"] == phase]
    bc = [r["ttft"] for r in rows if r["tenant"] in "BC" and r["status"] == 200]
    a = sum(1 for r in rows if r["tenant"] == "A" and r["status"] == 200)
    print(f"{label:36} {pct(bc, .5):21.2f} s {pct(bc, .95):5.2f} s {max(bc):5.2f} s {len(bc):9d} {a:7d}")
