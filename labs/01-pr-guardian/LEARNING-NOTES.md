# Lab 01 — Learning Notes

Complete this file in your own words. Do not let an AI agent fabricate the observations.

## Before the lab

### What do I expect an eval to give me?

_Write here._

### What do I think the main security boundary is?

_Write here._

### What is the difference between a useful demo and an engineering capability?

_Write here._

---

## Baseline run

| Item | Observation |
|---|---|
| Model | |
| Cases passed | |
| Cases failed | |
| Total tokens | |
| Approximate cost | |
| Slowest case | |
| Most surprising result | |

### False positives

_Write here._

### Missed findings

_Write here._

---

## Trace inspection

Case inspected:

`____________________________`

1. How many model turns occurred?
2. Which tools were called?
3. In what order?
4. What information did each tool return?
5. Was unnecessary context retrieved?
6. Where was most latency spent?
7. Were there retries or failures?
8. Was the final finding supported by evidence?
9. Could I reconstruct the operational path without hidden chain-of-thought?

### My trace observations

_Write here._

---

## Intentional regression

Prompt change introduced:

_Write here._

### What changed?

| Signal | Baseline | Regressed |
|---|---:|---:|
| Cases passed | | |
| False positives | | |
| Total tokens | | |
| Latency | | |

### Did the eval suite expose the degradation clearly?

_Write here._

### What does this teach me about prompt versioning?

_Write here._

---

## Codex architecture review

### Blockers

_Write here._

### Important findings

_Write here._

### Nice-to-have improvements

_Write here._

### Recommendations I accepted

_Write here._

### Recommendations I intentionally did not implement, and why

_Write here._

---

## Deterministic vs probabilistic

### Deterministic components

_Write here._

### Probabilistic components

_Write here._

### Where is authority enforced?

_Write here._

---

## Enterprise gap analysis

What would need to change before this capability could review real enterprise PRs?

_Write here._

---

## Interview story

Explain the lab in 60–90 seconds without reading a script:

_Write your version here._

---

## Five lessons I want to remember

1.
2.
3.
4.
5.
