# t4-timeshare: one T4, several small customers

Entry for the [Hacktoberfest Open-Source AI Challenge, Week 2: Side Hustle](https://dev.to/challenges/hacktoberfest-week2-2026-10-12).

One Tesla T4 serving Gemma 4 E2B to several small customers at once. A Rust gateway gives each
customer an API key, a fair share of the GPU, its own adapter and a bill computed from metered tokens.

Status: spec only. See [`SPEC.md`](SPEC.md).

## Repo layout

| Path | What |
|---|---|
| `SPEC.md` | What is being built, what gets measured, and the schedule |
| `RULES-week2.md`, `TEMPLATE-week2.md` | Challenge rules and submission template, saved for offline use |

## Challenge notes

Project started 2026-10-13, inside the challenge window. Any commit made after the deadline
(2026-10-18 23:59 PDT) will be listed here, as the rules require.

## License

Apache 2.0. Gemma models are subject to Google's Gemma terms.
