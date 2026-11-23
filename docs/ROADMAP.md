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

## Phase 2 — Evaluation first, then the gateway · IN PROGRESS
**Done:** evaluation harness — frozen task set, deterministic graders, benchmark runner, spend
ledger and the two caps.

**Next, in this order:** calibration run of `baseline-v1` across the three callable OCI models to
establish the baseline and the real per-token cost; then `LocalLlamaProvider` over llama.cpp with
GGUF selection in the 1B-4B range driven by the same harness; then streaming SSE with cancellation,
`/v1/embeddings` on `cohere.embed-v4.0`, and the first web UI on assistant-ui.

The order changed on 2026-11-24. Local inference was first only because it was free; with spend
authorised, the baseline measurement comes first — it is what makes every later component
falsifiable, and the local model then enters as a fourth arm with a measured cost profile instead of
an assumed one.

**Acceptance:** `baseline-v1` has a recorded score, latency and token cost per model, reproducible
from cassettes with zero provider calls; and the OpenAI SDK holds a streaming conversation with a
local model.

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

## Cross-cutting
The evaluation harness exists as of Phase 2 rather than Phase 8, so every later component has to beat
a recorded baseline to earn its place. `baseline-v1` is deliberately small and fully machine-graded;
it grows as capabilities land, and a task is never changed to make a result look better.
