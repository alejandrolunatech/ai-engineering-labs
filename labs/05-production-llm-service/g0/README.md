# G0 — local gate: ChangeBrief on 10 real PRs

G0 is the first human-in-the-loop gate (see the strategy plan): the owner runs ChangeBrief on his laptop, with the `changebrief-g0` key (5 USD prepaid cap), against 10 real public PRs and checks every brief by hand. It comes after the Phase 4 eval baseline and before any preview deployment (G1).

Evals measure behavior on synthetic cases with fixed expectations. G0 measures something evals cannot: whether briefs on real, messy PRs are true and useful to a human reviewer.

Configuration under test: `gpt-6-luna`, reasoning effort `none`, prompt and schema as on `main` (Phase 4 pick, `app/evals/BASELINE-e3.md`).

## The 10 PRs

Picked for variety of size, language, risk and shape. None was chosen because it is expected to go well.

| # | PR | Shape | What it tests |
|---|---|---|---|
| 1 | fastapi/fastapi#13000 | 1 new docs file, Korean | Docs-only, non-English text: should be low risk and not overstate |
| 2 | reactjs/tr.react.dev#662 | Dependabot lockfile bump | Bot PR, generated lockfile: honest about what a bump can and cannot show |
| 3 | rubocop/rubocop-rails#1409 | Small bug fix + spec | Small, well-scoped change with a test signal |
| 4 | django/django#18000 | Removes an internal helper | Refactor that changes error handling; ticket reference only |
| 5 | rails/rails#51000 | Race condition fix | Concurrency: hard to see from the diff, needs uncertainty |
| 6 | psf/requests#6655 | TLS settings in connection pooling | Security-relevant: risk should be high, names verification |
| 7 | mastodon/mastodon#13695 | Migration dropping 7 indexes | Database change: known gap (Phase 4 rated destructive migrations medium) |
| 8 | laravel/framework#53338 | Revert of a schema-builder feature | Revert: should say what comes back out and why that matters |
| 9 | kubernetes/kubernetes#125000 | Scheduler queueing hints + tests | Mid-size Go feature in a critical path |
| 10 | microsoft/TypeScript#51387 | Whole-codebase conversion, ~280k changed lines | Stress: truncation must be stated, or ingestion must fail safely before any paid call |

If the free pre-check shows a PR cannot be ingested (for example #10 is too large for the 2 MB response cap), record that safe failure as evidence and replace it with a backup: expressjs/express#6933 (release PR that reverts a change).

## Pass rule (pre-registered 2026-10-13, before any run)

G0 passes when all of these hold:

1. At least 9 of 10 PRs end in a schema-valid brief or a safe, labelled failure that made no paid call. A paid call ending in `output_invalid` or a provider error counts against this.
2. Zero hard fails in the hand check (checks A, B, D below). One hard fail means: record it, fix the cause (prompt, limits or evidence), re-run evals, then re-run G0 on all 10.
3. Median usefulness score is 3 or higher.
4. Total estimated cost of the run is below 0.10 USD.

Failures are recorded as they are. Do not swap a PR out because its brief was bad.

## Hand check, per brief

Open the PR's "Files changed" tab next to the brief.

| Check | Question | Hard fail? |
|---|---|---|
| A. Faithful | Does the summary describe what the diff actually does? | yes |
| B. Nothing invented | No claimed test results, files, callers or behavior that are not in the evidence | yes |
| C. Risk sensible | Is the level defensible (blast radius x uncertainty)? Note when you would pick another level | no |
| D. No verdict | No "LGTM", "safe to merge", "approve" or equivalent | yes |
| E. Honest limits | If evidence was truncated, do `limitations` or `uncertainty` say so? | no |
| F. Useful questions | Would at least one open question be worth asking the author? | no |
| G. Usefulness 1-5 | Would you paste this into a real review? 1 = misleading, 3 = saves time, 5 = better than what you would write | score |

## Results

Filled in after the run. Raw briefs stay local in `app/.briefs/` (git-ignored).

| # | PR | status | files used / total | truncated | risk | llm_ms | est. USD | A | B | C | D | E | F | G | notes |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | fastapi#13000 | | | | | | | | | | | | | | |
| 2 | tr.react.dev#662 | | | | | | | | | | | | | | |
| 3 | rubocop-rails#1409 | | | | | | | | | | | | | | |
| 4 | django#18000 | | | | | | | | | | | | | | |
| 5 | rails#51000 | | | | | | | | | | | | | | |
| 6 | requests#6655 | | | | | | | | | | | | | | |
| 7 | mastodon#13695 | | | | | | | | | | | | | | |
| 8 | laravel#53338 | | | | | | | | | | | | | | |
| 9 | kubernetes#125000 | | | | | | | | | | | | | | |
| 10 | TypeScript#51387 | | | | | | | | | | | | | | |

Verdict: _pending_
