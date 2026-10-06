# AI Engineering Labs

Hands-on laboratories for building **production-minded AI engineering capability**.

These labs are designed around the difference between **AI experimentation** and **AI engineering**: bounded authority, explicit behavioral contracts, evaluation, observability, security, cost awareness, developer experience, and repeatable delivery.

## Labs

| Lab | Focus | Status |
|---|---|---|
| [01 — PR Guardian](labs/01-pr-guardian/README.md) | Bounded PR-review agent, evals, tracing, token/cost measurement, regression testing | **Ready** |
| [02 — Zero-Trust MCP Gateway](labs/02-zero-trust-mcp-gateway/README.md) | MCP security, OPA/Rego policy-as-code, prompt injection, least privilege | **Ready** |
| 03 — Incident Commander | OpenTelemetry, traces, AI-assisted incident diagnosis | Planned |
| [04 — AI Engineering Golden Path](labs/04-ai-engineering-golden-path/README.md) | Reusable AI platform primitives, capability contracts, evals, observability, governance, and developer self-service | **Ready** |
| [05 — Production LLM Service: ChangeBrief](labs/05-production-llm-service/README.md) | Real public LLM API product: GitHub PR briefs, cost/latency evidence, abuse controls, CI/CD and production operations | **Designed — not released** |

## Why this repository exists

The goal is not to collect demos. Each lab should create an engineering artifact that can be explained, tested, challenged, and improved.

The working principle is:

> **The agent is not the product. The evaluated, observable, bounded engineering capability is the product.**

Lab 05 adds a second operating principle:

> **Production is an operating state, not a deployment file.**

## How to use the labs

1. Read the lab README before asking an AI coding agent to implement anything.
2. Work phase-by-phase. Do not ask an AI agent to build the whole lab in one shot.
3. You remain the architect and decision maker.
4. Use Claude Code primarily as an implementer.
5. Use Codex as an independent architecture/security reviewer.
6. Use GitHub Copilot for inline assistance while inspecting or modifying code.
7. Record your own observations in each lab's `LEARNING-NOTES.md`.
8. Never commit API keys, credentials, or real secrets.
9. For production-oriented labs, do not call a project "production" until the stated production evidence exists.

## Repository structure

```text
ai-engineering-labs/
├── README.md
├── LICENSE
├── CLAUDE.md
├── AGENTS.md
├── .gitignore
├── .github/workflows/ci.yml
└── labs/
    ├── 01-pr-guardian/
    ├── 02-zero-trust-mcp-gateway/
    ├── 04-ai-engineering-golden-path/
    └── 05-production-llm-service/
        ├── README.md
        ├── ARCHITECTURE.md
        ├── THREAT-MODEL.md
        ├── PROMPTS.md
        ├── LEARNING-NOTES.md
        ├── RUNBOOK.md
        ├── RELEASE-CHECKLIST.md
        ├── PRODUCTION-EVIDENCE.md
        └── .env.example
```

## Evidence discipline

Learning or implementing something in these labs does **not** rewrite past professional history. When using a lab in an interview, distinguish clearly between:

- what I have done professionally;
- what I built in this lab;
- what I learned;
- what I would change before enterprise deployment.

For Lab 05 specifically:

- before public release: **production-oriented learning project**;
- after the release Definition of Done is evidenced: **self-directed public production product**;
- never relabel it as enterprise/client production work unless that is independently true.

## Continuous integration

Every push to `main` and every pull request runs [`.github/workflows/ci.yml`](.github/workflows/ci.yml):

- a gitleaks secret scan over the full git history;
- Lab 02: OPA/Rego policy tests and the gateway pytest suite;
- Lab 04: the golden-path pytest suite;
- Lab 05: lint, typecheck, unit tests and production build of the ChangeBrief app.

Lab 01 has no automated test suite yet; its evals call a real model and stay a manual, local step.

## Licence

The code in this repository (source, tests, templates and configuration) is released under the [MIT License](LICENSE). The Markdown write-ups (`*.md`) are not covered by that licence and remain all rights reserved; see the scope note in [LICENSE](LICENSE).

## Author

**Alejandro Luna**  
AI Delivery & Transformation Consultant  
GitHub Copilot Certified (GH-300)  
https://alejandrolunatech.com
