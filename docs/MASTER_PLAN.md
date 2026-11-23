# Lyren — Master Plan

Entry point. Each section links to the document that owns the detail; this file only holds what
governs every decision.

## Objective
A personal AI platform with its own runtime, data, agents, models and infrastructure. The engineering
challenge is the intelligence layer — planning, memory, routing, evaluation, durable execution — not
connecting to an LLM API.

## Governing constraints
1. **Size for ~2 OCPU ARM / 12 GB RAM.** The tenancy's service limits are higher, but a limit is a
   ceiling, not a free allowance, and the account type is unresolved.
   → [RESOURCE_BUDGET.md](RESOURCE_BUDGET.md)
2. **No billing resource, plan change or chargeable service without explicit authorisation.**
3. **Zero GPU quota in this tenancy.** No training, no fine-tuning. → [OCI_DISCOVERY.md](OCI_DISCOVERY.md)
4. **Three callable chat models**, one embedding model, one rerank model. The router has three arms,
   so plan a routing experiment, not a broad study.
5. **No fake features.** Unfinished capability stays disabled and errors explicitly.
   → [IMPLEMENTATION_STATUS.md](IMPLEMENTATION_STATUS.md)
6. **Reuse before building.** → [OPEN_SOURCE_REUSE.md](OPEN_SOURCE_REUSE.md)
7. **Security from v1.** → [SECURITY_MODEL.md](SECURITY_MODEL.md)

## Build order, and why it is this order
The evaluation harness comes early, not last. Built after the planner, memory and routing, every
component before it is unfalsifiable — there is no way to tell whether memory helped or hurt. So:
a frozen task set and a deliberately weak baseline first, then each component must beat that baseline
to earn its place. → [ROADMAP.md](ROADMAP.md)

Record/replay of model calls is part of that foundation: without it no experiment is reproducible and
no CI is affordable. → [ADR-0004](decisions/0004-record-replay-cache.md)

## Architecture
Modular monolith, ports at the boundaries, one durable runtime.
→ [ARCHITECTURE.md](ARCHITECTURE.md), [ADR-0001](decisions/0001-modular-monolith.md),
[ADR-0002](decisions/0002-single-durable-runtime.md)

## Success criteria for v1
Web UI reachable; conversation with a local model; callable by an OpenAI-compatible client; a second
authorised provider reachable through the same contract; history persisted; credentials protected;
infrastructure rebuildable from code; tests automated; resource use monitored; a tested path to memory
and agents.

Current state: items 3 and 8 are met, 6 partially. The rest is Phase 2 onward.
