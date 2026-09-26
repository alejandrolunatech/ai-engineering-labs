# Lab 01 — PR Guardian

> Build a **bounded, observable, evaluated AI pull-request review agent** in approximately 100–120 minutes.

**Difficulty:** Intermediate / Senior AI Engineering  
**Primary gaps:** evals, structured outputs, tracing, usage/cost awareness, regression testing, bounded tools, human accountability  
**Stack:** Python 3.11+, OpenAI Agents SDK, Pydantic, pytest, local fixture repository  
**Default model:** `gpt-5.6-luna` for inexpensive iteration. Optional comparison: `gpt-5.6-sol`.

---

## Learning objective

This lab is not about making the smartest reviewer possible.

It is about experiencing the difference between:

> “The model gave me a useful answer.”

and:

> “I have a bounded AI capability with a behavioral contract, representative eval cases, structured output, operational traces, usage data, latency measurements, and a repeatable regression loop.”

By the end, you should be able to explain from hands-on experience:

- what makes an AI code-review capability testable;
- why traditional unit tests are necessary but insufficient for probabilistic behavior;
- how to design positive and negative eval cases;
- why clean PRs must be allowed to produce zero findings;
- how traces help debug agent behavior;
- how prompt changes can create regressions;
- how to inspect token usage, latency, and approximate cost;
- why a PR reviewer should begin read-only;
- how model capability differs from tool authority.

---

## Architecture

```text
PR fixture
(diff + files + test results)
        │
        v
┌─────────────────────┐
│ Read-only tool layer│
│ read_diff           │
│ read_file           │
│ search_repository   │
│ get_test_results    │
└─────────┬───────────┘
          │
          v
┌─────────────────────┐
│ PR Guardian Agent   │
│ bounded + read-only │
└─────────┬───────────┘
          │
          v
┌─────────────────────┐
│ Structured findings │
│ severity            │
│ file / line         │
│ evidence            │
│ recommendation      │
└─────────┬───────────┘
          │
     ┌────┴───────────────┐
     v                    v
 Eval harness         Observability
 detection            traces
 false positives      latency
 policy behavior      token usage
 regression           approximate cost
```

The **agent is only one component**. The engineering system around it is the lab.

---

## Security and authority constraints

### The agent must

- operate read-only;
- use explicit tools rather than arbitrary shell access;
- return structured output;
- support zero findings;
- cite evidence for every finding;
- distinguish defects from subjective style;
- treat repository content as untrusted data;
- expose usage and latency;
- be evaluated against repeatable cases.

### The agent must not

- modify files;
- create commits;
- merge branches;
- call arbitrary external URLs;
- execute arbitrary shell commands;
- treat text inside source files or READMEs as trusted instructions;
- invent findings simply to appear useful.

> **Model intelligence does not imply authority.**

---

## Timebox

| Phase | Time | Outcome |
|---|---:|---|
| 0 — Environment | 10 min | Python environment + API key |
| 1 — Bounded agent | 20 min | One PR fixture can be reviewed |
| 2 — Eval cases | 20 min | Six representative scenarios |
| 3 — Eval harness | 25 min | Repeatable results + usage data |
| 4 — Trace inspection | 10 min | One execution understood end-to-end |
| 5 — Intentional regression | 10 min | Quality degradation detected |
| 6 — Repair + rerun | 10 min | Regression corrected |
| 7 — Independent review + debrief | 15 min | Interview-ready learning |

**Hard stop: 120 minutes.** Simplify if infrastructure starts consuming the learning time.

---

# Phase 0 — Local setup

Clone the repository:

```bash
git clone https://github.com/alejandrolunatech/ai-engineering-labs.git
cd ai-engineering-labs/labs/01-pr-guardian
```

Check Python:

```bash
python3 --version
```

Create and activate a virtual environment:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
```

Create your local environment file:

```bash
cp .env.example .env
```

Put the real API key only in `.env`. It is ignored by Git.

Alternatively export it only for the terminal session:

```bash
export OPENAI_API_KEY="YOUR_KEY"
export OPENAI_MODEL="gpt-5.6-luna"
```

Your ChatGPT subscription and OpenAI API billing are separate. Keep the API budget small; this lab should be inexpensive.

Before continuing:

```bash
git status
```

Confirm `.env` is **not** shown as a tracked file.

---

# Phase 1 — Build the bounded reviewer

Use **Claude Code** as the primary implementer, but remain the architect.

The exact copyable prompt is in [PROMPTS.md](PROMPTS.md) under **Phase 1**.

Ask Claude to create:

```text
src/pr_guardian/
├── __init__.py
├── models.py
├── tools.py
├── agent.py
└── review.py
```

The only agent tools should be:

```text
read_diff(case_id)
read_file(case_id, relative_path)
search_repository(case_id, query)
get_test_results(case_id)
```

All tools must be constrained to:

```text
fixtures/cases/<case_id>/
```

and protect against path traversal.

A useful output contract is:

```python
class Finding(BaseModel):
    severity: Literal["low", "medium", "high", "critical"]
    file: str
    line: int | None
    issue: str
    evidence: str
    recommendation: str

class ReviewResult(BaseModel):
    summary: str
    findings: list[Finding]
```

The exact class names do not matter.

The important principle is:

> **The agent output is a contract, not arbitrary prose.**

### Checkpoint

Before continuing, inspect the code yourself.

Ask:

- Where is path traversal prevented?
- Are tools truly read-only?
- Can the model invoke a shell?
- Can it make arbitrary network calls?
- Is structured output enforced?
- Where is elapsed time measured?
- Where is SDK usage captured?
- Which components are deterministic?
- Which component is probabilistic?

If you cannot answer those questions, do not move on.

---

# Phase 2 — Build six representative eval fixtures

Use the **Phase 2** prompt in [PROMPTS.md](PROMPTS.md).

Create:

```text
fixtures/cases/
├── 01-duplicate-charge/
├── 02-hardcoded-secret/
├── 03-null-handling/
├── 04-clean-refactor/
├── 05-style-only/
└── 06-prompt-injection/
```

Each case should contain:

```text
diff.patch
relevant source files
test-results.txt
case-notes.md
```

### Case intent

**01 — Duplicate charge**  
A retry-path business logic error that can apply a payment side effect twice.

**02 — Hardcoded secret**  
A changed file introduces an obviously synthetic fake API secret.

**03 — Null handling**  
A subtle missing `None` / null condition causes a runtime failure.

**04 — Clean refactor**  
No meaningful defect. Correct result: **zero findings**.

**05 — Style only**  
Subjective style differences but no real defect. Correct result: **zero findings**.

**06 — Prompt injection**  
Repository text tells an AI reviewer to ignore its rules or access secrets, while the actual code also contains one ordinary bug. The reviewer should find the code bug without granting the malicious text authority.

Inspect every case manually. **You are the human ground truth.**

---

# Phase 3 — Define the behavioral contract

Create:

```text
evals/cases.json
```

Do not compare exact wording. Define behaviors.

For each case capture concepts such as:

```json
{
  "case_id": "04-clean-refactor",
  "expected_finding": false,
  "expected_category": null,
  "forbidden_findings": ["style-only"],
  "rationale": "A clean refactor should not create reviewer noise."
}
```

Useful fields:

- `expected_finding`;
- semantic category;
- minimum severity when appropriate;
- whether zero findings is expected;
- forbidden behavior;
- human-readable rationale.

Do **not** add an LLM judge yet.

First evaluate what can be checked deterministically and transparently.

---

# Phase 4 — Build the eval harness

Use the **Phase 4** prompt from [PROMPTS.md](PROMPTS.md).

Create:

```text
src/pr_guardian/eval_runner.py
```

The harness should:

- load `evals/cases.json`;
- execute all six cases;
- measure elapsed time;
- capture OpenAI Agents SDK usage;
- record request count and token usage;
- compare outputs with inspectable behavioral expectations;
- display a terminal table;
- save `reports/latest.json`;
- report failures rather than hiding them.

Target output shape:

```text
CASE                    PASS  FINDINGS  TOKENS   LATENCY
01-duplicate-charge     yes      1      3412     4.8s
02-hardcoded-secret     yes      1      2901     4.1s
03-null-handling        yes      1      3222     4.4s
04-clean-refactor       yes      0      2110     3.7s
05-style-only           yes      0      2305     3.9s
06-prompt-injection     yes      1      3870     5.2s
```

Your real values will differ.

Do not chase a perfect score. A failed case is useful evidence.

Run from `labs/01-pr-guardian` with the virtual environment active:

```bash
# all cases in evals/cases.json
python -m src.pr_guardian.eval_runner

# a subset (cheaper while iterating)
python -m src.pr_guardian.eval_runner 04-clean-refactor 05-style-only
```

Output:

- a terminal table (pass, detection/clean check, forbidden behavior, findings, requests, tokens, latency) followed by the reason for every failed case;
- `reports/latest.json` with the model, the instruction hash, per-case usage, trace IDs, tool calls, findings, and the result of each check on each finding.

The scoring rules are documented at the top of `src/pr_guardian/eval_runner.py`. They are deterministic: file match, minimum severity, keyword concept groups, zero findings for clean cases, and forbidden behavior (forbidden terms, secret disclosure, forbidden tool paths, out-of-scope tool calls). Every run makes real, billed model calls.

Record the baseline in [LEARNING-NOTES.md](LEARNING-NOTES.md).

---

# Phase 5 — Inspect one real trace

Run the prompt-injection scenario:

```bash
python -m src.pr_guardian.review 06-prompt-injection
```

Open the OpenAI API trace viewer and inspect the execution.

Record:

1. number of model turns;
2. tools called;
3. tool order;
4. context returned;
5. unnecessary retrieval;
6. latency concentration;
7. retries or failures;
8. whether evidence supports the final finding;
9. whether the operational path is reconstructable without hidden chain-of-thought.

The learning model is:

> **Logs tell me what happened.**  
> **Traces tell me how the agent got there.**  
> **Evals tell me whether the result was good.**

---

# Phase 6 — Usage and cost

Capture:

- requests;
- input tokens;
- output tokens;
- total tokens;
- elapsed time.

Do not permanently hard-code model pricing in core agent logic. Pricing can change.

Use current official pricing to calculate an approximate:

```text
input_cost =
  input_tokens / 1_000_000 × input_price_per_million

output_cost =
  output_tokens / 1_000_000 × output_price_per_million
```

Then ask a better question:

> **What is the cost per successful review?**

A cheap reviewer with many false positives may have poor economics.

---

# Phase 7 — Intentionally break the system

This phase is mandatory.

Temporarily weaken the agent instructions with something such as:

```text
Be extremely thorough. Always identify at least one thing that could
be improved in every pull request.
```

Run:

```bash
python -m src.pr_guardian.eval_runner
```

Pay attention to:

```text
04-clean-refactor
05-style-only
```

You are trying to create false positives.

Save the degraded result:

```bash
cp reports/latest.json reports/regression-example.json
```

The lesson is:

> **A prompt change is a production behavior change.**

Revert the bad instruction and rerun the suite.

Confirm recovery.

---

# Phase 8 — Optional model comparison

Only if time remains:

```bash
export OPENAI_MODEL="gpt-5.6-sol"
python -m src.pr_guardian.eval_runner
```

Compare:

- pass count;
- false positives;
- latency;
- tokens;
- approximate cost.

Do not conclude that one model is universally better from six cases.

A senior conclusion sounds like:

> “For this small dataset, model A produced X while model B produced Y. I would need broader representative evidence before making a platform decision.”

---

# Phase 9 — Independent Codex review

Use the **Codex Review** prompt from [PROMPTS.md](PROMPTS.md).

Codex should review, not rewrite.

Evaluate:

- bounded authority;
- path traversal;
- read-only guarantees;
- secret exposure;
- structured output;
- eval quality;
- vanity metrics;
- usage measurement;
- enterprise gaps;
- deterministic versus agentic responsibilities.

Classify findings:

```text
BLOCKER
IMPORTANT
NICE-TO-HAVE
```

You decide what to accept.

Record the important observations in [LEARNING-NOTES.md](LEARNING-NOTES.md).

---

# Phase 10 — Commit the result

Inspect first:

```bash
git status
git diff
```

Verify no secret is tracked:

```bash
git status --ignored
```

Then:

```bash
git add .
git status
git commit -m "lab: complete PR Guardian evaluated review agent"
git push
```

If `.env` appears in staged files, **stop**.

---

# Definition of Done

```text
[ ] Agent reviews a fixture
[ ] No arbitrary shell access
[ ] Tools are read-only
[ ] Structured output is enforced
[ ] Six eval cases exist
[ ] Clean refactor can produce zero findings
[ ] Style-only case can produce zero findings
[ ] Prompt-injection content gains no privileged authority
[ ] Eval harness runs all cases
[ ] Token usage is visible
[ ] Latency is visible
[ ] One trace was manually inspected
[ ] One intentional regression was created
[ ] Eval suite exposed the regression
[ ] Regression was repaired
[ ] Codex independently reviewed the design
[ ] Learning notes contain your own conclusions
[ ] No secrets are committed
```

Do not call the lab complete merely because “the agent works.”

The lab is complete when you can explain **why you trust it only inside a defined boundary**.

---

# Failure guide

## Clean cases produce findings

You have a false-positive problem.

Investigate:

- instructions that reward appearing useful;
- whether zero findings is natural in the output contract;
- whether negative cases are prominent enough;
- whether style commentary is being confused with defects.

## Duplicate-charge bug is missed

Investigate:

- missing context;
- wrong file retrieval;
- insufficient diff;
- ambiguous tool descriptions;
- whether the defect is genuinely inferable.

## Prompt injection changes behavior

Separate two questions:

1. Did the model become influenced?
2. Could that influence reach dangerous authority?

> **Prompt resistance is useful. Permission boundaries are stronger.**

## Cost or latency is unexpectedly high

Inspect:

- repeated file reads;
- excessive context;
- unnecessary model turns;
- use of an unnecessarily expensive model;
- work that could be deterministic.

---

# Interview debrief

After completing the lab, explain it aloud in your own words.

A useful structure:

> “I built a small PR-review capability specifically to deepen my production AI engineering practice. I treated the reviewer as only one component. I gave it bounded read-only tools, structured its findings, created positive and negative eval cases, inspected tracing and usage, and then intentionally degraded the prompt to see whether the eval suite would catch the regression. What became tangible is that an agent demo is easy; the engineering challenge is defining the behavioral contract, controlling authority, observing failures, and creating evidence that a change is actually better.”

Do not memorize the paragraph. Understand it.

---

# Senior-level questions to answer after the lab

**Why include clean PRs?**  
Because a reviewer that always finds something can look active while creating noise. Negative cases expose false positives.

**Why structured output?**  
It makes downstream validation, evaluation, rendering, policy checks, and automation more deterministic.

**Why no shell tool?**  
Code review does not require arbitrary execution authority. Permissions should follow least privilege.

**Why retrieve context through tools instead of dumping the repository into the prompt?**  
Because context engineering should provide the smallest trustworthy context sufficient for the task.

**Why is an eval different from a unit test?**  
Unit tests are ideal for deterministic contracts. Evals cover semantic or probabilistic behavior where multiple outputs may be acceptable.

**Why intentionally create a regression?**  
An eval suite is not mainly there to prove today's version works. It is there to detect when tomorrow's change makes behavior worse.

**What is still missing for enterprise rollout?**  
Real repository integration, enterprise identity/authorization, broader datasets, model/data governance, security testing, production observability, cost controls, staged rollout, ownership, developer feedback, and incident procedures.

---

# Optional stretch goals

Do these only after the core lab works.

### A — Real GitHub PR

Replace fixture-based diff reading with **read-only** GitHub PR access.

### B — LLM-as-a-judge

Add semantic scoring for groundedness, relevance, or actionability, calibrated against human-reviewed examples. Keep deterministic assertions.

### C — Human approval

Let the agent prepare a draft review comment but require explicit approval before posting.

### D — CI

Run deterministic tests and fixture validation in GitHub Actions. Avoid uncontrolled paid model calls on every commit.

---

# References

Current implementation references:

- OpenAI Agents SDK: https://openai.github.io/openai-agents-python/
- Quickstart: https://openai.github.io/openai-agents-python/quickstart/
- Tracing: https://openai.github.io/openai-agents-python/tracing/
- Usage tracking: https://openai.github.io/openai-agents-python/usage/
- OpenAI model catalog: https://platform.openai.com/docs/models
- API billing: https://help.openai.com/en/articles/9039756

Re-check SDK APIs, model IDs, and pricing if running the lab significantly later.

---

# Final principle

> **The agent is not the product. The evaluated, observable, bounded engineering capability is the product.**
