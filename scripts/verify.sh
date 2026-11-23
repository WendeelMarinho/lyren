#!/usr/bin/env bash
# The gate before every push.
#
# GitHub Actions minutes are exhausted on this account, so CI is not the gate right now — this
# script is. It runs exactly what .github/workflows/ci.yml runs, in the same order, so a green run
# here means a green run there once minutes return.
set -euo pipefail

cd "$(dirname "$0")/.."
VENV="${VENV:-.venv}"

echo "── ruff ────────────────────────────────────────────"
"$VENV/bin/ruff" check .
"$VENV/bin/ruff" format --check .

echo "── mypy (strict) ───────────────────────────────────"
"$VENV/bin/mypy" packages apps

echo "── pytest (coverage floor 80%) ─────────────────────"
"$VENV/bin/pytest" --cov-fail-under=80

echo "── secret audit ────────────────────────────────────"
# Tracked files only, and the history too: this repository is public, so a secret in a reverted
# commit is still published.
# The argon2 pattern deliberately requires the full hash shape. Matching the bare "$argon2"
# prefix flagged a test that asserts it, which is the kind of false positive that gets a check
# switched off rather than fixed.
PATTERN='ocid1\.[a-z]+\.oc1\.\.[a-z0-9]{10}|BEGIN (RSA |EC )?PRIVATE KEY|\$argon2[a-z]+\$v=[0-9]+\$m=|gho_[A-Za-z0-9]{20}'
if git grep -nIE "$PATTERN" -- . | grep -v '\.md:'; then
  echo "FAIL: a secret-shaped string is tracked"
  exit 1
fi
if git log --all -p --no-color | grep -qIE "$PATTERN"; then
  echo "FAIL: a secret-shaped string appears in history"
  exit 1
fi
echo "clean"

echo
echo "All gates passed."
