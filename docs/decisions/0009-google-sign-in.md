# ADR-0009 — Google sign-in exchanges an identity for a principal-bound token

**Date:** 2026-11-24 · **Status:** Accepted · **Extends** [ADR-0006](0006-principals-not-api-keys.md)

## Context
The web interface authenticates people with Google. The API authorises **principals** — identity
plus quota, model allow-list and enabled flag. Those are different things, and connecting them
badly loses everything ADR-0006 established.

## The alternative that was rejected
A Next.js server could hold one Lyren API key and proxy every user's requests. It is simpler, and it
would collapse every web user into a **single principal**. Per-person quotas would become a shared
pool, attribution would point at the proxy, and the audit trail would record one caller for
everybody. The reasons principals exist would survive in the code and disappear in practice.

## Decision
A token exchange. The browser sends a Google ID token to `POST /lyren/v1/auth/google`; the API
verifies it and returns a short-lived token **bound to one principal**, which the browser then uses
as an ordinary bearer credential.

**Verification is full, not partial.** RS256 signature against Google's JWKS, `iss` among Google's
two accepted issuers, `aud` equal to our client id, `exp`/`iat` with small leeway, and
`email_verified` required. `aud` is the check that matters most: without it, an ID token minted for
any other Google application would be accepted here.

**Optionally a Workspace domain.** `LYREN_GOOGLE_ALLOWED_DOMAINS` requires the `hd` claim to match.
When set, a personal Google account is refused even if its address is listed — the domain is a
second, independent gate.

**Signing in proves identity; it does not grant access.** A verified address is matched against
principals and refused when none claims it. Auto-provisioning on first sign-in would make a Google
account sufficient to use the deployment, which for a service built for a named group is a hole
rather than a convenience. An address claimed by two principals is a configuration error caught at
startup.

**Two credential types, one resolution path.** Session tokens carry a `lyst_` prefix, so a
malformed API key is never tried as a token or the reverse. Both resolve to the same `Principal`,
and every failure — unknown key, revoked key, expired token, disabled principal — is reported
identically. Quotas, allow-lists and metering are untouched: they already operate on principals, not
on credentials.

## Consequences
**The session TTL is the revocation window.** A signed token cannot be withdrawn before it expires,
so disabling a principal takes effect within one TTL rather than instantly. A short TTL (30 minutes
by default) is the mitigation; a revocation list needs shared state and arrives with the database in
Phase 5. Recorded here rather than left for someone to discover.

`GET /lyren/v1/me` returns the principal, its quota and today's usage, because a UI that cannot show
someone their own limit will have them discover it as an error instead.

`GET /lyren/v1/auth/config` serves the public client id, so the browser does not carry its own copy
to drift out of sync. A client id is not a secret.

These endpoints live under `/lyren/v1/`, not `/v1/`: they are not OpenAI endpoints and do not pretend
to be.

**This adds `pyjwt[crypto]`.** Hand-rolling RS256 verification is a well-known way to produce a
subtly broken verifier — skipping `aud`, accepting `alg: none`, mishandling key rotation. The
dependency is the conservative choice, not the convenient one.
