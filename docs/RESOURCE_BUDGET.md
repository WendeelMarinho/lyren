# Resource Budget

The governing constraint is the **Always Free envelope: ~2 OCPU ARM, 12 GB RAM**, on a single
availability domain.

This is a requirement rather than caution. The account is a **Free Trial**, so its higher limits are
temporary: when the trial ends the account reverts to Always Free and anything provisioned above
that allowance is disabled and then deleted. An instance sized to the trial's limits would collapse
on its expiry date.

A limit is also not an allowance even within Always Free: the A1 entitlement is measured in
**OCPU-hours per month**, so an instance sized inside the service limit can still exceed it by
running continuously. The real limit values live in the private infrastructure repository
(`lyren-infra`, `docs/TENANCY_INVENTORY.md`).

## Target allocation on one A1 VM

| Component | RAM | Notes |
|---|---|---|
| OS and Docker | ~1.0 GB | |
| Lyren API (uvicorn) | ~0.5 GB | capped at 1 GB in compose |
| Worker | ~0.5 GB | Phase 6 |
| Reverse proxy (TLS) | ~0.1 GB | Phase 3 |
| llama.cpp, 1B-4B quantised | ~2-4 GB | Phase 2; a 7-8B quant needs ~5 GB and is out |
| Headroom | remainder | fragmentation and spikes |

Oracle AI Database Always Free does **not** consume VM RAM — it is a separate allowance. Using it
instead of a co-hosted Postgres is the single biggest RAM saving available.

Observability stays off-box. Self-hosting Prometheus and Grafana would cost roughly 1.5 GB.

## Hard constraints

- **No GPU quota.** No training, no fine-tuning, no dedicated serving units. Those workloads do not
  run on this infrastructure at all.
- **One availability domain.** No cross-AD HA; expect *out of host capacity* on A1 provisioning, so
  the bootstrap retries rather than assumes.
- **The free AMD micro shapes are reserved for the isolated code executor:** separate host, egress
  blocked, no instance principal attached, cgroup CPU and memory caps, hard timeout. Model-authored
  code must not run where credentials live — the instance metadata endpoint at `169.254.169.254`
  hands an instance-principal token to any local HTTP request.
- Boot volume ~50 GB, model cache on its own volume, logs with retention.

## Spend controls

`LYREN_ALLOW_PAID_PROVIDERS` defaults to `false`, and alias policies carry their own `allow_paid`
flag, so a fallback never crosses into a billing provider implicitly. Per-alias `max_output_tokens`
caps a client that asks for more.

The budget is **shared among several people**, so there are two layers. Per-principal quotas
(`requests_per_minute`, `calls_per_day`) stop one person starving another;
`LYREN_DEPLOYMENT_CALLS_PER_DAY` stops the group exhausting the bill, because the sum of individual
quotas bounds nothing financially. Both are checked before any provider call, so a refused request
costs nothing. → [ADR-0006](decisions/0006-principals-not-api-keys.md)

For benchmark runs, `lyren_eval.budget.BudgetGuard` is the hard stop: a **call cap** that works without prices, and a
**money cap** that refuses the call when a model's price is unknown rather than assuming it is free.
An OCI budget only alerts and is not the control.
→ [ADR-0005](decisions/0005-spend-control-in-process.md)

**Unknown:** the per-token price of each model, and the spend itself. Oracle publishes no price
through the API, and both `COST` and `USAGE` return nothing after roughly 200 Generative AI calls —
so the platform cannot read its own consumption at all. Every call is treated as billable and
bounded by call count rather than by money. See [OCI_DISCOVERY.md](OCI_DISCOVERY.md).

## Where to spend, while the trial lasts

Keep the always-on components inside the Always Free envelope and spend the trial on **bursty,
high-value** work: benchmark and evaluation runs. Trial credits are the wrong thing to convert into
standing capacity — a permanently larger A1 instance would consume them for capacity the platform
does not need, and would then be disabled when the trial ends anyway.
