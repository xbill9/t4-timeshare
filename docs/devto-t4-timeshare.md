---
title: "Renting Out One T4 to Three Customers: Gemma 4, vLLM Multi-LoRA and a Rust Gateway"
published: false
description: "One Tesla T4 serving Gemma 4 E2B to three paying tenants. A 245-line Rust gateway gives each one a key, its own adapter, a priority and a private cache, and bills them by GPU time from a ledger that matches vLLM's counters to the token."
tags: devchallenge, hf26challenge, gemma, rust
cover_image: https://raw.githubusercontent.com/xbill9/t4-timeshare/main/docs/devto-cover.248ace7f.jpg
---

*This is a submission for the [Hacktoberfest Open-Source AI Challenge Week 2: Side Hustle](https://dev.to/challenges/hacktoberfest-week2-2026-10-12)*

This article provides a step by step guide to renting out one NVIDIA T4 on a Google Cloud VM to several small customers at once, with Gemma 4 E2B served by vLLM and a small Rust gateway in front. Every log, script and number is committed.

https://github.com/xbill9/t4-timeshare

**One customer sending 4,000-token prompts pushes everyone else's first token from 0.28 s to 29.90 s on a shared T4. vLLM's priority scheduling brings that back to 6.52 s. The gateway adds what turns a shared GPU into a business: keys, a fine-tune per customer that no one else can call, a prefix cache per customer, and a ledger that matched vLLM's own token counters exactly. Billed by GPU time, the long-prompt customer pays 27.2% of the VM for 22.0% of the tokens.**

---

## What I Built

A small AI job costs too much either way. A GPU of your own sits idle most of the day. A per-token API bill grows with every customer you add, and every prompt leaves your building.

The side hustle is the middle: one person rents one T4, and sells shares of it to a few small businesses at a flat monthly price. Each customer gets:

- an API key that works with any OpenAI client
- its own fine-tuned adapter on the shared base model, callable by that customer only
- a prefix cache that other customers cannot read through response timing
- a bill computed from metered tokens, weighted by what each token costs the GPU

The operator gets one config file and a ledger.

The three demo tenants are picked so each one loads the T4 differently:

| Tenant | Job | Shape |
| :--- | :--- | :--- |
| A | Summarise long daily logs | Few requests, 4,096-token prompts |
| B | Triage short support emails | One 512-token request every 2 s |
| C | Tag product rows, with its own adapter | One 512-token request every 2 s |

---

## Demo

The gateway listens on port 8080 and speaks the OpenAI chat API. `day3/demo.sh`, run with `bash -v`:

```text
curl -s localhost:8080/v1/chat/completions -H "Authorization: Bearer demo-key-B" \
  -d '{"messages":[{"role":"user","content":"Label this email: my parcel arrived broken"}],"max_tokens":20}' \
  | jq -c '{model, usage: .usage.total_tokens}'
{"model":"xbill9/gemma-4-E2B-it-qat-q4_0-w4a16-ct-text-emb4","usage":37}
curl -s localhost:8080/v1/chat/completions -H "Authorization: Bearer demo-key-C" \
  -d '{"messages":[{"role":"user","content":"Label this email: my parcel arrived broken"}],"max_tokens":20}' \
  | jq -c '{model, usage: .usage.total_tokens}'
{"model":"rand","usage":26}
curl -s localhost:8080/v1/chat/completions -H "Authorization: Bearer demo-key-B" \
  -d '{"model":"rand","messages":[{"role":"user","content":"hi"}]}' -w ' %{http_code}\n'
{"error":"adapter belongs to another tenant"} 403
curl -s localhost:8080/v1/chat/completions -d '{"messages":[{"role":"user","content":"hi"}]}' -w ' %{http_code}\n'
{"error":"missing or unknown key"} 401
tail -4 ledger.jsonl
{"completion_tokens":20,"model":"xbill9/gemma-4-E2B-it-qat-q4_0-w4a16-ct-text-emb4","prompt_tokens":17,"queue_ms":0.0006799999999999999,"status":200,"tenant":"B","total_ms":355.14126200000004,"ts":1792165075.2638927}
{"completion_tokens":9,"model":"rand","prompt_tokens":17,"queue_ms":0.000778,"status":200,"tenant":"C","total_ms":498.805413,"ts":1792165075.7809048}
{"refused":"adapter belongs to another tenant","status":403,"tenant":"B","ts":1792165075.7979941}
{"refused":"missing or unknown key","status":401,"tenant":null,"ts":1792165075.8125255}
```

The same request from B and C reaches two different models: B gets the base model, C gets its adapter without naming it. B asking for C's adapter is refused, and so is a request with no key. Every one of the four lands in the ledger.

---

## Code

https://github.com/xbill9/t4-timeshare

| Path | What |
| :--- | :--- |
| `gateway/src/main.rs` | The gateway, 245 lines of Rust (axum, reqwest, tokio) |
| `gateway/tenants.toml` | Keys, adapters, priorities and in-flight caps |
| `day1/` | Checks on the T4 before building: LoRA, cache salt, streamed usage, priority, prefill cost |
| `day2/` | The noisy-neighbour test straight to vLLM |
| `day3/` | The same test through the gateway, isolation checks, the bill and VM pricing |

---

## How I Built It

#### At This Point You Should Have…

- A Google Cloud VM with one NVIDIA T4. This one is an `n1-standard-2` in `us-west2-b`
- vLLM 0.29.0 serving `xbill9/gemma-4-E2B-it-qat-q4_0-w4a16-ct-text-emb4`, Gemma 4 E2B with Google's quantization-aware 4-bit weights, fp16, at most 8 sequences at once
- Rust, for the gateway
- A clone: `git clone https://github.com/xbill9/t4-timeshare`

---

#### Step 1 — Check the Engine Can Do Multi-Tenant Work

Four features decide whether one vLLM can serve several paying customers. Each was checked on the T4 before any gateway code was written (`day1/RESULTS.md`):

| Check | Result |
| :--- | :--- |
| LoRA adapters on the 4-bit weights, Turing GPU | 🟢 A zero adapter returns the base model's output, 40 of 40 tokens. A random adapter differs from token 1. 6 of 6 requests in one mixed batch match their solo output. |
| Per-request prefix-cache salt | 🟢 Same salt, repeat: 1,216 of 1,217 tokens from cache. Different salt: 0. |
| Token usage on streamed responses | 🟢 Present with `stream_options.include_usage`, absent without it. The gateway sets it. |
| Priority scheduling | 🟢 With `--scheduling-policy priority`, a high-priority request queued last finished first. |

The 6 of 6 is what makes per-customer fine-tunes cheap: requests for different adapters share one batch on one GPU, and each still gets its own model's answer.

---

#### Step 2 — Measure What Hurts on a T4

A customer's request costs the GPU in two parts: reading the prompt (prefill) and writing the answer (decode). `day1/prefill_cost.py` times prefill alone, one request at a time, 5 per length, with the prefix cache unable to help:

```text
prompt ~  256: median    106.9 ms  min    103.4  max    108.7
prompt ~  512: median    262.0 ms  min    258.9  max    267.9
prompt ~ 1024: median    730.8 ms  min    717.0  max    737.4
prompt ~ 2048: median   2180.8 ms  min   2149.6  max   2223.6
prompt ~ 4096: median   7122.4 ms  min   7050.4  max   7363.7
prompt ~ 8192: median  25364.0 ms  min  25261.6  max  25697.8
prefill fit over 30 requests: -12.8 ms + 374.32 us x n + 336.9989 ns x n^2; worst error 2.1%
decode: median 9.34 ms per output token over 5 pairs (256 tokens minus 1 token, same length prompt)
```

Prefill grows with the square of the prompt. One 4,096-token prompt costs as much GPU time as 767.8 output tokens. On a T4 the customer who hurts the others is the one with long prompts, more than the one with many requests.

---

#### Step 3 — Watch One Customer Stall the Others

`day2/m1_direct.py` runs the three tenants straight against vLLM. B and C each send one 512-token request every 2 seconds and stream 64 tokens back. For 180 seconds, A keeps four 4,096-token summaries in flight. Every prompt starts with a random tag, so nothing comes from cache.

First come, first served, every request in the same queue:

```text
[quiet] B: 90/90 ok  first token median    0.29 s  95th    0.29 s  max    0.34 s | total median    0.98 s  95th    0.99 s
[flood] A: 16/16 ok  first token median   30.82 s  95th   45.37 s  max   46.12 s | total median   50.08 s  95th   54.03 s
[flood] B: 90/90 ok  first token median   29.78 s  95th   44.47 s  max   47.81 s | total median   35.07 s  95th   48.91 s
```

A support-email triage that answered in a third of a second now waits half a minute for its first word. B pays for A's prompts.

---

#### Step 4 — Put the Gateway in Front

`gateway/src/main.rs` does six things per request, in order:

1. **Key to tenant.** `Authorization: Bearer <key>` looks the tenant up in `tenants.toml`. No key or an unknown one: 401.
2. **Model check.** The tenant gets its own adapter by default, or the base model on request. Another tenant's adapter: 403.
3. **Priority.** The tenant's priority goes into the request body, overwriting whatever the client sent.
4. **Cache salt.** `cache_salt` is set to the tenant's name, so cached prompts are shared within a tenant and never across tenants.
5. **In-flight cap.** The request waits for one of the tenant's slots, a `tokio` semaphore per tenant.
6. **Ledger.** When the response ends, or the client disconnects, one JSON line is written with the tenant, the model, the status, vLLM's own prompt and output token counts, the time spent waiting for a slot and the total time.

The demo tenants:

```toml
[[tenant]]
name = "A"
key = "demo-key-A"
max_inflight = 1
priority = 10

[[tenant]]
name = "C"
key = "demo-key-C"
adapter = "rand"
max_inflight = 8
priority = 0
```

A has one slot and runs last. B and C have 8 slots each, the most vLLM runs at once. C's `rand` adapter is a random rank-8 LoRA from `day1/make_adapters.py`, standing in for a customer's fine-tune.

Streaming responses pass straight through. The gateway watches the stream for the one chunk that carries `usage` and records it when the stream ends. A request that dies halfway is still in the ledger, and its slot is released at that moment.

---

#### Step 5 — Check Isolation

```shell
python3 day3/isolation.py
```

```text
PASS  no key: 401
PASS  unknown key: 401
PASS  B asks for C's adapter: 403
PASS  B asks for a model that is not served: 404
PASS  B gets the base model: xbill9/gemma-4-E2B-it-qat-q4_0-w4a16-ct-text-emb4
PASS  C gets its own adapter by default: rand
PASS  C's answer differs from the base model's: 'Here are a few examples of how a spare G' vs 'Here are three common uses for a spare G'
PASS  B's repeat is served from B's cache: 2400 hit tokens (first send 0)
PASS  A sending B's prompt gets none of B's cache: 0 hit tokens
9 of 9 pass
```

The last two lines are the privacy check. When B sends a long prompt twice, the second send is served from cache. A sends the identical prompt and gets nothing from B's cache, so A cannot tell from response time whether B ever sent it. The hit counts come from vLLM's `/metrics`, not from timing.

---

#### Step 6 — Rerun the Noisy Neighbour Through the Gateway

```shell
day3/run_m1.sh
python3 day3/compare.py
```

```text
run                                   B+C first token median    95th     max  B+C done  A done
quiet, no A (direct)                                  0.28 s  0.29 s  0.37 s       180       0
direct, first come first served                      29.90 s 44.49 s 47.81 s       180      16
direct, A at low priority                             6.52 s 14.71 s 16.31 s       180      16
gateway: priority + A capped at 1                     7.06 s 12.11 s 13.55 s       180       7
```

Priority does most of the work: B and C's median wait falls from 29.90 s to 6.52 s. Capping A at one request shortens the worst waits, from 14.71 s to 12.11 s at the 95th percentile. A pays for it, finishing 7 summaries in the window against 16.

B and C still wait about 7 s, close to one 4,096-token prefill (7.1 s in Step 2). A request that arrives while A's prompt is being read waits for that read to finish.

🔎 **Tip: size the cap above what the tenant needs.** B sends a request every 2 seconds and each one spends about 12 seconds on the GPU under load, so B needs about 6 slots. With B capped at 4, the same run gave B a median time inside vLLM of 11.61 s and a median wait for a gateway slot of 37.77 s (`day3/cap4/`). A cap is for the customer you want to slow down.

---

#### Step 7 — Check the Ledger Against vLLM

A bill is only as good as its meter. `day3/bill.py` adds up the ledger and compares it with vLLM's own `prompt_tokens_total` and `generation_tokens_total` counters, read before and after the run:

```text
ledger vs vLLM counters: prompt 122,442 vs 122,442, output 12,416 vs 12,416; match: True
```

Every token vLLM processed in the run is attributed to a tenant, and no tenant is charged for a token vLLM did not process.

---

#### Step 8 — Send the Bill

The VM's on-demand price comes from the Cloud Billing Catalog API, fetched during the build (`day3/pricing.us-west2.txt`):

```text
T4 0.410000 + 2 vCPU x 0.037970 + 7.5 GiB x 0.005089 = 0.5241 USD/hour
x 730 hours = 382.60 USD/month
```

`bill.py` prices each request in GPU seconds, using the prefill fit from Step 2 plus 9.34 ms per output token, and splits the month by each tenant's share. Over the gateway run:

```text
tenant   requests refused  prompt tok  output tok token share     GPU s GPU share  bill USD
A               7       0      28,718         896       22.0%      58.7     27.2%    104.22
B              90       0      46,803       5,760       39.0%      78.4     36.4%    139.11
C              90       0      46,921       5,760       39.1%      78.5     36.4%    139.26
```

A sent 22.0% of the tokens and used 27.2% of the GPU. A flat price per token would undercharge the long-prompt customer and pass the difference on to the other two. Weighting prompt tokens by their measured prefill cost puts it back.

---

#### Compare and Contrast

| | Straight to vLLM | vLLM with priority | Through the gateway |
| :--- | :--- | :--- | :--- |
| B and C, median first token under load | 29.90 s | 🥈 6.52 s | 🥇 7.06 s |
| B and C, 95th percentile | 44.49 s | 🥈 14.71 s | 🥇 12.11 s |
| Keys per customer | ❌ | ❌ | 🟢 |
| Adapter only its owner can call | ❌ | ❌ | 🟢 |
| Prefix cache per customer | ❌ | ❌ | 🟢 |
| Per-customer bill, checked against vLLM | ❌ | ❌ | 🟢 |

---

#### So, Which One?

Turn on `--scheduling-policy priority` for any shared vLLM: on these runs it is the single biggest change, and it costs one flag. Selling the GPU takes the gateway, because priority alone still lets any client claim any priority, call any adapter and read any cache. The gateway sets all three from the key.

---

#### Prior Work

- **The T4 rig**: the VM, vLLM 0.29.0 install, Turing patch and the `vllm-t4` script come from my earlier `gemma4-dev` T4 serving work.
- **[gemma-rust](https://github.com/xbill9/gemma-rust)**: reqwest client patterns for the OpenAI-compatible endpoint.
- **[dev-hacktoberfest](https://github.com/xbill9/dev-hacktoberfest)** (Week 1): every result checked by code that did not produce it.
- **Open source used**: [vLLM](https://github.com/vllm-project/vllm) (Apache 2.0), Gemma 4 E2B (Gemma terms), [axum](https://github.com/tokio-rs/axum), [reqwest](https://github.com/seanmonstar/reqwest), [tokio](https://github.com/tokio-rs/tokio).

---

## Why Does Open Innovation Matter?

Every part of this business needs the weights.

- **The model runs on hardware the operator controls.** That is possible only with downloadable weights, and it is what lets the operator promise a customer that its emails never reach a model vendor.
- **One base model, one small adapter per customer.** Per-customer fine-tunes that share one GPU and one batch need the weights and an engine that serves adapters side by side. vLLM's multi-LoRA does that on a 2018-era T4.
- **The cost is flat.** The operator pays 382.60 USD a month whatever the customers send. A heavy customer costs the others waiting time, which the scheduler controls, and costs the operator nothing extra.
- **Everything can be checked.** Engine, gateway and model are open, so the cache isolation and the bill are tested against vLLM's own counters, and a customer can read the code that bills them.

---

## Prize Categories

**Gemma**: Gemma 4 E2B, served locally on a T4 with vLLM, with per-customer LoRA adapters on Google's quantization-aware 4-bit weights.

---

## Summary

The goal of this project was to sell shares of one T4 to several small customers without one customer ruining the service for the others. The key to the solution was vLLM's priority scheduling, adapters and cache salt, controlled per customer by a gateway that holds the keys. The results were:

- 🟢 A long-prompt customer pushed other customers' first token from 0.28 s to 29.90 s. Priority brought it to 6.52 s; the gateway's cap on that customer brought the 95th percentile from 14.71 s to 12.11 s.
- 🟢 9 of 9 isolation checks pass: keys, adapter ownership and a prefix cache per customer.
- 🟢 The ledger matched vLLM's token counters exactly: 122,442 prompt and 12,416 output tokens.
- 🟢 A per-adapter customer runs in the same batch as base-model customers, at about the same speed.
- ⚠️ B and C still wait about one long prefill, around 7 s, while A is active. Chunking long prompts further, or giving A its own hours, are the next steps.
- ❌ A's throughput falls from 16 summaries to 7 in the window. That is the price A pays for a cheaper share.

Scope: one T4 on one Google Cloud VM, vLLM 0.29.0, one 180-second run per configuration. The two direct runs and the gateway run used separate server starts with the same flags; in the direct runs C used the base model, through the gateway it used its adapter. The token bucket, the per-customer fair queue and a tenant-count sweep from `SPEC.md` are not built. The VM price excludes disk and network.

The strategy for renting out one T4 to several customers with Gemma 4 and vLLM was validated with an incremental step by step approach.

---

#### References

- [Hacktoberfest Open-Source AI Challenge, Week 2](https://dev.to/challenges/hacktoberfest-week2-2026-10-12)
- [t4-timeshare on GitHub](https://github.com/xbill9/t4-timeshare)
- [vLLM](https://github.com/vllm-project/vllm)
- [Gemma 4 E2B, 4-bit build used here](https://huggingface.co/xbill9/gemma-4-E2B-it-qat-q4_0-w4a16-ct-text-emb4)
- [Google Cloud GPU pricing](https://cloud.google.com/compute/gpus-pricing)
