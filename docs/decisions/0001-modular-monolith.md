# ADR-0001 — Modular monolith, not microservices

**Date:** 2026-11-23 · **Status:** Accepted

## Context
The target host is a single Ampere A1 VM inside the Always Free envelope: ~2 OCPU, 12 GB RAM, one
availability domain. The reference architecture names seven runtime concerns (API, conversation,
routing, memory, retrieval, agents, tools).

## Decision
One FastAPI process for the API, a separate worker process when background execution arrives, and
inference as its own process. Module boundaries inside the monolith are enforced by ports
(`Protocol`) rather than by network hops.

## Consequences
Each process boundary costs RAM we do not have, so we buy isolation where it is cheap — types and
protocols — rather than where it is expensive. The cost is that a runaway module can take down the
API; mitigated by container resource limits. Splitting later is possible precisely because the ports
already exist.

## Alternatives rejected
Microservices per concern: unaffordable at 12 GB. A single process for everything including
inference: a llama.cpp stall would take the API with it.
