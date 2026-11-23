# Lyren

A personal AI platform on Oracle Cloud Infrastructure: its own runtime, data, agents, models and
infrastructure — not a wrapper over someone else's API.

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
KEY=$(openssl rand -hex 32)
echo "your api key: $KEY"
printf 'LYREN_API_KEY_HASHES=%s\n' "$(printf '%s' "$KEY" | sha256sum | cut -d' ' -f1)" >> .env

.venv/bin/uvicorn lyren_api.main:app --reload
```

The API refuses to start serving authenticated routes with an empty `LYREN_API_KEY_HASHES`: there is
no unauthenticated mode. Only key hashes are stored, never the keys.

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
packages/core       settings, errors, structured logging, request ids
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
