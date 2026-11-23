"""In-process hard spend cap.

An OCI budget only alerts; it does not stop spending. On a pay-as-you-go account the only thing that
actually refuses the next call is code, so the cap lives here and the guard wraps every provider.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from lyren_core.errors import BudgetExceededError, BudgetUnenforceableError
from lyren_eval.pricing import PriceBook
from lyren_inference.ports import ChatProvider, ChatRequest, ChatResponse, ModelSpec, Usage


@dataclass(slots=True)
class SpendLedger:
    """Running totals for a run. Token counts are always recorded; cost only when priced."""

    calls: int = 0
    cached_calls: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost: Decimal = Decimal(0)
    unpriced_calls: int = 0
    per_model: dict[str, int] = field(default_factory=dict)

    def record(self, model_id: str, usage: Usage, cost: Decimal | None, *, cached: bool) -> None:
        self.calls += 1
        self.per_model[model_id] = self.per_model.get(model_id, 0) + 1
        if cached:
            self.cached_calls += 1
        self.prompt_tokens += usage.prompt_tokens or 0
        self.completion_tokens += usage.completion_tokens or 0
        if cost is None:
            self.unpriced_calls += 1
        else:
            self.cost += cost

    @property
    def cost_is_complete(self) -> bool:
        """False when any billed call could not be priced, so the total understates reality."""
        return self.unpriced_calls == 0


class BudgetGuard:
    """Refuses a call once a cap is reached.

    Two independent caps, because they need different knowledge. `max_calls` is enforceable with no
    price information at all, which makes it the usable guard before an invoice exists.
    `hard_cap` is a money cap and needs a price; with a price missing the guard fails closed
    rather than allowing an uncapped spend on a pay-as-you-go account. Both None means
    observation only.
    """

    def __init__(
        self,
        inner: ChatProvider,
        price_book: PriceBook,
        *,
        hard_cap: Decimal | None,
        max_calls: int | None = None,
        ledger: SpendLedger | None = None,
    ) -> None:
        self._inner = inner
        self._prices = price_book
        self._hard_cap = hard_cap
        self._max_calls = max_calls
        self.ledger = ledger if ledger is not None else SpendLedger()
        self.name = f"budgeted:{inner.name}"

    @property
    def remaining(self) -> Decimal | None:
        if self._hard_cap is None:
            return None
        return self._hard_cap - self.ledger.cost

    def chat(self, spec: ModelSpec, request: ChatRequest) -> ChatResponse:
        if self._max_calls is not None and self.ledger.calls >= self._max_calls:
            raise BudgetExceededError(f"call cap of {self._max_calls} reached")

        cap = self._hard_cap
        if cap is not None and spec.bills:
            if self.ledger.cost >= cap:
                raise BudgetExceededError(
                    f"spend cap of {cap} reached; {self.ledger.calls} calls recorded"
                )
            if not self._prices.has_price(spec.id):
                raise BudgetUnenforceableError(
                    f"no price configured for {spec.id}; the spend cap cannot be honoured",
                    detail="add the model to the price book or clear the hard cap deliberately",
                )

        response = self._inner.chat(spec, request)
        cost = None if response.from_cache else self._prices.cost_of(spec.id, response.usage)
        self.ledger.record(spec.id, response.usage, cost, cached=response.from_cache)
        return response
