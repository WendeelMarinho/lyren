# Lyren

An AI platform on Oracle Cloud Infrastructure with its own runtime, data, agents, models and
infrastructure — not a wrapper over someone else's API.

Lyren serves a **small group of named people**, not one owner and not the open internet. Every API
key identifies a person, so usage is attributed, quotas are individual, and one key can be revoked
without rotating everyone else's. It is built in the open because the engineering is the point: the
reasoning behind each decision is recorded in [`docs/decisions/`](docs/decisions/), and every
measurement is reproducible from the task sets and cassettes in the repository.

**Status: Phase 1.** What works is listed below. Everything else is planned, and the code says so
rather than pretending otherwise. See [docs/IMPLEMENTATION_STATUS.md](docs/IMPLEMENTATION_STATUS.md).

## What works today

| Surface | State |
|---|---|
| `GET /healthz`, `GET /readyz` | implemented, tested |
| `GET /v1/models` (OpenAI-shaped) | implemented, tested |
| `GET /lyren/v1/models` (native, with availability verdicts) | implemented, tested |
| `POST /v1/chat/completions`, non-streaming | implemented, tested |
| Pinned model registry + alias routing + fallback | implemented, tested |
| Principals: per-person identity, quotas, model allow-lists, key revocation | implemented, tested |
| Per-principal and deployment-wide spend caps | implemented, tested |
| Record/replay cache for model calls | implemented, tested |
| Evaluation harness: frozen task set, deterministic graders, benchmark runner | implemented, tested |
| Spend guards: call cap and money cap, failing closed on unknown prices | implemented, tested |
| OCI Generative AI chat provider | implemented; verified by hand against the live service |
| Streaming SSE, embeddings, files, agent runs, memory | **not implemented** — these return an explicit error |
| Local llama.cpp inference | **not implemented** — Phase 2 |
| Web UI | **not implemented** — Phase 2 |

## Run it

```bash
uv venv --python 3.12
uv pip install -e ".[dev]"

cp .env.example .env
cp principals.example.json principals.json

# Mint a key, keep only its hash, and put the hash in principals.json
KEY=$(openssl rand -hex 32)
echo "your api key: $KEY"
printf '%s' "$KEY" | sha256sum

.venv/bin/uvicorn lyren_api.main:app --reload
```

There is **no unauthenticated mode**. A shared deployment needs `LYREN_PRINCIPALS_FILE`; only key
hashes are stored, never the keys. `LYREN_API_KEY_HASHES` is a single-principal shortcut for local
work and the API refuses it outside `LYREN_ENVIRONMENT=local`, because a shared deployment with no
attribution is a configuration error rather than a convenience. See
[ADR-0006](docs/decisions/0006-principals-not-api-keys.md).

Each principal carries a rate limit, a daily call cap and an optional model allow-list, and
`LYREN_DEPLOYMENT_CALLS_PER_DAY` bounds the whole deployment — the sum of individual quotas does
not bound the bill.

To reach OCI Generative AI, set `LYREN_OCI_ENABLED=true` and `LYREN_OCI_COMPARTMENT_ID`. **Every
on-demand call bills.** Left off, the chat route reports the provider as unconfigured instead of
silently degrading.

### With the OpenAI SDK

```python
from openai import OpenAI

client = OpenAI(base_url="http://127.0.0.1:8000/v1", api_key="<your key>")
print([m.id for m in client.models.list().data])
print(
    client.chat.completions.create(
        model="lyren/fast",
        messages=[{"role": "user", "content": "ping"}],
    )
    .choices[0]
    .message.content
)
```

`stream=True` is refused with a clear error. The surface is *partially* OpenAI-compatible and the
docs never claim more than is tested.

## Benchmark a model

The frozen baseline task set has 14 tasks graded by machine — no LLM judging the LLM. This is the
command that spends money, so it runs behind a call cap:

```bash
.venv/bin/python -m lyren_eval --model lyren/fast --taskset baseline-v1 --max-calls 20
```

Prices are not configured, because Oracle does not expose per-token prices through the API and they
have not been measured. The run therefore reports token counts and `cost=UNKNOWN` rather than a
guess. Passing `--max-spend` without a `--price-book` makes the guard **refuse** the call instead of
spending uncapped. See [ADR-0005](docs/decisions/0005-spend-control-in-process.md).

## Verify

```bash
.venv/bin/ruff check . && .venv/bin/ruff format --check .
.venv/bin/mypy packages apps
.venv/bin/pytest
```

## Layout

```
apps/api            FastAPI application
packages/core       settings, errors, structured logging, request ids, principals, metering
packages/inference  model registry, provider ports, record/replay cache, OCI provider
packages/evaluation frozen task sets, graders, benchmark runner, spend guards
tests/unit          offline tests — no network, no credentials
infrastructure/     Dockerfile (arm64 target), compose, CI
                    OCI Terraform, host bootstrap and the tenancy inventory live in a
                    separate private repository, lyren-infra
docs/               architecture, discovery, reuse matrix, ADRs
```

## License

MIT — see [LICENSE](LICENSE).
