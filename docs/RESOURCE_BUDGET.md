# Resource Budget

The governing assumption is the **Always Free envelope: ~2 OCPU ARM, 12 GB RAM**. The tenancy's
service limits are higher (16 OCPU / 96 GB regional for A1), but a limit is a ceiling and not a free
allowance, and the account type is unresolved. See [OCI_DISCOVERY.md](OCI_DISCOVERY.md).

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

- **Zero GPU quota.** No training, no fine-tuning, no dedicated serving units in this tenancy.
- **One availability domain.** No cross-AD HA; expect *out of host capacity* on A1 provisioning.
- **Two E2.1.Micro shapes free and unused.** Reserved for the isolated code executor: separate VM,
  egress blocked, no instance principal attached. Model-authored code must not run where the
  credentials live — the instance metadata endpoint hands out instance-principal tokens.
- Block storage: 200 GB on the free line. Boot ~50 GB, model cache on its own volume.

## Spend controls

`LYREN_ALLOW_PAID_PROVIDERS` defaults to `false`, and alias policies carry their own `allow_paid`
flag, so a fallback never crosses into a billing provider implicitly. Per-alias
`max_output_tokens` caps a client that asks for more.

`lyren_eval.budget.BudgetGuard` is the hard stop: a **call cap** that works without prices, and a
**money cap** that refuses the call when a model's price is unknown rather than assuming it is free.
An OCI budget only alerts and is not the control. → [ADR-0005](decisions/0005-spend-control-in-process.md)

**Unknown:** the per-token price of each model, and therefore whether the 2026-11-23 probe calls
billed — 24h later the cost report still showed zero. Until an invoice exists, every call is treated
as billable and bounded by call count rather than by money.

**$300 allowance, reported 2026-11-24.** No promotional credit appears in the API, so this is read as
pay-as-you-go headroom with no automatic stop. Spend it on bursty, high-value work — benchmarks and
evaluation runs — and keep the always-on components inside the Always Free envelope. A permanent
4 OCPU / 24 GB A1 instance would cost roughly $55/month at list price and consume the whole allowance
in about five months, for capacity the platform does not yet need.
