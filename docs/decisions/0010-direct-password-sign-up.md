# ADR-0010 — Direct password sign-up, restricted to declared addresses

**Date:** 2026-11-24 · **Status:** Accepted · **Complements** [ADR-0009](0009-google-sign-in.md)

## Context
Google sign-in is built but its OAuth client does not exist yet, so people need a way in now.
Password sign-up is that way, and Google will be added alongside it rather than replacing it.

The temptation is open self-registration. On a pay-as-you-go account with no automatic stop, serving
a named group, that means a stranger can create an account and spend the group's budget. So the same
rule as Google applies: **signing up proves you hold an address; it does not grant access.**

## Decisions

**Only a declared address can register.** The address must already appear under a principal's
`emails`. An address nobody declared is refused.

**Optionally a registration token.** Between an address being declared and the person signing up,
whoever registers first would take the account. A principal may carry
`registration_token_hash`, and when it does the token is required — an invite, handed over out of
band. Left unset, the declared address alone is enough and that race exists. The example config
uses a token and says why.

**Every refusal to register is worded identically.** An unclaimed address, an address that already
has a password, and a wrong token all answer `this address cannot be registered`. Otherwise the
endpoint would enumerate which addresses the deployment knows. A legitimate person who is unsure
simply tries signing in instead.

**A missing account and a wrong password cost the same.** The credential store hashes a dummy value
when there is no record, so response time does not distinguish the two, and both answer
`the address or password is wrong`.

**Argon2id at parameters the target can serve.** 64 MiB, two passes, no parallelism — about 120 ms
on a development x86 machine and more on two ARM OCPUs. The library defaults assume more CPU than
the target has. That is the intended order of magnitude: expensive for an attacker, tolerable for a
person signing in.

**Attempts are throttled per address.** Deliberately expensive hashing makes sign-in a
denial-of-service surface on a small CPU budget, so the throttle protects the passwords and the CPU
at once. It is keyed on the address, not the principal: keying on something only real accounts have
would leak which addresses exist.

**Length, not composition.** Twelve characters minimum, long passphrases welcome, and no rule about
digits or symbols — those push people towards `Password1!`. A password equal to the address itself is
refused.

## Consequences
Hashes live in a JSON file replaced atomically under an in-process lock, with mode `600`. A
registration flow needs durable mutable state and there is no database yet; this is correct for the
single-worker deployment that per-principal metering already requires, and it moves into the
database in Phase 5. The store's methods are the port.

**There is no password reset.** Resetting needs email delivery, which the deployment does not have.
Today an administrator clears the principal's record so the person can register again. A reset flow
arrives with outbound email, not before — and a reset endpoint that cannot actually send mail would
be a fake feature.

Both credential paths — password and Google — mint the same `lyst_` session token and resolve to the
same principal, so quotas, allow-lists, metering and attribution are untouched by which was used.
