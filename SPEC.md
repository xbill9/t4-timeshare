# t4-timeshare — spec

One Tesla T4, several small customers. Each customer gets an API key, a fair share of the GPU, its own
fine-tune if it wants one, and a flat monthly bill. The side hustle is running the GPU.

Entry for the Hacktoberfest Open-Source AI Challenge, Week 2: Side Hustle (`RULES-week2.md`).
Deadline 2026-10-18 23:59 PDT. Project started 2026-10-13.

---

## Who pays, and for what

| Who | Their problem | What they buy |
|---|---|---|
| **Tenant**: a small business or solo developer with a small, steady AI job (triage support email, tag product rows, summarise a daily log) | A GPU of their own sits idle 95% of the time; a per-token API bill grows with every customer they add | A key, a guaranteed share of one GPU, a flat price, an optional adapter tuned on their own examples, data that never reaches a model vendor |
| **Operator**: the person running the T4 (the side hustler) | One GPU's monthly cost is fixed; it pays off only when several customers share it without hurting each other | The gateway: keys, fair sharing, metering, a bill per tenant |

## Why open weights are the product

- **The model runs on hardware the operator controls.** That is possible only with downloadable weights.
- **One base model, one small adapter per tenant.** Per-customer fine-tunes sharing one GPU need the
  weights and an engine that serves adapters (vLLM multi-LoRA).
- **The cost is flat.** A heavy tenant costs the others waiting time, which a scheduler can control,
  and costs the operator nothing extra. Per-token billing makes every heavy customer a direct cost.
- **Inspectable end to end.** Engine, gateway and model are all open, so isolation can be tested and
  shown, not taken on trust.

---

## Prior work reused (credit every one in the article)

| Source | What is reused |
|---|---|
| `~/gemma4-dev/gpu-vllm-t4-2b` and `-w4a16` (public) | The T4 VM, vLLM 0.29.0 setup, Turing patch, `~/bin/vllm-t4`, and the 2026-09-18 sweep as the single-tenant baseline |
| [gemma-rust](https://github.com/xbill9/gemma-rust) | reqwest client patterns for the OpenAI-compatible endpoint |
| Week 1 [dev-hacktoberfest](https://github.com/xbill9/dev-hacktoberfest) | Independent grader pattern: every result checked by code that did not produce it |
| "Put the arithmetic in the tool" (zombiescan MCP article) | Every count, total, ratio and price in the article computed by code and quoted |

## What the baseline already says (2026-09-18 REPORT.md, QAT w4a16, `--max-num-seqs 8`)

| Input tokens | c | Total out tok/s | Per stream | TTFT |
|---:|---:|---:|---:|---:|
| 512 | 1 | 62.27 | 72.31 | 316 ms |
| 512 | 8 | 215.91 | 37.83 | 1,301 ms |
| 4096 | 1 | 14.00 | 46.18 | 7,243 ms |
| 4096 | 8 | 15.95 | 2.59 | 16,879 ms |

**Prefill is the T4's weak point**: 8x the prompt is 23x the time to first token. So the noisy
neighbour on a shared T4 is the tenant with **long prompts**, more than the one with many requests.
The gateway has to charge prompt tokens accordingly. Caveat carried over: that sweep did not fully
defeat the prefix cache; re-run with `--no-enable-prefix-caching` before quoting prefill figures.

---

## Build

```
tenant key ──► Rust gateway (axum) ──► vLLM (Gemma 4 E2B QAT w4a16, multi-LoRA) on the T4
                 │ key → tenant, adapter
                 │ per-tenant token bucket (cost = weighted prompt + reserved output tokens)
                 │ fair queue across tenants, max in-flight per tenant
                 │ 429 + Retry-After when a bucket is empty
                 └► ledger (SQLite): one row per request, from vLLM's usage field
```

1. **Keys and adapters.** A TOML file maps key → tenant → adapter name (or base model) → bucket
   rate, burst and monthly allowance. A request for another tenant's adapter is refused and logged.
2. **Token bucket charged in model tokens.** Before the request: reserve `w × prompt_tokens +
   max_tokens` (prompt counted with vLLM's `/tokenize`, `w` set from the measured prefill cost).
   After the response: refund the unused output tokens. Clock injected, so tests never sleep.
3. **Fair queue.** At most N requests in flight per tenant, and the next free slot goes to the
   tenant with the fewest tokens in flight. Keeps vLLM's own queue (8 sequences) from filling with
   one tenant's work.
4. **Ledger and bill.** Per-request row: tenant, adapter, prompt and output tokens (from vLLM's
   response), queue wait, TTFT, total time, status. `bill` prints per-tenant totals and the
   operator's cost share; all arithmetic in code.
5. **Cache isolation.** Per-tenant salt on the prefix cache, if vLLM 0.29 supports it, so one
   tenant cannot learn another's prompts from response timing.

## Measurements (each computed by a script, each with raw logs committed)

| # | Question | Method |
|---|---|---|
| M1 | Noisy neighbour | Tenant A floods with 4096-token prompts; B and C send steady 512-token jobs. B's and C's p50/p95 TTFT and completion time: direct to vLLM vs through the gateway. ABBA order, 3 repeats. |
| M2 | How many tenants fit | Add tenants with a fixed workload mix until a target p95 breaks. Report the count and the share of the GPU each gets. |
| M3 | Is the bill right? | Ledger totals per tenant vs vLLM's `/metrics` token counters over the same window. Must match exactly; any gap is a bug. |
| M4 | Isolation | Wrong key, other tenant's adapter, missing key: all refused, all logged. With and without the cache salt, does a timing probe tell whether another tenant sent a prompt? |
| M5 | Does an adapter earn its place? | One tenant's task, base model vs its LoRA, scored by a grader on held-out examples. Optional: train on Tinker for that category. |
| M6 | What a tenant pays | The VM's monthly list price (fetched from the pricing source during the week, cited) divided across the M2 tenant count, next to the same tenants' token volume at public per-token API prices (also fetched and cited). |

## Day-1 checks (all pass; numbers in `day1/RESULTS.md`)

- [x] vLLM 0.29.0 `--enable-lora` with Gemma 4 E2B **QAT w4a16 (Marlin)** on SM 7.5. Fallback: bf16
      build with LoRA, or per-tenant system prompt + output schema with no adapter.
- [x] Per-request prefix-cache salt in vLLM 0.29.0. Fallback: prefix caching off, and say so.
- [x] vLLM priority scheduling flag in 0.29.0 (nice to have; the gateway does fairness either way).
- [x] Host RAM: 7.8 GB plus 16 GB swap with LoRA enabled. Watch EngineCore RSS at load.
- [x] Does `usage` come back on streamed responses (`stream_options.include_usage`)? The ledger needs it.

## Tenants and first users

Three demo tenants, picked so each stresses the T4 differently:

| Tenant | Job | Shape |
|---|---|---|
| A | Summarise long daily logs or reports | Few requests, 4k-token prompts (the prefill hog) |
| B | Triage short support emails into labels | Many requests, short prompts, JSON out |
| C | Nightly batch: tag or describe product rows | Bursts of hundreds of short requests |

Real first users replace the demo tenants where possible: each gets a key and a small real job for
the rest of the week, and their own ledger rows become the "My First User" section (what they ran,
what it would cost them, would they pay, what they asked for next).

## Out of scope

Hosted agent platforms and closed models; multi-GPU and autoscaling; a sign-up UI; payments. Demo
tenants and data are invented for this project.

## What shipped (2026-10-16)

The demo is the minimal slice of the build above: keys, adapter ownership, per-tenant priority and
in-flight cap, per-tenant cache salt, and a JSON-lines ledger reconciled against vLLM's counters.
Not built: the token bucket, the fewest-tokens-in-flight queue, SQLite, and M2, M5 and M6 (the
bill uses the VM's list price only). Results: `day3/`. Article: `docs/devto-t4-timeshare.md`.

## Prize categories

Gemma (featured). Tinker only if M5 trains there and shows a gain over the base model.
