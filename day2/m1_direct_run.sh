#!/bin/bash
# M1 direct-to-vLLM baseline: FCFS run, then a priority-scheduling run with tenant A at low priority.
set -e
cd "$(dirname "$0")/.."
wait_healthy() { for i in $(seq 1 60); do curl -sf http://127.0.0.1:8000/health >/dev/null && return 0; sleep 10; done; return 1; }
wait_healthy
python3 day2/m1_direct.py day2/m1_direct.fcfs.json 2>&1 | tee day2/m1_direct.fcfs.out
~/bin/vllm-t4 stop; sleep 5
RSS_LOG=$PWD/day2/rss.m1-priority.log day1/serve_lora.sh /opt1/t4-timeshare-adapters --scheduling-policy priority
wait_healthy
python3 day2/m1_direct.py day2/m1_direct.priority.json --priority --phases flood 2>&1 | tee day2/m1_direct.priority.out
