# ADR-0007 — A provider router, and local inference as a privacy boundary

**Date:** 2026-11-23 · **Status:** Accepted

## Context
Until now there was one provider, so the chat route could hold a single `ChatProvider`. Adding
llama.cpp makes that wrong in two ways: the route would have to know which concrete client serves
which model, and alias fallback could not cross a provider boundary — which is precisely the
fallback worth having, since a hosted model falling back to a local one is the difference between
degraded service and none.

Separately, the platform became shared. That changes what local inference is *for*.

## Decision

**A `ProviderRouter` dispatches on `ModelSpec.provider`.** A spec already names its provider, so the
route asks the router and the router owns the mapping. The cache wraps the router rather than each
provider, so a cache hit never reaches dispatch at all, and one cassette store covers every provider
because the key already includes `provider`.

**`lyren/local` is documented as the alias on which prompt content never leaves our host.** Local
inference is treated as a privacy boundary, not only a cost arm. A cheap arm can be dropped when the
budget grows; a boundary cannot, so the local provider stays on the roadmap independently of cost.

**The local model is `UNVERIFIED` until probed.** Startup calls `/health` and records the verdict in
the registry, so alias resolution skips a server that is down or holding no model instead of failing
a request at call time. Which GGUF is loaded is declared in configuration, never inferred from the
server.

**No GGUF is selected and no local benchmark is recorded.** Measuring llama.cpp on an x86 development
machine answers nothing about 2 ARM OCPUs, and publishing such a number would invite the false
confidence this project exists to avoid. The selection runs on the target hardware in Phase 3, with
the same task set and graders as the hosted comparison.
→ [local inference plan](../research/local-inference-plan.md)

## Consequences
The router is a map lookup, so it adds a layer with almost no behaviour — justified only because the
alternative puts provider selection in the HTTP route, where it would be duplicated by every future
endpoint and untestable without a transport.

`lyren/fast` and `lyren/auto` now list the local model as a trailing candidate. Until the probe
verifies it, those aliases resolve exactly as before, so adding the candidate changes nothing until
a server actually exists. That is the intended property: a candidate list is a preference order, not
a promise.

Readiness now reports which providers are wired, because "the API is up" and "the API can answer"
stopped being the same question once a provider could be configured but unreachable.
