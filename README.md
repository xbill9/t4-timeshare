# t4-timeshare: one T4, several small customers

Entry for the [Hacktoberfest Open-Source AI Challenge, Week 2: Side Hustle](https://dev.to/challenges/hacktoberfest-week2-2026-10-12).

One Tesla T4 serving Gemma 4 E2B to several small customers at once. A Rust gateway in front of vLLM
gives each customer an API key, its own adapter, a priority, a cap on requests in flight, a private
prefix cache, and a bill computed from metered tokens.

Article: [`docs/devto-t4-timeshare.md`](docs/devto-t4-timeshare.md).

## Run it

```shell
day1/serve_lora.sh /opt1/t4-timeshare-adapters --scheduling-policy priority   # vLLM on :8000
cargo build --release --manifest-path gateway/Cargo.toml
gateway/target/release/t4-gateway gateway/tenants.toml ledger.jsonl            # gateway on :8080
python3 day3/isolation.py                                                        # 9 checks
day3/run_m1.sh                                                                   # noisy neighbour + bill
```

## Repo layout

| Path | What |
|---|---|
| `gateway/` | The Rust gateway (`src/main.rs`) and the demo tenants (`tenants.toml`) |
| `day1/` | Checks on the T4: LoRA on 4-bit weights, cache salt, streamed usage, priority, prefill cost |
| `day2/` | Noisy neighbour straight to vLLM, first come first served and with priority |
| `day3/` | Same test through the gateway, isolation checks, the bill, the ledger check, VM pricing |
| `docs/` | The DEV article and its cover |
| `SPEC.md` | The original plan, and what shipped |
| `RULES-week2.md`, `TEMPLATE-week2.md` | Challenge rules and submission template, saved for offline use |

## Challenge notes

Project started 2026-10-13, inside the challenge window. Any commit made after the deadline
(2026-10-18 23:59 PDT) will be listed here, as the rules require.

## License

Apache 2.0. Gemma models are subject to Google's Gemma terms.
