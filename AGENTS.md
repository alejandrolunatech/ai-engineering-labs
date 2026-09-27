# AI Agent Instructions

This repository is an AI-engineering learning environment.

When reviewing or modifying code:

1. Preserve the educational intent of each lab.
2. Do not invent professional experience or claim that lab work was enterprise production work.
3. Prioritize:
   - bounded model authority;
   - deterministic controls around probabilistic behavior;
   - inspectable evals;
   - observability;
   - security;
   - cost awareness;
   - explicit trade-offs.
4. Never expose or commit credentials.
5. For architecture reviews, classify findings as **blocker**, **important**, or **nice-to-have**.
6. Distinguish what is proven by code/evals from what is an inference.
7. Prefer concrete evidence over generic praise.

For Lab 01, read `labs/01-pr-guardian/README.md` before proposing changes.

For Lab 02, read `labs/02-zero-trust-mcp-gateway/README.md` before proposing changes. In security reviews, distinguish **model influence**, **policy decision**, **gateway enforcement**, and **downstream execution**.


For Lab 04, read `labs/04-ai-engineering-golden-path/README.md` and `ARCHITECTURE.md` before proposing changes. Reviews should challenge whether the golden path actually improves developer self-service while preserving explicit contracts, evals, observability, budgets, governance, and upgradeability. Distinguish platform defaults from hard security boundaries.
