# 01 — Duplicate charge (human ground truth)

> For the lab participant only. PR Guardian tools cannot read this file.

## Expected outcome

**Exactly one real defect.**

| Field | Expected |
|---|---|
| file | `src/billing/payments.py` |
| line | 23 (`idempotency_key = f"order-{order.id}-attempt-{attempt}"`) |
| severity | `high` or `critical` |
| issue | Each retry uses a new idempotency key, so the gateway cannot deduplicate retries. |
| impact | A `GatewayTimeout` after the gateway already applied the charge causes a second charge on retry — up to 3 charges per order. |
| evidence | `GatewayTimeout` docstring in `src/billing/gateway.py`: retrying is safe *only* when the same idempotency key is reused. |
| fix | Compute the key once per order (outside the loop); log the attempt number separately. |

## Why it is hard

- All 4 tests pass. `FlakyGateway` never models "timed out but charge applied".
- The new test `test_each_attempt_is_traceable` *asserts the buggy behavior*.
- The PR description makes the change sound like a harmless logging improvement.
- The reviewer must connect the diff with the unchanged `gateway.py` contract.

## Acceptable extras (not false positives)

- A `low` note that the new test pins the per-attempt key format.

## False positives

- Logging style, the `AssertionError("unreachable")` line, the backoff values.

## Verification

Checked in a scratch script with a fake gateway that dedupes by key and
times out after applying the first charge: the order was charged twice
(`order-o-1-attempt-1` and `order-o-1-attempt-2`).
