"""Deterministic graders only.

A model judging a model is weak evidence, so the baseline grades against machine-checkable answers.
An LLM judge may be added later as a separate, clearly labelled grader — never as the default.
"""

from __future__ import annotations

import json
import re
import unicodedata
from collections.abc import Callable
from decimal import Decimal, InvalidOperation

Grader = Callable[[str, object], bool]


def normalize(text: str, *, fold_accents: bool = True) -> str:
    out = text.strip().lower()
    out = re.sub(r"[\s]+", " ", out)
    out = out.strip(" .!?,;:\"'`*")
    if fold_accents:
        decomposed = unicodedata.normalize("NFD", out)
        out = "".join(ch for ch in decomposed if unicodedata.category(ch) != "Mn")
    return out


def grade_exact(answer: str, expected: object) -> bool:
    return normalize(answer) == normalize(str(expected))


def grade_exact_cased(answer: str, expected: object) -> bool:
    return answer.strip() == str(expected).strip()


def grade_contains_all(answer: str, expected: object) -> bool:
    needles = expected if isinstance(expected, list) else [expected]
    haystack = normalize(answer)
    return all(normalize(str(needle)) in haystack for needle in needles)


def grade_not_contains(answer: str, expected: object) -> bool:
    """Passes when none of the forbidden strings appears. Graded on a non-empty answer only."""
    needles = expected if isinstance(expected, list) else [expected]
    haystack = normalize(answer)
    if not haystack:
        return False
    return not any(normalize(str(needle)) in haystack for needle in needles)


def grade_regex(answer: str, expected: object) -> bool:
    return re.search(str(expected), answer.strip(), re.IGNORECASE | re.MULTILINE) is not None


def grade_numeric(answer: str, expected: object) -> bool:
    """Accepts the first number in the answer, tolerating thousands separators and pt-BR commas."""
    target = _as_decimal(str(expected))
    if target is None:
        return False
    found = re.search(r"-?\d[\d.,]*", answer)
    if not found:
        return False
    value = _as_decimal(found.group(0))
    if value is None:
        return False
    return abs(value - target) <= Decimal("0.001")


def grade_json_keys(answer: str, expected: object) -> bool:
    """Passes when the answer parses as a JSON object carrying exactly the expected keys."""
    block = re.search(r"\{.*\}", answer, re.DOTALL)
    if not block:
        return False
    try:
        parsed = json.loads(block.group(0))
    except json.JSONDecodeError:
        return False
    if not isinstance(parsed, dict):
        return False
    wanted = {str(k) for k in (expected if isinstance(expected, list) else [expected])}
    return set(parsed.keys()) == wanted


def _as_decimal(raw: str) -> Decimal | None:
    """Parse a number without guessing.

    A single separator is read as the decimal separator, so "2.500" is 2.5 and not 2500. Accepting
    both readings would let "3.91" pass as 391, and a benchmark that inflates its own score is worse
    than one that demands an unformatted answer.
    """
    cleaned = raw.strip()
    has_dot, has_comma = "." in cleaned, "," in cleaned

    if has_dot and has_comma:
        if cleaned.rfind(".") > cleaned.rfind(","):
            cleaned = cleaned.replace(",", "")
        else:
            cleaned = cleaned.replace(".", "").replace(",", ".")
    elif cleaned.count(".") > 1:
        cleaned = cleaned.replace(".", "")
    elif cleaned.count(",") > 1:
        cleaned = cleaned.replace(",", "")
    elif has_comma:
        cleaned = cleaned.replace(",", ".")

    try:
        return Decimal(cleaned)
    except InvalidOperation:
        return None


GRADERS: dict[str, Grader] = {
    "exact": grade_exact,
    "exact_cased": grade_exact_cased,
    "contains_all": grade_contains_all,
    "not_contains": grade_not_contains,
    "regex": grade_regex,
    "numeric": grade_numeric,
    "json_keys": grade_json_keys,
}
