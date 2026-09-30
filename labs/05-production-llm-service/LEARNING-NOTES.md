# Lab 05 — Learning Notes

Record evidence as you execute the lab. Do not pre-fill conclusions you have not observed.

## Status

**DESIGNED — NOT YET IMPLEMENTED OR RELEASED**

A repository design is not production evidence.

## Phase 0 — Product contract

What did I decide?

What did I deliberately exclude?

What production outcome would make this useful to a real stranger?

## Phase 1 — Deterministic application boundaries

What is deterministic?

Which inputs are rejected before any external call?

What would still be probabilistic later?

## Phase 2 — GitHub ingestion

What real GitHub limits did I encounter?

What evidence is lost through truncation?

How did I prevent arbitrary URL fetching?

## Phase 3 — Real LLM integration

Exact model ID:

Why this model:

API used:

First real request evidence:

What surprised me about latency or response behavior?

## Phase 4 — Structured output and evals

Eval-set size:

Baseline pass rate:

Known failure modes:

Which checks are deterministic vs model-quality judgments?

## Phase 5 — Cost and latency

What does one representative request cost?

What is actually known vs estimated?

Where is latency spent?

Did token counts match my intuition?

## Phase 6 — Production abuse/security

What attacks or abuse cases did I test?

Which control actually enforces the boundary?

What remains an honest limitation?

## Phase 7 — UX and operability

How does the UI communicate uncertainty, truncation and failure?

Can I diagnose a failure without reading sensitive raw content?

## Phase 8 — CI/CD

What does CI prove?

What does a preview/production deployment prove that CI does not?

## Phase 9 — Public release

Launch date:

Live URL:

Deployment SHA:

External smoke request:

Failure path tested:

## Phase 10 — Production measurements / model experiment

Measurement window:

Request sample size:

p50 / p95 total latency:

p50 / p95 LLM latency:

Token distribution:

Estimated cost distribution:

Failure rate:

Truncation rate:

Models/configurations compared:

Decision and evidence:

## Phase 11 — Post-launch review

What would I change for meaningful scale?

What did I learn that I could not have learned from a local demo?

What is now truthful to say in an interview?

What must I still avoid claiming?
