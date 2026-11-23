# ADR-0006 — An API key identifies a person, not merely access

**Date:** 2026-11-23 · **Status:** Accepted · **Supersedes the auth model of** [ADR-0001](0001-modular-monolith.md)

## Context
Lyren was scoped as a personal platform and authenticated with a flat list of API key hashes in
configuration. It is now a shared service for a small group of named people.

A flat hash list cannot express any of what that requires. It has no identity, so usage cannot be
attributed; no per-person limits, so one person can spend the shared budget; no individual
revocation, so removing one person's access means rotating everyone's key; and no owner, so memory
and conversation history have nothing to belong to.

The budget makes this acute rather than theoretical. The account is pay-as-you-go with no automatic
stop, and several people now share it.

## Decision
A key resolves to a **`Principal`** — id, display name, `Quota`, an optional allow-list of models,
and an enabled flag. Keys are separate `ApiKeyRecord`s so a principal can hold several and lose one.

- **Resolution fails identically** for an unknown key, a revoked key and a disabled principal. The
  caller learns the key does not work, never which of the three it was.
- **Revocation sets `revoked_at`; the record is kept.** Deleting it would erase the audit trail of
  who held access.
- **Two independent caps.** Per-principal `requests_per_minute` and `calls_per_day` stop one person
  starving another. A **deployment-wide** `calls_per_day` stops the group from exhausting the budget
  — five people at 500 calls a day is 2500 calls a day, so per-principal limits alone bound nothing
  that matters financially. Whichever binds first applies, and both are checked *before* any
  provider call, so a refused request costs nothing.
- **Output tokens are capped by the stricter of** the alias budget and the principal's quota, so a
  client asking for more cannot widen its own allowance.
- **`/v1/models` is narrowed per principal**, so a person is not shown models they would be refused.
- **The single-principal shortcut remains for local development only.** With
  `LYREN_API_KEY_HASHES` and no principals file, the API refuses to start outside
  `LYREN_ENVIRONMENT=local`, naming the reason. A shared deployment without attribution is a
  configuration error, not a convenience.

The store is a JSON file for now. It moves into the database in Phase 5; the port is what matters.

## Consequences
Metering is **in-process and therefore per-worker**: two API workers each allow the full rate. This
is recorded rather than hidden. The per-minute rate is the loose one under that constraint; the daily
caps, which are what bound spend, are the conservative ones. A shared counter arrives with the
database.

Managing a JSON file by hand is operational friction and will not scale past a handful of people.
That is the right trade while the group is small and there is no database; an admin endpoint would be
a surface to secure before there is anything to secure it with.

## Found while building this
`LYREN_API_KEY_HASHES` had **never worked as an environment variable**. pydantic-settings
JSON-decodes a complex field from the environment before any validator runs, so a comma-separated
value failed to parse. Earlier tests passed the tuple directly to `Settings(...)` and never
exercised the environment path. Fixed with `NoDecode`, and the test that found it now covers it.
