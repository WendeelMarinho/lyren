# Security and Data Protection Model

Lyren serves a small group of named people. That changes the question from "can the operator be
compromised" to "can one person harm another, or can anyone harm all of them" — and it brings the
users' data under obligations the operator does not get to choose.

This file states what is enforced now and what is explicitly not yet. Nothing here is aspirational:
if a control is listed as enforced, there is a test for it.

## Enforced now

| Control | Where |
|---|---|
| A key resolves to a **named principal**; usage is attributable | `lyren_core/identity.py` |
| Keys are stored **only as SHA-256 hashes** | `identity.hash_key` |
| Unknown key, revoked key and disabled principal fail **identically** | `PrincipalStore.resolve` |
| Revocation keeps the record (`revoked_at`), preserving the access trail | `ApiKeyRecord` |
| A principal may hold several keys, so one can be rotated alone | `ApiKeyRecord.principal_id` |
| **Per-principal** rate limit and daily call cap, checked before any provider call | `lyren_core/metering.py` |
| **Deployment-wide** daily cap, because the sum of individual quotas bounds nothing | `UsageMeter` |
| Per-principal model allow-list, enforced on call **and** on `/v1/models` | `Principal.may_use` |
| Output tokens capped by the stricter of alias budget and principal quota | `routes/chat.py` |
| No unauthenticated mode; the dev shortcut is **refused** outside a local environment | `deps.get_principal_store` |
| Secret redaction in logs: OCIDs, bearer tokens, `sk-`/`gho_`/`ghp_`, PEM private keys | `lyren_core/logging.py` |
| Request ids on every response | `lyren_api/main.py` |
| Boundary validation with bounded `max_tokens` and `temperature` | `routes/chat.py` |
| Paid providers gated, default off; fallback never crosses implicitly | `lyren_core/settings.py` |
| Errors carry a code and no provider internals beyond a redacted detail | `lyren_api/main.py` |
| Container runs as a non-root user; API bound to loopback in compose | `infrastructure/docker/` |
| No secrets in Git: `.env` and `principals.json` ignored, only examples tracked | `.gitignore` |

## Known limitation, stated rather than hidden

**Metering is in-process, so it is per-worker.** Two API workers each allow the full rate, which
means the real rate limit is the configured one multiplied by the worker count. The daily caps —
the ones that bound spend — are therefore the conservative controls, and the deployment runs a
single worker until there is a shared counter. That counter arrives with the database in Phase 5.
Recorded in [ADR-0006](decisions/0006-principals-not-api-keys.md).

## Not yet implemented, and what it costs

| Gap | Consequence | Phase |
|---|---|---|
| TLS termination and restrictive CORS | API is loopback-only until then; **do not expose it** | 3 |
| Audit log of privileged and per-principal operations | attribution exists in metering but is not durable | 3 |
| Key rotation and revocation workflow | revocation works, but by hand-editing a JSON file | 3/5 |
| Session auth for the web UI | no UI exists yet | 2 |
| Per-principal data isolation in storage | no persistence yet, so nothing is co-mingled either | 5 |
| Verifiable deletion of a person's data | required before real data is stored | 5 |
| Prompt-injection defences for retrieved documents | no retrieval exists yet | 5 |
| Upload validation and limits | no upload endpoint exists yet | 5 |
| Isolated executor for model-authored code | **autonomous execution stays off** | 6 |

## The executor threat, stated plainly

An agent that writes and runs code must not run it where credentials live. On OCI the instance
metadata endpoint `169.254.169.254` hands an instance-principal token to anything that can make a
local HTTP request, so model-authored code on the API host is equivalent to granting it the host's
IAM identity. Docker on the same VM is not a security boundary against that.

The plan: one of the free `VM.Standard.E2.1.Micro` shapes as a dedicated executor, egress blocked,
**no instance principal attached**, cgroup CPU and memory caps, hard timeout. Until that exists,
autonomous execution is disabled and code runs only with human approval.

## Trust boundaries

Retrieved documents, tool output and model output are **untrusted input**. Instructions found inside
them are never executed. A model asserting a fact does not make it a fact: memory entries carry a
source and a review state, and the evaluation harness grades claims against machine-checkable
answers rather than against another model's opinion.

## Data protection

Lyren handles other people's data, so these are obligations rather than preferences. Brazilian LGPD
applies.

**Already true:**

- Only key hashes are stored, never keys. A compromised store does not yield anyone's credential.
- Prompts are not logged. Log redaction covers credential shapes, and log level defaults to
  information about requests rather than their contents.
- Per-principal attribution exists, which is what makes a future deletion request answerable.

**Required before any personal data is persisted, which is Phase 5:**

- **Disclosure that prompts leave the deployment.** Content sent to `lyren/*` aliases backed by OCI
  Generative AI is processed by Oracle as a third party. Users must be told this before they use it;
  it is not something to discover later. The local llama.cpp provider is the option that keeps
  content on our own host, which is a reason to build it beyond cost.
- **Purpose limitation and retention.** Conversation history and memory need a stated purpose, a
  retention period and automatic expiry — not indefinite accumulation by default.
- **Deletion that is verifiable**, covering conversations, memory entries, derived embeddings and
  cassettes. A record deleted from one table and left in a vector index is not deleted.
- **Opt-in for persistent sensitive content**, per the memory design, rather than persisting
  everything by default.
- **An access path for a person's own data**, since the right to access is as real as the right to
  delete.

Documenting these now is deliberate: the controls are far cheaper to build before there is data than
to retrofit after.

## Credentials

Prefer OCI **instance principals** on the host over long-lived API keys. Locally, an API-key profile
is used because the browser session token expires every 60 minutes and cannot survive a long
benchmark; the private key sits outside every repository and is never committed. IAM policies are
least-privilege and scoped to the compartment holding Lyren resources. The tenancy's identifiers and
limits live in the private `lyren-infra` repository.
