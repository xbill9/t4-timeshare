#!/bin/bash
# M1 through the gateway: fresh ledger, flood phase, then the bill and ledger check.
# Needs vLLM up with --scheduling-policy priority (day1/serve_lora.sh ... --scheduling-policy priority).
set -e
cd "$(dirname "$0")/.."
rm -f day3/ledger.m1.jsonl
gateway/target/release/t4-gateway gateway/tenants.toml day3/ledger.m1.jsonl > day3/gateway.m1.log 2>&1 &
gw=$!; trap 'kill $gw' EXIT; sleep 1
python3 day3/m1_gateway.py day3/m1_gateway.json 2>&1 | tee day3/m1_gateway.out
python3 day3/bill.py day3/ledger.m1.jsonl --run day3/m1_gateway.json | tee day3/bill.m1.out
