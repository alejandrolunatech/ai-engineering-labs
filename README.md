# AI Engineering Labs

Hands-on laboratories for building **production-minded AI engineering capability**.

These labs are designed around the difference between **AI experimentation** and **AI engineering**: bounded authority, explicit behavioral contracts, evaluation, observability, security, cost awareness, developer experience, and repeatable delivery.

## Labs

| Lab | Focus | Status |
|---|---|---|
| [01 — PR Guardian](labs/01-pr-guardian/README.md) | Bounded PR-review agent, evals, tracing, token/cost measurement, regression testing | **Ready** |
| 02 — Zero-Trust MCP Gateway | MCP security, policy-as-code, prompt injection, least privilege | Planned |
| 03 — Incident Commander | OpenTelemetry, traces, AI-assisted incident diagnosis | Planned |
| 04 — AI Engineering Golden Path | Reusable AI platform primitives and developer self-service | Planned |

## Why this repository exists

The goal is not to collect demos. Each lab should create an engineering artifact that can be explained, tested, challenged, and improved.

The working principle is:

> **The agent is not the product. The evaluated, observable, bounded engineering capability is the product.**

## How to use the labs

1. Read the lab README before asking an AI coding agent to implement anything.
2. Work phase-by-phase. Do not ask an AI agent to build the whole lab in one shot.
3. You remain the architect and decision maker.
4. Use Claude Code primarily as an implementer.
5. Use Codex as an independent architecture/security reviewer.
6. Use GitHub Copilot for inline assistance while inspecting or modifying code.
7. Record your own observations in each lab's `LEARNING-NOTES.md`.
8. Never commit API keys, credentials, or real secrets.

## Repository structure

```text
ai-engineering-labs/
├── README.md
├── CLAUDE.md
├── AGENTS.md
├── .gitignore
└── labs/
    └── 01-pr-guardian/
        ├── README.md
        ├── PROMPTS.md
        ├── LEARNING-NOTES.md
        ├── requirements.txt
        ├── .env.example
        ├── src/
        ├── fixtures/
        ├── evals/
        ├── reports/
        └── tests/
```

## Evidence discipline

Learning or implementing something in these labs does **not** rewrite past professional history. When using a lab in an interview, distinguish clearly between:

- what I have done professionally;
- what I built in this lab;
- what I learned;
- what I would change before enterprise deployment.

## Author

**Alejandro Luna**  
AI Delivery & Transformation Consultant  
GitHub Copilot Certified (GH-300)  
https://alejandrolunatech.com
