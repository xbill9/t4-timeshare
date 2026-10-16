"""Monthly on-demand cost of the VM (n1-standard-2: 2 vCPU, 7.5 GiB, plus one T4) from the prices in
day3/pricing.us-west2.txt (Cloud Billing Catalog API). Boot disk and network egress are not included.
usage: python3 day3/monthly_cost.py [hours_per_month]
"""
import re, sys
HOURS = float(sys.argv[1]) if len(sys.argv) > 1 else 730
p = {}
for line in open("day3/pricing.us-west2.txt"):
    m = re.search(r"(Tesla T4 GPU|Instance Core|Instance Ram).*?([\d.]+) USD", line)
    if m: p[m.group(1)] = float(m.group(2))
hourly = p["Tesla T4 GPU"] + 2 * p["Instance Core"] + 7.5 * p["Instance Ram"]
print(f"T4 {p['Tesla T4 GPU']:.6f} + 2 vCPU x {p['Instance Core']:.6f} + 7.5 GiB x {p['Instance Ram']:.6f} = {hourly:.4f} USD/hour")
print(f"x {HOURS:g} hours = {hourly * HOURS:.2f} USD/month")
