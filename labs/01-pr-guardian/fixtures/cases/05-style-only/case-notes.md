# 05 — Style only (human ground truth)

> For the lab participant only. PR Guardian tools cannot read this file.

## Expected outcome

**Zero findings.** The summary may mention that the change is stylistic.

## What changed

- The loop became a list comprehension, and the accumulator loop became `sum(...)`.
- `.format()` became an f-string, and single quotes became double quotes.
- Type hints were added, and `total` was renamed to `total_units`.

## Why there is no defect

- Output order is preserved (a comprehension iterates in the same order).
- `sum([])` is `0`, the same as the old loop on empty input.
- All 4 tests pass.

## Likely false positives (each one counts against the reviewer)

- "`list[dict]` is too loose; use a TypedDict/dataclass". Subjective preference.
- "Missing docstrings on functions". Style, and unchanged by this PR.
- "Negative quantities are counted as low stock". Pre-existing behavior, not introduced here.
- "Comprehension is less readable than the loop". Opinion.

A reviewer that reports any of these as a finding is manufacturing work.

## Verification

Checked in a scratch script: before and after versions return identical
results on 20,000 random inputs, including empty lists, negative quantities
and custom thresholds.
