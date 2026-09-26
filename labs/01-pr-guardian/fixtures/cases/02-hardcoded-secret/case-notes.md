# 02 — Hardcoded secret (human ground truth)

> For the lab participant only. PR Guardian tools cannot read this file.

The credential `mr_live_EXAMPLEFAKE7c1d2e3f4a5b6c7d8e9f0a1b` is **synthetic**.
"Mailroute" and `api.mailroute.example` are fictional (`.example` is a reserved
TLD). The value matches no real provider's key format.

## Expected outcome

**Exactly one real defect.**

| Field | Expected |
|---|---|
| file | `src/notifications/mailer.py` |
| line | 11 (`_DEFAULT_API_KEY = "mr_live_..."`) |
| severity | `high` or `critical` |
| issue | A live-looking API key is committed to source control as a fallback. |
| impact | Anyone with repository access gets the credential. Environments that forget to set the variable silently send production email with a shared key instead of failing fast. |
| evidence | The literal key in the diff; the `live` prefix; the comment "Shared key so local development works". |
| fix | Remove the literal and revoke/rotate the key. Keep failing fast when `MAILROUTE_API_KEY` is missing, or use a clearly non-functional dev/sandbox mode. |

## Why it matters

- Both tests pass; `test_works_without_environment_key` actually depends on the secret.
- The PR has a sympathetic motive (onboarding friction).

## Acceptable extras

- A note that the test should not rely on the embedded default.

## False positives

- Using `urllib` instead of an HTTP library; dataclass style.

## Judgment call

A reviewer that says "looks like a fake/example key, so no issue" is **wrong**.
Reviewers can't reliably tell real keys from example keys, and the pattern of
committing a fallback credential is the defect.
