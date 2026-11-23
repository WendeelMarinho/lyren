from decimal import Decimal

import pytest

from lyren_core.errors import BudgetExceededError, BudgetUnenforceableError
from lyren_eval.budget import BudgetGuard, SpendLedger
from lyren_eval.pricing import ModelPrice, PriceBook
from lyren_inference.ports import (
    ApiFormat,
    Availability,
    Capability,
    ChatRequest,
    ChatResponse,
    Message,
    ModelSpec,
    Role,
    Usage,
)

SPEC = ModelSpec(
    id="meta.llama-3.3-70b-instruct",
    vendor="meta",
    provider="oci_generative_ai",
    api_format=ApiFormat.GENERIC,
    pinned_version="1.0.0",
    capabilities=frozenset({Capability.CHAT}),
    availability=Availability.VERIFIED,
)
REQUEST = ChatRequest(messages=(Message(role=Role.USER, content="ping"),))
PRICED = PriceBook(
    prices={SPEC.id: ModelPrice(input_per_mtok=Decimal(1), output_per_mtok=Decimal(2))}
)


class Stub:
    name = "stub"

    def __init__(self, cached=False):
        self.calls = 0
        self.cached = cached

    def chat(self, spec, request):
        self.calls += 1
        return ChatResponse(
            model_id=spec.id,
            text="pong",
            finish_reason="stop",
            usage=Usage(prompt_tokens=1_000_000, completion_tokens=1_000_000),
            from_cache=self.cached,
        )


def test_call_cap_is_enforceable_without_any_price_information():
    guard = BudgetGuard(Stub(), PriceBook.empty(), hard_cap=None, max_calls=2)

    guard.chat(SPEC, REQUEST)
    guard.chat(SPEC, REQUEST)

    with pytest.raises(BudgetExceededError):
        guard.chat(SPEC, REQUEST)


def test_money_cap_without_a_price_fails_closed():
    guard = BudgetGuard(Stub(), PriceBook.empty(), hard_cap=Decimal(10))

    with pytest.raises(BudgetUnenforceableError):
        guard.chat(SPEC, REQUEST)


def test_money_cap_stops_once_the_recorded_spend_reaches_it():
    stub = Stub()
    guard = BudgetGuard(stub, PRICED, hard_cap=Decimal(4))

    guard.chat(SPEC, REQUEST)

    assert guard.ledger.cost == Decimal(3)
    assert guard.remaining == Decimal(1)
    guard.chat(SPEC, REQUEST)
    with pytest.raises(BudgetExceededError):
        guard.chat(SPEC, REQUEST)
    assert stub.calls == 2


def test_cache_hits_are_counted_but_never_charged():
    guard = BudgetGuard(Stub(cached=True), PRICED, hard_cap=Decimal(10))

    guard.chat(SPEC, REQUEST)

    assert guard.ledger.cached_calls == 1
    assert guard.ledger.cost == Decimal(0)


def test_an_unpriced_call_marks_the_total_incomplete():
    ledger = SpendLedger()
    ledger.record(SPEC.id, Usage(prompt_tokens=10, completion_tokens=5), None, cached=False)

    assert ledger.cost_is_complete is False
    assert ledger.prompt_tokens == 10


def test_price_is_none_when_token_counts_are_missing():
    assert PRICED.cost_of(SPEC.id, Usage()) is None
