# Working on Lyren

Read this before changing anything. It is deliberately short; the permanent detail lives in `docs/`.

## Non-negotiables

1. **Never create a billing OCI resource, change the tenancy plan or enable a chargeable service
   without explicit authorisation.** On-demand Generative AI calls bill.
2. **Assume the Always Free envelope**: ~2 OCPU ARM / 12 GB RAM. The tenancy's service limits are
   higher, but a limit is a ceiling, not a free allowance.
3. **No fake features.** Anything unfinished stays disabled and returns an explicit error. Never let
   a route imply a capability that is not tested.
4. **Partial OpenAI compatibility is partial.** Do not rename something to suggest coverage that
   does not exist.
5. **Model availability is empirical.** The OCI catalog lists models that 404 on call. Only a probe
   decides; see `packages/inference/lyren_inference/registry.py`.
6. **Reuse before building.** Check `docs/OPEN_SOURCE_REUSE.md` first. Do not reimplement a
   maintained library, and do not add a dependency without recording why.
7. **No secrets in Git**, no secrets in logs. `lyren_core.logging.redact` covers the known shapes;
   extend it rather than bypassing it.
8. **Tests ship with the change.** Bug fixes start with a test that reproduces the bug.
9. **Nothing untrusted runs on the host.** Model-authored code needs real isolation; until that
   exists, autonomous execution stays off.

## Before you finish

```bash
./scripts/verify.sh
```

It runs what CI runs, in the same order, plus a secret audit over tracked files **and history** —
this repository is public, so a secret in a reverted commit is still published. Coverage floor is
80%.

**CI is not the gate right now.** This account's Actions minutes are exhausted, so pushes are
verified on the machine and pushed by hand. Do not report a change as verified on the strength of a
local run alone without saying so — and when minutes return, check the run instead of assuming it
matches. Six commits in this repository were pushed while CI was red and nobody looked; the cause
turned out to be the minute limit rather than the code, which is luck, not diligence.

Then update `docs/IMPLEMENTATION_STATUS.md` — it is the single place that says what is real.

## Token discipline

Do not re-run the OCI discovery; it is recorded in `docs/OCI_DISCOVERY.md`. Do not re-read whole
repositories to re-derive decisions already in `docs/decisions/`. Prefer small patches over
rewriting files.
