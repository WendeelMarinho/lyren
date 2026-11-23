# ADR-0002 — One durable runtime (LangGraph), not LangGraph plus Temporal

**Date:** 2026-11-23 · **Status:** Accepted

## Context
The original plan paired LangGraph with Temporal for durable agent execution. Both persist state,
both retry, both resume from checkpoints.

## Decision
LangGraph alone for Phase 6. Temporal is reconsidered only when a concrete failure mode appears that
LangGraph cannot handle.

## Consequences
We avoid two sources of truth for run state and two retry semantics. We also avoid a real impedance
mismatch: Temporal workflow code must be deterministic on replay, so model calls, clocks and
randomness have to live in activities — which leaves a choice between decomposing a LangGraph graph
into one activity per node (reimplementing the graph) or running the whole graph as a single activity
(losing durability inside it). Self-hosting a Temporal server plus its datastore also costs roughly
1 GB on a 12 GB box.

The cost: LangGraph's durability guarantees are weaker than Temporal's event-sourced replay. Accepted
until measured against a real workload.

## Alternatives rejected
Both together: the mismatch above. Temporal alone: more to learn about durable execution, but slower
to a working Phase 6 and heavier on the box.
