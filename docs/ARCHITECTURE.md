# Architecture

A modular monolith for the API, a separate worker process when background execution lands, and
inference as its own process. Not microservices: the resource budget is 12 GB and process boundaries
cost RAM.

```
Clients (OpenAI SDK, curl, CLI, web UI)
        |
   Edge: TLS                                        [Phase 3]
        |
   Identity and metering  (packages/core)
     PrincipalStore  -> who is calling, what they may use      IMPLEMENTED
     UsageMeter      -> per-principal + deployment caps        IMPLEMENTED
        |
   Lyren API  (apps/api)
     /healthz /readyz /v1/models /v1/chat/completions   IMPLEMENTED
     /lyren/v1/models (native, with availability)       IMPLEMENTED
     streaming, /v1/embeddings, /v1/responses,
     /v1/files, /v1/agents/runs, /v1/memory/*           NOT IMPLEMENTED
        |
   Intelligence Runtime  (packages/inference, then packages/agents)
     ModelRegistry  -> pinned ids, alias policies, probe verdicts   IMPLEMENTED
     CachingChatProvider -> record/replay cassettes                 IMPLEMENTED
     Conversation / Context / Memory / Retrieval                    NOT IMPLEMENTED
     Agent orchestrator (LangGraph)                                 NOT IMPLEMENTED
        |
   ProviderRouter -> dispatches on ModelSpec.provider              IMPLEMENTED
     OCIGenerativeAIProvider                                        IMPLEMENTED
     LocalLlamaProvider (llama.cpp)                                 IMPLEMENTED
       GGUF selection and local benchmark                           NOT DONE (needs ARM)
        |
   Data: Oracle AI Database, Object Storage, model cache            NOT IMPLEMENTED
```

## Boundaries that matter

**`ChatProvider` port.** A `Protocol` in `packages/inference/.../ports.py`. The API never imports a
vendor SDK; providers never know about HTTP. This is the one abstraction worth its cost, because it
is what makes the router, the cache and the benchmark harness compose.

**The cache is a decorator, not a layer.** `CachingChatProvider` wraps any `ChatProvider`, so
recording and replaying is orthogonal to which provider is in use. It wraps the *router*, so a cache
hit never reaches dispatch and one cassette store covers every provider — the key already includes
`provider`.

**`lyren/local` is a privacy boundary, not only a cheap arm.** Every prompt sent to an OCI-backed
alias is processed by Oracle as a third party; `lyren/local` is the only alias on which content stays
on our host. A cheap arm can be dropped when the budget grows, so this one stays on the roadmap
independently of cost. → [ADR-0007](decisions/0007-provider-router-and-local-boundary.md)

**Availability is data, not configuration.** `Availability` per model, with a probe timestamp. The
chat route records a verdict when a candidate fails, so catalog drift is observed rather than
assumed. This exists because the OCI catalog demonstrably lies; see
[OCI_DISCOVERY.md](OCI_DISCOVERY.md).

**Identity precedes everything.** A key resolves to a `Principal`, and the principal — not the
request — decides the model allow-list, the output-token ceiling and the quota. Both caps are
checked before any provider call, so a refused request costs nothing. See
[ADR-0006](decisions/0006-principals-not-api-keys.md).

**Routing decisions are made on cost and latency under a quality floor**, not on a quality ranking.
That is a measurement result, not a preference: at the scale of a hand-written benchmark, latency
and token cost separate the models clearly and quality does not.
→ [baseline-v2 results](research/baseline-v2-results.md)

**Aliases are the routing identity.** `lyren/fast`, `lyren/deep`, `lyren/code`, `lyren/research`,
`lyren/auto` are virtual models with an ordered candidate list and their own output budget, timeout
and paid-provider gate. Clients target an alias; the alias absorbs model churn.

## What is deliberately absent

No Kubernetes, Redis, Temporal, Prometheus or Grafana. Each would consume RAM the box does not have.
Observability starts as structured JSON logs with request ids; a metrics backend arrives only when
there is something measured that logs cannot answer, and it will be hosted off-box.

No streaming yet. SSE changes error handling, cancellation and usage accounting all at once, so it
gets its own phase and its own tests rather than a partial implementation.
