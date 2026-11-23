# Roadmap

Each phase names its acceptance criterion. A phase is not done until that criterion is demonstrable,
and [IMPLEMENTATION_STATUS.md](IMPLEMENTATION_STATUS.md) is updated.

## Phase 0 — Discovery · DONE
OCI audit, reuse matrix, architecture, resource budget, ADRs.
**Accepted:** [OCI_DISCOVERY.md](OCI_DISCOVERY.md) records probe-verified facts and names what is
unverified.

## Phase 1 — Foundation · DONE
Monorepo, FastAPI app, settings, structured logging, model registry, record/replay cache, OCI
provider, offline tests, CI, arm64 Dockerfile, compose. Authentication was later replaced: the
platform is shared, so a key identifies a person and carries individual quotas.
→ [ADR-0006](decisions/0006-principals-not-api-keys.md)
**Accepted:** lint, strict typecheck and 27 tests pass with 83% coverage; the API serves `/healthz`,
`/readyz`, `/v1/models` and non-streaming `/v1/chat/completions` with no paid resource required.

## Phase 2 — Evaluation first, then the gateway · IN PROGRESS
**Done:** evaluation harness — frozen task set, deterministic graders, benchmark runner, spend
ledger and the two caps.

**Done:** `baseline-v1` and `baseline-v2` measured across the three callable OCI models. The
conclusion shaped the router: at this scale the harness separates cost and latency cleanly and does
not separate quality, so routing goes on cost and latency under a quality floor.
→ [baseline-v2 results](research/baseline-v2-results.md)

**Done:** principals, per-person quotas and a deployment-wide cap, required by the platform being
shared.

**Done:** `LocalLlamaProvider` and a `ProviderRouter` that dispatches on the model's provider, so
alias fallback can cross a provider boundary. `lyren/local` is the only alias on which prompt content
never leaves our host.

**Deferred to Phase 3 on purpose:** GGUF selection and the local benchmark. Measuring llama.cpp on an
x86 development machine answers nothing about 2 ARM OCPUs.
→ [local inference plan](research/local-inference-plan.md)

**Done:** `/v1/embeddings` on `cohere.embed-v4.0`, verified live at 1536 dimensions, with explicit
`input_type` because indexing a document as a query degrades recall silently. Embeddings are cached
like chat, so a retrieval benchmark can replay its corpus instead of re-embedding it.

**Done:** streaming SSE with cancellation, verified end to end against the live service.
→ [ADR-0008](decisions/0008-streaming.md)

**Done:** Google sign-in exchanged for a principal-bound session token, `GET /lyren/v1/me`, and the
public sign-in config endpoint. Both questions that blocked the UI are answered: it lives in its own
repository, `lyren-web`, and browsers authenticate with Google.
→ [ADR-0009](decisions/0009-google-sign-in.md)

**Done:** direct sign-up and sign-in with a password, restricted to declared addresses, throttled
per address, with an optional one-time invite token. Google will be added alongside it rather than
replacing it. → [ADR-0010](decisions/0010-direct-password-sign-up.md)

**Next:** the Next.js scaffold in `lyren-web`. It is no longer blocked — password sign-in works
today, so the UI can be built and Google added later without changing the client's contract: both
paths mint the same session token.

The order changed on 2026-11-24. Local inference was first only because it was free; with spend
authorised, the baseline measurement comes first — it is what makes every later component
falsifiable, and the local model then enters as a fourth arm with a measured cost profile instead of
an assumed one.

**Acceptance:** `baseline-v1` has a recorded score, latency and token cost per model, reproducible
from cassettes with zero provider calls; and the OpenAI SDK holds a streaming conversation with a
local model.

## Phase 3 — OCI Deployment
Terraform modules in the private `lyren-infra` repository, each resource classified
Always-Free-confirmed / credit-covered / pay-per-use / unverified, defaulting to the first only.
ARM64 deploy, TLS, restrictive NSG, instance principal, tested backup and restore.

Because real people will use it, this phase also carries a **durable audit log** of per-principal
operations and the **disclosure** that prompts sent to OCI-backed aliases are processed by Oracle as
a third party. Neither is optional once the service is reachable by someone other than the operator.

**Acceptance:** the API answers over HTTPS with authentication, inside the approved envelope; the
infrastructure can be destroyed and rebuilt from code; and every call is attributable to a principal
in a log that survives a restart.

## Phase 4 — Model Routing
Alias policies driven by measured cost and latency; optional OCI provider behind an explicit budget;
controlled fallback; comparative benchmarks across the three callable models plus the local one.
**Acceptance:** the same client contract switches models with no client change, and the choice is
justified by numbers rather than preference.

## Phase 5 — Memory and RAG
Oracle AI Database persistence; vector index at 1536 dimensions; document pipeline (TXT, Markdown,
text-bearing PDF, code, JSON); hybrid retrieval with rerank; the four memory types; verifiable
deletion.

This is the phase where Lyren first stores other people's data, so it carries the data-protection
work with it rather than after it: per-principal isolation, retention with automatic expiry,
opt-in for persistent sensitive content, an access path for a person's own data, and deletion that
also clears derived embeddings and cassettes. A shared counter for rate limiting lands here too,
replacing the in-process one.
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
