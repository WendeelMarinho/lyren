# ADR-0003 — Model availability is empirical, never read from the catalog

**Date:** 2026-11-23 · **Status:** Accepted

## Context
On 2026-11-23 the OCI Generative AI catalog in `sa-saopaulo-1` returned 41 models. Eight chat entries
appeared live by their metadata. **Three answered a real request.** Two failure patterns explain the
gap: display-names are duplicated, and the entry whose `time-on-demand-retired` is null is the
dedicated-cluster variant rather than an on-demand offer; and `time-on-demand-retired` set to epoch
zero (`1970-01-01`) means not served on demand while reading like "never retired".

Separately, `google.gemini-2.5-flash` exists and is `ACTIVE` but returns 429 because
`gemini-2-5-flash-requests-per-minute-count` is 0 in this tenancy — a different failure from absence,
requiring a different response.

## Decision
Every model in the registry carries an `Availability` verdict (`verified`, `unverified`,
`not_found`, `quota_zero`) with a probe date, and a pinned version. The catalog is a hint. The chat
route records a verdict when a candidate fails, so drift is observed rather than assumed. Model lists
are never hardcoded from catalog output.

## Consequences
`GET /v1/models` shows only callable models; `GET /lyren/v1/models` shows everything with the reason.
A quota-zero model raises `ModelDisabledByQuotaError` (actionable: request a limit increase) while a
missing one raises `ModelNotAvailableError` (actionable: stop asking). Known-dead models stay in the
registry as negative knowledge so we do not rediscover them.

The cost: the seeded verdicts are a point-in-time snapshot and will go stale. Mitigated by probes at
runtime and by treating this as expected drift rather than an error.
