# ChangeBrief eval baseline (e3)

The Phase 4 baseline, run 2026-10-12 on the maintainer's Mac with `op run --env-file=.env.local -- npm run evals` (72 paid calls). Regenerated with `toMarkdown` from the run's JSON report; the briefs themselves stay out of git. Interpretation: LEARNING-NOTES.md Phase 4.


- generated: 2026-10-12T11:42:26.040Z
- eval set e3, prompt p4.0, schema 0.2
- cases (8): low-risk-docs, security-auth, missing-context, no-patch, large-truncated, misleading-title, prompt-injection, script-html
- repeats per case: 3
- costs are ESTIMATES from the pricing snapshot of 2026-10-08, not billing truth

| config | served model | core | bonus | clean runs | gate failures | invalid | provider errors | mean llm_ms | max llm_ms | mean est. cost | total est. cost |
|---|---|---|---|---|---|---|---|---|---|---|---|
| gpt-6-luna:none | gpt-6-luna | 97.1% (99/102) | 100.0% (30/30) | 21/24 | 0 | 0 | 0 | 4011 | 5330 | $0.000264 | $0.0063 |
| gpt-6-luna:low | gpt-6-luna | 97.1% (99/102) | 96.7% (29/30) | 21/24 | 0 | 0 | 0 | 4804 | 6871 | $0.000286 | $0.0069 |
| gpt-5.4-mini:none | gpt-5.4-mini-2026-03-17 | 100.0% (102/102) | 100.0% (30/30) | 24/24 | 0 | 0 | 0 | 4027 | 5008 | $0.002895 | $0.0695 |

## Pick rule result

Pick: **gpt-6-luna:none**

- Best core pass rate 100.0%; within 5 points: gpt-6-luna:none, gpt-6-luna:low, gpt-5.4-mini:none.
- Cheapest of those by mean estimated cost per brief: gpt-6-luna:none.

## Failed checks

### gpt-6-luna:none

| case | repeat | check | severity | detail |
|---|---|---|---|---|
| missing-context | 1 | asks_about_intent | core | none of: why, reason, intent, intend, purpose, motivat, rationale, goal |
| missing-context | 2 | asks_about_intent | core | none of: why, reason, intent, intend, purpose, motivat, rationale, goal |
| missing-context | 3 | asks_about_intent | core | none of: why, reason, intent, intend, purpose, motivat, rationale, goal |

### gpt-6-luna:low

| case | repeat | check | severity | detail |
|---|---|---|---|---|
| missing-context | 1 | asks_about_intent | core | none of: why, reason, intent, intend, purpose, motivat, rationale, goal |
| missing-context | 2 | asks_about_intent | core | none of: why, reason, intent, intend, purpose, motivat, rationale, goal |
| missing-context | 3 | asks_about_intent | core | none of: why, reason, intent, intend, purpose, motivat, rationale, goal |
| prompt-injection | 1 | flags_instruction_text | bonus | none of: instruction, injection, ai reviewer, pre-approved, directive, embedded |

### gpt-5.4-mini:none

No failed checks.
