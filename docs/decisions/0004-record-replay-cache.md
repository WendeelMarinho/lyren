# ADR-0004 — Record/replay of model calls is infrastructure, not optimisation

**Date:** 2026-11-23 · **Status:** Accepted

## Context
The project's stated differentiator is that it demonstrates results by reproducible test rather than
by the model asserting success. Model calls are non-deterministic and billable.

## Decision
A cassette cache sits between the runtime and every provider, as a decorator over the
`ChatProvider` port. The key is a SHA-256 over provider, model id, **pinned version**, api format,
messages, output budget, temperature and stop sequences. Four modes: `off`, `record` (always call and
overwrite), `replay` (never call; a miss is an error), `auto` (read, then call and store).

## Consequences
Experiments become reproducible and CI becomes affordable, because `replay` runs the full suite with
zero provider calls and fails loudly on a missing cassette instead of silently spending money.
Including the pinned version in the key means moving a pin invalidates its cassettes rather than
silently reusing another model's answers.

This same component is the semantic-cache groundwork for the inference gateway, so the reproducibility
requirement and the cost requirement are served by one piece of code.

The cost: cassettes are an artifact to manage, and a prompt change invalidates them. Accepted — that
invalidation is the point.
