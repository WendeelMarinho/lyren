# Local inference — plan, and why the measurement waits

Status: the **provider is built and tested**; no GGUF has been selected and no local benchmark has
been run. This file records why the selection is deliberately deferred and what will decide it.

## Why local inference matters here beyond cost

The original reason was cost. The stronger reason arrived with the platform becoming shared: **every
prompt sent to an OCI-backed alias is processed by Oracle as a third party.** `lyren/local` is the
only alias on which content never leaves our own host. For a group handling anything they would not
hand to a third party, that is a capability rather than an optimisation.

This is also why the local provider is not merely "the cheap arm". A cheap arm can be dropped when
the budget grows; a privacy boundary cannot.

## Why the GGUF choice is not made yet

**Benchmarking llama.cpp on an x86 development machine answers nothing about 2 ARM OCPUs.** Tokens
per second, time to first token and memory headroom are all properties of the target hardware, and
the target is Ampere A1. A number measured here would be a number about the wrong machine, and
recording it would invite exactly the false confidence this project is built to avoid.

The selection therefore runs on the OCI instance in Phase 3, using the same harness that measured
the hosted models — the comparison is only meaningful if it is the same task set, the same graders
and the same cassette discipline.

## Candidates to evaluate

**Treat this list as a starting point to re-check at selection time, not as current.** It reflects
what was available as of this writing; the small-model field moves quickly and a newer release may
dominate it.

| Family | Size | Q4_K_M file, estimated | Why it is a candidate |
|---|---|---|---|
| Qwen2.5 Instruct | 1.5B / 3B | ~1.0 / ~2.0 GB | strong multilingual coverage for its size |
| Llama 3.2 Instruct | 1B / 3B | ~0.8 / ~2.0 GB | well-supported tooling, documented tool calling |
| Gemma 2 | 2B | ~1.6 GB | strong quality per parameter |
| Phi-3.5-mini | 3.8B | ~2.3 GB | reasoning-oriented at the top of the range |
| SmolLM2 Instruct | 1.7B | ~1.1 GB | lower bound on what is usable at all |

Sizes are **estimates from quantisation arithmetic, not measurements.** Runtime memory is the file
plus the KV cache plus server overhead, so budget well above the file size. Against a ~12 GB envelope
already holding the OS, Docker, the API and a worker, the practical ceiling is the 1B-4B range: a
7-8B quant needs roughly 5 GB and is out.

## What the benchmark must measure

Quality on `baseline-v3` is necessary but not where the decision gets made, for the reason the hosted
comparison established: at this task-set size, quality does not separate models and cost and latency
do. → [baseline-v2 results](baseline-v2-results.md)

So the deciding axes are:

- **Tokens per second** and **time to first token**, on ARM, under the real thread count.
- **Resident memory** at the configured context length, measured rather than estimated.
- **pt-BR quality specifically.** Most small-model reporting is English-first, and this platform is
  used in Portuguese. The task set already carries `ptbr`-tagged tasks for that reason.
- **Tool calling**, since the agent runtime of Phase 6 depends on it and small models vary wildly.
- A **quality floor** on `baseline-v3`: the local arm does not need to win, it needs not to fall
  below the floor at which routing to it is acceptable.

## How the provider handles not knowing

The registry seeds `local/llama-cpp` as `UNVERIFIED`, which means **not callable**. Startup probes
`/health` and records the verdict, so a server that is down or holding no model is skipped by alias
resolution instead of failing a request. Which GGUF is loaded is declared in configuration
(`LYREN_LOCAL_MODEL_ID`) rather than inferred: the server answers for whatever it has, and
attributing a benchmark to the wrong model silently is worse than refusing to guess.
