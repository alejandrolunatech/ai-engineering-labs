# 03 — Null handling (human ground truth)

> For the lab participant only. PR Guardian tools cannot read this file.

## Expected outcome

**Exactly one real defect.**

| Field | Expected |
|---|---|
| file | `src/hr/leave_requests.py` |
| line | 28 (`cc=[manager.email]`); line 25 is also acceptable |
| severity | `medium` or `high` |
| issue | `directory.find_manager()` returns `Employee | None`, but the result is dereferenced without a check. |
| impact | `AttributeError: 'NoneType' object has no attribute 'email'` when a top-level employee (no `manager_id`) or an employee whose manager left the directory submits leave. Leave requests fail for these employees. |
| evidence | `find_manager` return type and docstring in `src/hr/directory.py`. |
| fix | `cc=[manager.email] if manager else []`, plus a test for an employee without a manager. |

## Why it is subtle

- Both tests pass: the test employee `e-1` has a valid manager.
- The test directory itself contains `e-3` whose manager `e-9` does not exist.
  The data needed to trigger the crash is already present but never exercised.
- The reviewer must read the *unchanged* `directory.py` to see the `None` contract.

## Acceptable extras

- A `low` note about missing test coverage for the no-manager path
  (ideally merged into the main finding).

## False positives

- Date formatting style, dataclass choices.

## Verification

Checked in a scratch script: a top-level employee and an employee with a
departed manager both raise `AttributeError`.
