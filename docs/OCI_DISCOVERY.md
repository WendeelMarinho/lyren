# OCI Discovery

Read-only audit of the target tenancy. **Probed 2026-11-23.** Every line below was obtained from the
OCI API or from a real inference call — nothing here is inferred from documentation or marketing
pages. Do not re-run this audit to re-derive it; re-run it to detect drift.

No OCIDs, tokens, keys or wallets are recorded in this file.

## Tenancy

| Property | Value |
|---|---|
| Tenancy name | `wendeel` |
| Home region | `sa-saopaulo-1` (GRU) |
| Subscribed regions | `sa-saopaulo-1` only |
| Availability domains | **1** (`...SA-SAOPAULO-1-AD-1`) |
| Compartments | root only — no sub-compartments |
| Object Storage namespace | present |
| Existing resources | **none** — no compute, no database, no VCN, no bucket |
| Cost, Nov 2026 | zero |
| Credits (CREDIT / ALLCREDIT / EXPIREDCREDIT) | **empty** — no promotional credit, active or expired |

**Single AD** means no cross-AD high availability, and Ampere A1 capacity in one AD is where
*out of host capacity* errors show up.

## Account type — UNRESOLVED

The operator reports "free tier". The API cannot distinguish an **Always Free** tenancy from a
**pay-as-you-go** one: there is no account-type field, and the absence of credit records only rules
out an active trial. Service limits do not settle it either, because the Always Free A1 allowance is
expressed in OCPU-hours per month rather than as a service limit.

**Consequence, and it is the governing assumption of this project:** size everything for the Always
Free envelope (~2 OCPU ARM / 12 GB RAM running 24/7). A limit is a ceiling, not a free allowance.

To resolve: Console → Billing & Cost Management.

**Re-checked 2026-11-24**, after a $300 allowance was reported as available: credits are still empty
across `CREDIT`, `ALLCREDIT` and `EXPIREDCREDIT`, recorded cost is still zero, and no OCI budget is
configured. So the $300 reads as a payment-method-backed allowance, not an Oracle credit grant —
which means **nothing stops billing at $300**. The spend cap is enforced in the application instead;
see [ADR-0005](decisions/0005-spend-control-in-process.md). The probe calls of 2026-11-23 had still
registered no cost 24h later, which is consistent either with them being free or with usage lag.

## Compute limits

| Limit | Value | Scope |
|---|---|---|
| `standard-a1-core-regional-count` | **16** | region — the binding cap |
| `standard-a1-memory-regional-count` | **96 GB** | region — the binding cap |
| `standard-a1-core-count` / `memory-count` | 41 / 277 GB | AD |
| `standard-e2-micro-core-count` | 2 (0 used) | AD — the Always Free AMD micro shapes |
| `standard-e3` / `e4` / `e5` core count | 16 / 16 / 13 | AD |
| **every GPU shape** | **0** | AD |
| Block storage, total | 30,720 GB ceiling; 200 GB on the free line | region |

**Zero GPU quota across every shape.** No training and no fine-tuning happens in this tenancy.

## Generative AI (`ai-generative`)

Only two quotas are non-zero:

| Quota | Value |
|---|---|
| `max-on-demand-chat-request-per-minute-count` | **500** |
| `max-on-demand-embed-request-per-minute-count` | **1000** |

Everything else is zero, including: all Gemini variants, all Grok/xAI variants, **every
`dedicated-unit-*`** (so no fine-tuning and no dedicated serving), `imported-model-count`,
`sandbox-*`, `warmpool-*`, `routing-profile-count`, `private-endpoint-count`.

### Models — verdicts from real calls, not from the catalog

The catalog returned 41 models, of which 8 chat entries looked live. **Three answer.**

| Model | Capability | Verdict |
|---|---|---|
| `cohere.command-a-03-2025` | chat | **works** |
| `meta.llama-3.3-70b-instruct` | chat | **works** |
| `meta.llama-4-scout-17b-16e-instruct` | chat | **works** (MoE, 17B active) |
| `cohere.embed-v4.0` | embeddings | **works**, 1536 dimensions |
| `cohere.rerank-v4.0-fast` | rerank | **works** |
| `google.gemini-2.5-flash` | chat | 429 — `gemini-2-5-flash-requests-per-minute-count` is 0 |
| `openai.gpt-oss-120b`, `openai.gpt-oss-20b` | chat | **404 not found** |
| `cohere.command-r-08-2024` | chat | **404 not found** |
| `meta.llama-3.1-70b-instruct`, `meta.llama-3-70b-instruct` | chat | **404 not found** |

Why the catalog misleads, and this is a design input rather than a footnote:

- Display-names are **duplicated**, and the entry whose `time-on-demand-retired` is null is the
  dedicated-cluster variant — not an on-demand offer.
- `time-on-demand-retired` set to **epoch zero** (`1970-01-01`) means not served on demand. It reads
  like "never retired".

Hence `packages/inference/lyren_inference/registry.py` stores an `Availability` verdict per model,
pins versions, and records probe results at runtime. Never hardcode a model list from the catalog.

## Not verified

- Max context window per model: not exposed by the API and not measured. Left `None` in the registry
  rather than guessed.
- Per-token prices, and therefore whether the probe calls above billed. Usage data lags by hours.
- Autonomous AI Database Always Free availability: not probed.
- IAM dynamic groups, policies, VCN and NSG capability: not probed.
- `VM.Standard.A1.Flex` actual provisioning capacity in this single AD.
- The OpenAI-compatible endpoint Oracle documents: not probed.
