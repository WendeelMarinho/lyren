# Lyren — Master Plan

Entry point. Each section links to the document that owns the detail; this file only holds what
governs every decision.

## Objective
An AI platform with its own runtime, data, agents, models and infrastructure, serving a **small group
of named people**. The engineering challenge is the intelligence layer — planning, memory, routing,
evaluation, durable execution — not connecting to an LLM API.

Two things follow from it being shared rather than personal, and they are not cosmetic:

- **Identity is foundational.** Attribution, per-person quotas, individual key revocation and
  memory ownership all depend on knowing who is calling. → [ADR-0006](decisions/0006-principals-not-api-keys.md)
- **The budget is shared and has no automatic stop.** Per-person quotas protect people from each
  other; only a deployment-wide cap protects the bill. → [ADR-0005](decisions/0005-spend-control-in-process.md)

It is also built in the open, because demonstrating the engineering is part of the objective: the
reasoning is in `decisions/`, and every measurement is reproducible from the repository.

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
7. **Security and data protection from v1**, including for the people using it, not only for the
   operator. → [SECURITY_MODEL.md](SECURITY_MODEL.md)

## Build order, and why it is this order
The evaluation harness comes early, not last. Built after the planner, memory and routing, every
component before it is unfalsifiable — there is no way to tell whether memory helped or hurt. So:
a frozen task set and a deliberately weak baseline first, then each component must beat that baseline
to earn its place. → [ROADMAP.md](ROADMAP.md)

Record/replay of model calls is part of that foundation: without it no experiment is reproducible and
no CI is affordable. → [ADR-0004](decisions/0004-record-replay-cache.md)

## Repositories

This repository holds the application and is public. OCI Terraform, host bootstrap, operational
scripts and the tenancy inventory live in a separate **private** repository, `lyren-infra`: those
describe the deployment — OCIDs, network layout, IAM policies, real quota values — and publishing
them would hand over a map. `Dockerfile.api` and the development compose file stay here, with the
source they build.

## Architecture
Modular monolith, ports at the boundaries, one durable runtime.
→ [ARCHITECTURE.md](ARCHITECTURE.md), [ADR-0001](decisions/0001-modular-monolith.md),
[ADR-0002](decisions/0002-single-durable-runtime.md)

## Success criteria for v1
Web UI reachable; conversation with a local model; callable by an OpenAI-compatible client; a second
authorised provider reachable through the same contract; history persisted; credentials protected;
infrastructure rebuildable from code; tests automated; resource use monitored; a tested path to memory
and agents.

Current state: items 3 and 8 are met; 6 is met for credentials at rest and in transit to the
provider, and incomplete until there is TLS and an audit log. The rest is Phase 2 onward.

Because the platform is shared, two criteria are added: each person's usage is attributable and
individually bounded (met), and each person's data is isolated and deletable on request (not met —
there is no persistence yet, which is also why it is not yet a breach of it).
