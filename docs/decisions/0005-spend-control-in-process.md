# ADR-0005 — The hard spend cap lives in Lyren, not in an OCI budget

**Date:** 2026-11-23 · **Status:** Accepted

## Context
A spend allowance was made available for OCI. Checked on 2026-11-23, the tenancy reports **zero
promotional credit** (`CREDIT`, `ALLCREDIT` and `EXPIREDCREDIT` all empty), zero recorded cost and
**no configured budget**, so the allowance is a payment-method-backed one rather than an Oracle
credit grant.

That distinction matters: promotional credit stops when it runs out. A pay-as-you-go account does
not stop at any figure — it keeps billing. And an **OCI budget only alerts; it does not block
spending.**

Oracle's per-token prices for on-demand Generative AI are also not exposed by the API and have not
been measured, so the system cannot convert tokens to money yet.

## Decision
Two independent caps in `lyren_eval.budget.BudgetGuard`, wrapping every provider:

1. **`max_calls`** — a call-count cap, enforceable with no price information at all. This is the
   usable guard today.
2. **`hard_cap`** — a money cap. When a money cap is set and the model has no configured price, the
   guard raises `BudgetUnenforceableError` and **refuses the call**.

An OCI budget with alert rules is still worth creating, as a second line of defence and because it
sees spend the application cannot (compute, storage). It is not the control.

## Consequences
Failing closed on an unpriced model is the deliberate choice. The alternative — treating an unknown
price as zero — is exactly how an uncapped bill happens on a pay-as-you-go account.

The first benchmark run therefore uses `--max-calls` with no money cap: cost is bounded by call count
and per-task output budget rather than by price. The invoice from that run is what populates the
price book, after which the money cap becomes enforceable.

Cache hits are counted but never charged, so replaying a task set is free and visibly so.

The `SpendLedger` records token counts always and reports `cost_is_complete = False` when any billed
call could not be priced: an understated total is not presented as a total.
