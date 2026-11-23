# Security Model

Security is part of the architecture from v1, not a later phase. This file states what is enforced
now and what is explicitly not yet.

## Enforced now

| Control | Where |
|---|---|
| Bearer API keys, stored only as SHA-256 hashes, compared in constant time | `apps/api/lyren_api/deps.py` |
| No unauthenticated mode — empty `LYREN_API_KEY_HASHES` fails the request | `deps.require_api_key` |
| Secret redaction in logs: OCIDs, bearer tokens, `sk-`/`gho_`/`ghp_` keys, PEM private keys | `lyren_core.logging.redact` |
| Request ids on every response, for traceability | `lyren_api.main` |
| Input validation at the boundary via Pydantic, with bounded `max_tokens` and `temperature` | `routes/chat.py` |
| Per-alias output budget capping the client's request | `routes/chat.py` |
| Paid providers gated by `LYREN_ALLOW_PAID_PROVIDERS`, default `false` | `lyren_core.settings` |
| Errors carry a code and no provider internals beyond a redacted detail | `lyren_api.main` |
| Container runs as a non-root user; API bound to loopback in compose | `infrastructure/docker/` |
| No secrets in Git; `.env` ignored, only `.env.example` tracked | `.gitignore` |

## Not yet implemented — and the consequence

| Gap | Consequence | Phase |
|---|---|---|
| Rate limiting | a leaked key can exhaust spend | 3 |
| TLS termination and restrictive CORS | API is loopback-only until then | 3 |
| Session auth for the web UI | no UI exists yet | 2 |
| Key revocation and rotation workflow | keys are static config today | 3 |
| Isolated executor for model-authored code | **autonomous execution stays off** | 6 |
| Prompt-injection defences for retrieved documents | no retrieval exists yet | 5 |
| Upload validation and limits | no upload endpoint exists yet | 5 |
| Audit log of privileged operations | 3 |

## The executor threat, stated plainly

An agent that writes and runs code must not run it where the credentials live. On OCI, the instance
metadata endpoint `169.254.169.254` hands out instance-principal tokens to anything that can make a
local HTTP request, so model-authored code on the API host is equivalent to granting it the host's
IAM identity. Docker on the same VM is not a security boundary against that.

The plan: one of the two free `VM.Standard.E2.1.Micro` shapes as a dedicated executor, with egress
blocked, **no instance principal attached**, cgroup CPU and memory caps, and a hard timeout. Until
that exists, autonomous execution is disabled and code runs only with human approval.

## Trust boundaries

Retrieved documents, tool output and model output are **untrusted input**. Instructions found inside
them are never executed. A model asserting a fact does not make it a fact: memory entries carry a
source and a review state, and the evaluation harness scores claims against verifiable artifacts.

## Credentials

Prefer OCI instance principals on the VM over long-lived API keys. Locally, the security-token
session is short-lived by design. Least-privilege IAM policies, scoped to the compartment that holds
Lyren resources.
