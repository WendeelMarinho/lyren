# Implementation Status

Updated **2026-11-24**. The one place that says what is real. Five states, and nothing is promoted
without the verification named.

- **Verified** — implemented, with passing automated tests.
- **Implemented, hand-checked** — working code, exercised against the live service, no automated test.
- **Planned** — designed, not built.
- **Unavailable** — blocked by the tenancy.
- **Needs authorisation** — buildable, but may bill or expose a service.

## Verified

| Item | Evidence |
|---|---|
| `GET /healthz`, `GET /readyz` with per-check reporting | `tests/unit/test_api.py` |
| `GET /v1/models`, OpenAI shape, excludes non-callable models | `tests/unit/test_api.py` |
| `GET /lyren/v1/models` exposing availability verdicts | `tests/unit/test_api.py` |
| `POST /v1/chat/completions`, non-streaming | `tests/unit/test_api.py` |
| Bearer auth against SHA-256 hashes, constant-time compare | `tests/unit/test_api.py` |
| Streaming refused explicitly rather than ignored | `tests/unit/test_api.py` |
| Alias resolution, ordering, fallback, probe recording | `test_api.py`, `test_registry.py` |
| Per-alias output-token cap overriding a larger client request | `tests/unit/test_api.py` |
| Record/replay cache: key stability, pin invalidation, four modes | `tests/unit/test_cache.py` |
| OCI error mapping: 404 vs zero-quota 429 vs real throttling | `tests/unit/test_oci_provider.py` |
| Request id propagation and echo | `tests/unit/test_api.py` |
| Secret redaction in logs | `lyren_core.logging` |
| Deterministic graders: exact, cased, contains, regex, numeric, json keys | `tests/unit/test_eval_graders.py` |
| Numeric parsing refuses to guess a thousands separator | `tests/unit/test_eval_graders.py` |
| Frozen baseline task set loads; duplicate ids and unknown graders rejected | `tests/unit/test_eval_runner.py` |
| Benchmark runner: pass/fail/error accounting, per-tag breakdown, latency | `tests/unit/test_eval_runner.py` |
| Call cap enforced with no price information | `tests/unit/test_eval_budget.py` |
| Money cap fails closed when a model has no configured price | `tests/unit/test_eval_budget.py` |
| Cache hits counted but never charged | `tests/unit/test_eval_budget.py` |
| Spend ledger flags an incomplete cost total | `tests/unit/test_eval_budget.py` |

Gates: `ruff check`, `ruff format --check`, `mypy --strict` over `packages` and `apps`, and
`pytest` — **61 tests passing, 81% coverage** (floor 80%, enforced in CI).

## Implemented, hand-checked

| Item | What was checked |
|---|---|
| `OCIGenerativeAIProvider` chat, GENERIC and COHERE formats | Live calls on 2026-11-23 returned completions from the three callable models |
| Security-token, API-key and instance-principal auth paths | Security-token path exercised; the other two are written but not run |

## Planned

Local llama.cpp provider as a fourth routing arm; streaming SSE; `/v1/embeddings`; web UI on assistant-ui;
Terraform modules; Oracle AI Database persistence; document pipeline and hybrid retrieval; memory
system; LangGraph orchestration; isolated executor; Lyren Code via opencode; evaluation harness.

Documents not yet written, deliberately left absent rather than stubbed:
`OCI_COST_MODEL.md`, `DATA_MODEL.md`, `API_SPECIFICATION.md` (the OpenAPI schema at `/openapi.json`
is currently the contract), `TEST_STRATEGY.md`.

## Unavailable in this tenancy

| Item | Reason |
|---|---|
| Fine-tuning, LoRA/QLoRA, any training | zero GPU quota; every `dedicated-unit-*` is 0 |
| Dedicated model serving, imported models | quota 0 |
| Gemini and Grok model families | per-model request quotas are 0 |
| `openai.gpt-oss-120b` / `20b` | catalog-listed, 404 on call |
| Cross-AD high availability | one availability domain |

## Needs authorisation

Creating any OCI resource — **including the protective OCI budget with alert rules**, which is free
but is still a resource; exposing the API to the internet; requesting a service-limit increase (now
worth doing for Gemini and Grok, whose per-model quotas are 0); making this repository public.

Spending on OCI Generative AI on-demand calls is **authorised** as of 2026-11-24, bounded by the
in-process call cap.

## Open questions

1. **Always Free or pay-as-you-go?** Unresolved via API. A $300 allowance was reported on
   2026-11-24, but no promotional credit appears in `CREDIT`/`ALLCREDIT`/`EXPIREDCREDIT`, so it reads
   as pay-as-you-go headroom with **no automatic stop**. Console → Billing & Cost Management settles it.
2. **Per-token price of each callable model.** Not exposed by the API, not measured. Until an
   invoice exists the money cap cannot be enforced and the harness reports `cost=UNKNOWN`. The first
   real benchmark run is the calibration that fixes this.
3. Max context window per callable model — not exposed by the API, not measured, left `None`.
