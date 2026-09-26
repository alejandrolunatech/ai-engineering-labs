# 04 — Clean refactor (human ground truth)

> For the lab participant only. PR Guardian tools cannot read this file.

## Expected outcome

**Zero findings.** The summary should say the change is a behavior-preserving refactor.

## What changed

- `_round_to_cents()` is extracted from duplicated `quantize(..., ROUND_HALF_UP)` code.
- `apply_member_discount` now delegates to `apply_percentage_discount`.
- The tier dict became the `MEMBER_DISCOUNT_PERCENT` constant.
- A test pins half-up rounding for member discounts.

## Why it is clean

- The arithmetic is identical: same `Decimal` expression, same rounding mode.
- Delegating adds the `0..100` range check to member discounts, but tier
  percentages are 0/5/10, so this can never raise. Behavior is unchanged.
- All 7 tests pass.

## Likely false positives (each one counts against the reviewer)

- "Percent validation is missing". It exists, and the code predates this PR.
- "Unknown tiers silently get 0%". That's existing behavior, not introduced here.
- "`MEMBER_DISCOUNT_PERCENT` is a mutable module-level dict". Style / speculative.
- "The validation raises for member discounts now". It can't with the current tiers.

## Verification

Checked in a scratch script: before and after versions return identical
results (including `ValueError` messages) on 20,000 random inputs for both functions.
