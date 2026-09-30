# Lab 05 — Production Release Checklist

Use this checklist for the first public release and meaningful later releases.

## Product

- [ ] Scope is still public GitHub PRs only.
- [ ] User-facing limitations are visible.
- [ ] AI-generated output is labelled.
- [ ] Missing evidence is represented as uncertainty/limitations rather than invented facts.
- [ ] Large/truncated PR behavior is understandable.

## Model

- [ ] Exact OpenAI model ID is recorded.
- [ ] Official model documentation was re-checked near release time.
- [ ] Official pricing was re-checked near release time.
- [ ] Pricing snapshot date/source is recorded.
- [ ] Output token ceiling is configured.
- [ ] Model change has passed evals.
- [ ] No unbounded retry path exists.

## Security / abuse

- [ ] API key exists only server-side.
- [ ] No real secret appears in repository history for this lab.
- [ ] Arbitrary URL fetch is impossible.
- [ ] Public-only GitHub boundary is tested.
- [ ] Prompt-injection fixture passes.
- [ ] XSS-style fixture is safely rendered.
- [ ] Request-size limits are tested.
- [ ] Distributed production rate limiting is enabled.
- [ ] Provider/project spend controls are configured.
- [ ] Kill switch is implemented and tested.
- [ ] Raw PR content, prompt and model output are absent from telemetry.

## Quality

- [ ] Unit tests pass.
- [ ] Integration tests pass with mocked external services.
- [ ] Behavioral eval gate passes.
- [ ] Missing-context evals exist.
- [ ] Oversized/truncated eval exists.
- [ ] Adversarial/prompt-injection eval exists.
- [ ] Structured-output failure test exists.
- [ ] Known limitations are recorded rather than hidden.

## Observability

- [ ] Total latency measured.
- [ ] GitHub latency measured.
- [ ] LLM latency measured.
- [ ] Provider-reported token usage captured when available.
- [ ] Unknown token usage is not recorded as zero.
- [ ] Estimated cost is derived only from matched dated pricing metadata.
- [ ] Estimate is visibly labelled as estimate.
- [ ] Production errors use constrained/redacted categories.
- [ ] Sample logs have been manually reviewed for sensitive/raw source content.

## Deployment

- [ ] CI runs on pull requests/main as designed.
- [ ] Preview deployment works.
- [ ] Production environment variables configured.
- [ ] Production deploy completed.
- [ ] HTTPS works.
- [ ] Custom domain resolves.
- [ ] External production smoke test passes.
- [ ] Rollback procedure is documented and understood.
- [ ] RUNBOOK.md reflects actual deployment behavior.

## Production evidence

- [ ] Launch date recorded.
- [ ] Live URL recorded.
- [ ] Deployed commit SHA recorded.
- [ ] First real external successful request recorded.
- [ ] At least one safe failure path exercised.
- [ ] Production sample size/time window recorded before reporting percentiles.
- [ ] p50/p95 latency recorded when sample size is sufficient.
- [ ] Average/median estimated model cost recorded when sample size is sufficient.
- [ ] Failure/rate-limit/truncation rates recorded.
- [ ] PRODUCTION-EVIDENCE.md updated.
- [ ] Portfolio/interview wording distinguishes self-directed production from enterprise/client production.

## Go / no-go

Release only when there are **zero known release blockers** from THREAT-MODEL.md.

A checklist tick is evidence only if you can point to the configuration, test, log, deployment, or measurement that supports it.
