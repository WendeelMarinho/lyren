# Implementation Status

Updated **2026-11-23** (third pass). The one place that says what is real. Five states, and nothing is promoted
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
| `POST /v1/embeddings`: one vector per input, in order, OpenAI shape | `tests/unit/test_embeddings_api.py` |
| `input_type` reaches the provider and is reported back | `tests/unit/test_embeddings_api.py` |
| A chat model is refused on the embeddings route, and the reverse | `tests/unit/test_embeddings_api.py` |
| Embeddings count against the principal's quota | `tests/unit/test_embeddings_api.py` |
| Embeddings cached separately per input type | `tests/unit/test_cache.py` |
| A key resolves to a named principal; unknown, revoked and disabled fail alike | `tests/unit/test_identity.py` |
| Sign-up works for a declared address and is refused for any other | `tests/unit/test_auth_api.py` |
| Registering twice and an unclaimed address answer identically | `tests/unit/test_auth_api.py` |
| An optional registration token is required when a principal declares one | `tests/unit/test_auth_api.py` |
| A wrong password and an unknown address answer identically | `tests/unit/test_auth_api.py` |
| Repeated failures lock an address out; success clears the counter | `test_auth_api.py`, `test_credentials.py` |
| Password change requires the current password and replaces the old one | `tests/unit/test_auth_api.py` |
| Password length enforced; the address itself refused as a password | `tests/unit/test_credentials.py` |
| Hashes persist as argon2 strings, mode 600, with no temporary file left behind | `tests/unit/test_credentials.py` |
| Google id token verified for signature, issuer, audience, expiry, email_verified | `tests/unit/test_federation.py` |
| A token for another audience or signed by another key is refused | `tests/unit/test_federation.py` |
| Workspace domain restriction, including refusing a personal account | `tests/unit/test_federation.py` |
| A Google account no principal claims is refused — no auto-provisioning | `test_federation.py`, `test_auth_api.py` |
| One address claimed by two principals fails at startup | `tests/unit/test_identity.py` |
| Session token round-trips to its principal; expired, tampered and wrong-type refused | `tests/unit/test_federation.py` |
| An API key is never mistaken for a session token, or the reverse | `tests/unit/test_federation.py` |
| Both credential types reach the same principal and the same attribution | `tests/unit/test_auth_api.py` |
| `GET /lyren/v1/me` reports quota and real usage | `tests/unit/test_auth_api.py` |
| Revoking one key leaves a principal's other keys working | `tests/unit/test_identity.py` |
| A key referencing a missing principal is rejected at construction | `tests/unit/test_identity.py` |
| Per-principal rate limit and daily cap, refused before any provider call | `test_metering.py`, `test_api.py` |
| One principal exhausting its quota does not block another | `test_metering.py`, `test_api.py` |
| Deployment-wide daily cap binds even when no principal is near its own | `tests/unit/test_metering.py` |
| Daily counters reset on a new day; the rate window slides | `tests/unit/test_metering.py` |
| Model allow-list enforced on call and reflected in `/v1/models` | `tests/unit/test_api.py` |
| Output tokens capped by the stricter of alias budget and principal quota | `tests/unit/test_api.py` |
| The dev auth shortcut is refused outside a local environment | `tests/unit/test_api.py` |
| `LYREN_API_KEY_HASHES` parses from the environment as comma-separated | `tests/unit/test_api.py` |
| Streaming SSE: role frame, content deltas, finish frame, `[DONE]` | `tests/unit/test_streaming.py` |
| A disconnected client still spends its quota | `tests/unit/test_streaming.py` |
| A failure after the first byte becomes an error frame, not a status | `tests/unit/test_streaming.py` |
| Alias fallback works before the first chunk and is refused after | `tests/unit/test_streaming.py` |
| A streamed answer is recorded and replayed as one chunk | `tests/unit/test_streaming.py` |
| A cancelled stream is not recorded | `tests/unit/test_streaming.py` |
| A streamed and a non-streamed call share one cassette | `tests/unit/test_streaming.py` |
| The COHERE summary event does not duplicate the answer | `tests/unit/test_oci_provider.py` |
| A non-streaming provider refuses a streamed request up front | `tests/unit/test_api.py` |
| Alias resolution, ordering, fallback, probe recording | `test_api.py`, `test_registry.py` |
| Per-alias output-token cap overriding a larger client request | `tests/unit/test_api.py` |
| Record/replay cache: key stability, pin invalidation, four modes | `tests/unit/test_cache.py` |
| OCI error mapping: 404 vs zero-quota 429 vs real throttling | `tests/unit/test_oci_provider.py` |
| Request id propagation and echo | `tests/unit/test_api.py` |
| Provider router dispatches by model and names what is configured | `tests/unit/test_router.py` |
| Local llama.cpp provider: probe, parse, loading server, unreachable server | `tests/unit/test_local_llama.py` |
| An unsupported role is refused by the local provider rather than dropped | `tests/unit/test_local_llama.py` |
| The local model is not callable until a probe verifies it | `tests/unit/test_registry.py` |
| Secret redaction in logs | `lyren_core.logging` |
| Deterministic graders: exact, cased, contains, regex, numeric, json keys | `tests/unit/test_eval_graders.py` |
| Numeric parsing refuses to guess a thousands separator | `tests/unit/test_eval_graders.py` |
| Frozen baseline task set loads; duplicate ids and unknown graders rejected | `tests/unit/test_eval_runner.py` |
| Benchmark runner: pass/fail/error accounting, per-tag breakdown, latency | `tests/unit/test_eval_runner.py` |
| Call cap enforced with no price information | `tests/unit/test_eval_budget.py` |
| Money cap fails closed when a model has no configured price | `tests/unit/test_eval_budget.py` |
| Cache hits counted but never charged | `tests/unit/test_eval_budget.py` |
| Spend ledger flags an incomplete cost total | `tests/unit/test_eval_budget.py` |
| Weakness probes scored apart from the discriminating set | `tests/unit/test_eval_runner.py` |
| Repeated attempts reach the provider separately and expose instability | `test_eval_runner.py`, `test_cache.py` |
| A run of repeated identical errors aborts and reports no score | `tests/unit/test_eval_runner.py` |
| Provider 401/403 reported as a credential failure, not a model failure | `tests/unit/test_oci_provider.py` |

Gates: `ruff check`, `ruff format --check`, `mypy --strict` over `packages` and `apps`, and
`pytest` — **221 tests passing, 88% coverage** (floor 80%, enforced in CI).

## Implemented, hand-checked

| Item | What was checked |
|---|---|
| `OCIGenerativeAIProvider` chat, GENERIC and COHERE formats | Live calls on 2026-11-23 returned completions from the three callable models |
| `OCIGenerativeAIProvider.embed` | Live call on 2026-11-23 returned 1536-dim vectors with correct semantic ordering |
| Streamed chat, both formats, end to end through the API | Live on 2026-11-23: 31 frames, quota counted, replay served from the cassette in 3 frames |
| Security-token, API-key and instance-principal auth paths | Security-token path exercised; the other two are written but not run |

## Planned

GGUF selection and the local benchmark, which need ARM hardware; streaming SSE; `/v1/embeddings`; web UI on assistant-ui;
Terraform modules; Oracle AI Database persistence; document pipeline and hybrid retrieval; memory
system; LangGraph orchestration; isolated executor; Lyren Code via opencode; evaluation harness.

Required by the platform being shared rather than personal, and not yet built: a durable audit
log, per-principal data isolation in storage, verifiable deletion of a person's data, disclosure
that prompts reach Oracle as a third-party processor, and retention with automatic expiry. All are
Phase 3 or 5, and all are cheaper to build before there is data than to retrofit after. See
[SECURITY_MODEL.md](SECURITY_MODEL.md).

Documents not yet written, deliberately left absent rather than stubbed:
`OCI_COST_MODEL.md`, `DATA_MODEL.md`, `API_SPECIFICATION.md` (the OpenAPI schema at `/openapi.json`
is currently the contract), `TEST_STRATEGY.md`.

## Unavailable in this tenancy

| Item | Reason |
|---|---|
| Fine-tuning, LoRA/QLoRA, any training | zero GPU quota; every `dedicated-unit-*` is 0 |
| Dedicated model serving, imported models | quota 0 |
| Gemini and Grok model families | per-model request quotas are 0 in this tenancy |
| `openai.gpt-oss-120b` / `20b` | catalog-listed, 404 on call |
| Cross-AD high availability | one availability domain |
| A shared rate counter across workers | metering is in-process; the deployment runs one worker until Phase 5 |

## Needs authorisation

Creating any OCI resource — **including the protective OCI budget with alert rules**, which is free
but is still a resource; exposing the API to the internet; requesting a service-limit increase (now
worth doing for Gemini and Grok, whose per-model quotas are zero here); **making this repository
public**.

Spending on OCI Generative AI on-demand calls is **authorised** as of 2026-11-23, bounded by the
in-process call cap. Infrastructure lives in a separate private repository, `lyren-infra`.

## Open questions

1. **Always Free or pay-as-you-go?** Unresolved via API: no promotional credit appears in
   `CREDIT`/`ALLCREDIT`/`EXPIREDCREDIT`, so the available allowance reads as pay-as-you-go headroom
   with **no automatic stop**. Console → Billing & Cost Management settles it. Tenancy specifics are
   in the private `lyren-infra` repository.
2. **Per-token price of each callable model.** Not exposed by the API, not measured. Until an
   invoice exists the money cap cannot be enforced and the harness reports `cost=UNKNOWN`. The first
   real benchmark run is the calibration that fixes this.
3. Max context window per callable model — not exposed by the API, not measured, left `None`.
4. **No GGUF is selected and no local benchmark exists.** The provider is built and tested, but
   measuring llama.cpp on an x86 development machine answers nothing about 2 ARM OCPUs, so the
   selection runs on the target hardware in Phase 3.
   → [local inference plan](research/local-inference-plan.md)
5. **Quality is not measurable at the current task-set size.** `baseline-v2` ran (22 tasks, 20
   discriminating, 2 attempts each, 131 calls) and the three callable models landed within 2.5
   points — about 0.36 of a standard error. Separating them by 5 points would take roughly 680
   tasks per model. Cost and latency separate cleanly at this size; quality does not, which is why
   the router uses a quality *floor* rather than a ranking.
   → [baseline-v2 results](research/baseline-v2-results.md)
6. **Token attribution is incomplete for streamed traffic.** OCI reports no token counts on a
   stream, so a streamed call is counted against the quotas but its tokens are recorded as unknown
   rather than zero.
7. **No per-token price is known**, so every run reports `cost=UNKNOWN` and spend is bounded by call
   count rather than by money.
