# Day-1 results

T4 on debian13 (n1-standard-2), vLLM 0.29.0, `xbill9/gemma-4-E2B-it-qat-q4_0-w4a16-ct-text-emb4`,
`--max-num-seqs 8`, `--enable-lora --max-loras 2 --max-lora-rank 8`, no drafter. Started with
`day1/serve_lora.sh`. Every figure below is printed by the script named next to it.

| Check | Result | Evidence |
|---|---|---|
| LoRA on QAT w4a16, SM 7.5 | Works per request. Zero adapter = base output, 40 of 40 tokens. Random adapter differs from token 1. 6 of 6 requests in one mixed batch match their solo output. | `lora_check.out` |
| Per-tenant cache salt | Works. Salt A repeat: 1216 of 1217 tokens from cache. Salt B and no salt after salt A: 0. | `live_checks.lora-nodrafter.out` |
| `usage` on streamed responses | Present in one chunk with `stream_options.include_usage`, absent without it. The gateway must set it. | `live_checks.lora-nodrafter.out` |
| Priority scheduling | Works. `--scheduling-policy priority`: high-priority request finished first, at 17.48 s, ahead of three low-priority requests queued before it. FCFS, same workload: high finished last, at 20.39 s. Under FCFS the `priority` field is accepted and ignored. | `priority_check.priority.out`, `priority_check.fcfs.out` |
| Host RAM with LoRA | Fits. Peak EngineCore RSS 2,457,232 KB, peak swap used 2,338,840 KB of 16 GB, MemAvailable never below 2,714,836 KB. The swapfile is not in fstab and was off after a reboot; `vllm-t4 swap` turns it on. | `rss.priority.log`, `rss.fcfs.log` (and the 3-hour `rss.log`: peak engine RSS 3,155,520 KB, swap 1,940,148 KB) |

`rss.lora-nodrafter.log`: its `engine_rss_kb` column is a different process (3.2 MB from before the
server loaded). `serve_lora.sh` now matches only the EngineCore child of the server it started.

## Prefill cost (sets the bucket weight)

`prefill_cost.py`, one request at a time, 5 requests per length, every prompt starting with a random
tag; 0 prefix-cache hit tokens across all 30 requests.

| Prompt tokens | Median time, max_tokens=1 |
|---:|---:|
| 256 | 106.9 ms |
| 512 | 262.0 ms |
| 1024 | 730.8 ms |
| 2048 | 2,180.8 ms |
| 4096 | 7,122.4 ms |
| 8192 | 25,364.0 ms |

Prefill grows with the square of the prompt: fit `-12.8 ms + 374.32 us x n + 336.9989 ns x n^2`,
within 2.1% of all 30 requests. Decode: 9.34 ms per output token (median of 5).

So a flat weight per prompt token is wrong. In output tokens of decode time, one prompt token costs
0.044 at 256 tokens, 0.113 at 2048, 0.187 at 4096 and 0.335 at 8192. A 4096-token prompt costs as
much GPU time as 767.8 output tokens. The bucket charge becomes `(a + b*n + c*n^2) / decode_time +
max_tokens` with the fitted constants in `prefill_cost.json`. Measured one request at a time; under
a full batch the ratio is unmeasured.
