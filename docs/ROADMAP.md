# Roadmap

Each phase names its acceptance criterion. A phase is not done until that criterion is demonstrable,
and [IMPLEMENTATION_STATUS.md](IMPLEMENTATION_STATUS.md) is updated.

## Phase 0 — Discovery · DONE
OCI audit, reuse matrix, architecture, resource budget, ADRs.
**Accepted:** [OCI_DISCOVERY.md](OCI_DISCOVERY.md) records probe-verified facts and names what is
unverified.

## Phase 1 — Foundation · DONE
Monorepo, FastAPI app, settings, structured logging, bearer auth, model registry, record/replay
cache, OCI provider, offline tests, CI, arm64 Dockerfile, compose.
**Accepted:** lint, strict typecheck and 27 tests pass with 83% coverage; the API serves `/healthz`,
`/readyz`, `/v1/models` and non-streaming `/v1/chat/completions` with no paid resource required.

## Phase 2 — Inference Gateway · NEXT
Local `LocalLlamaProvider` over llama.cpp; GGUF selection driven by a reproducible benchmark
(tokens/s, time-to-first-token, RAM, pt-BR and en quality, tool calling) across the 1B-4B range;
streaming SSE with cancellation; `/v1/embeddings` on `cohere.embed-v4.0`; usage metering; the first
web UI on assistant-ui.
**Acceptance:** the OpenAI SDK lists models and holds a streaming conversation with a **local**
model, with no OCI call.

## Phase 3 — OCI Deployment
Terraform modules, each resource classified Always-Free-confirmed / credit-covered / pay-per-use /
unverified, defaulting to the first only. ARM64 deploy, TLS, restrictive NSG, instance principal,
tested backup and restore.
**Acceptance:** the API answers over HTTPS with authentication, inside the approved envelope, and the
infrastructure can be destroyed and rebuilt from code.

## Phase 4 — Model Routing
Alias policies driven by measured cost and latency; optional OCI provider behind an explicit budget;
controlled fallback; comparative benchmarks across the three callable models plus the local one.
**Acceptance:** the same client contract switches models with no client change, and the choice is
justified by numbers rather than preference.

## Phase 5 — Memory and RAG
Oracle AI Database persistence; vector index at 1536 dimensions; document pipeline (TXT, Markdown,
text-bearing PDF, code, JSON); hybrid retrieval with rerank; the four memory types; verifiable
deletion.
**Acceptance:** answers cite retrieved sources, interpretation is distinguished from retrieval, and
Recall@K, MRR and citation precision are measured on a frozen set.

## Phase 6 — Cognitive Runtime
LangGraph orchestration, specialised agents, MCP tools, durable runs, checkpoints, human approval,
cancellation.
**Acceptance:** a multi-step task is interrupted and resumed without improperly repeating an
operation.

## Phase 7 — Lyren Code
opencode integrated against the Lyren gateway, isolated workspace, patch generation, review,
approval before any sensitive action.

## Phase 8 — Advanced
Temporal memory, GraphRAG, context compression, tool selection, adaptive routing, prompt
optimisation, evaluation-driven improvement. Experiments stay out of the main runtime until tested.

## Cross-cutting, starting now
The evaluation harness is built alongside Phase 2, not after Phase 8. Until a frozen task set and a
deliberately weak baseline exist, no later component can be shown to have helped.
