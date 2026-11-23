"""Token prices.

Oracle's per-token prices for on-demand Generative AI are not exposed by the API and were not
measured, so this module never guesses one. An unpriced model yields `None`, and callers decide what
that means — the budget guard treats it as unenforceable rather than as free.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

from lyren_inference.ports import Usage

_PER_MILLION = Decimal(1_000_000)


@dataclass(frozen=True, slots=True)
class ModelPrice:
    input_per_mtok: Decimal
    output_per_mtok: Decimal
    currency: str = "USD"


@dataclass(frozen=True, slots=True)
class PriceBook:
    prices: dict[str, ModelPrice]
    currency: str = "USD"

    @classmethod
    def empty(cls) -> PriceBook:
        return cls(prices={})

    @classmethod
    def from_file(cls, path: Path) -> PriceBook:
        raw = json.loads(path.read_text(encoding="utf-8"))
        currency = str(raw.get("currency", "USD"))
        prices = {
            model_id: ModelPrice(
                input_per_mtok=Decimal(str(entry["input_per_mtok"])),
                output_per_mtok=Decimal(str(entry["output_per_mtok"])),
                currency=currency,
            )
            for model_id, entry in raw.get("models", {}).items()
        }
        return cls(prices=prices, currency=currency)

    def has_price(self, model_id: str) -> bool:
        return model_id in self.prices

    def cost_of(self, model_id: str, usage: Usage) -> Decimal | None:
        """Cost of one call, or None when the price or the token counts are unknown."""
        price = self.prices.get(model_id)
        if price is None:
            return None
        if usage.prompt_tokens is None or usage.completion_tokens is None:
            return None
        return (
            price.input_per_mtok * Decimal(usage.prompt_tokens)
            + price.output_per_mtok * Decimal(usage.completion_tokens)
        ) / _PER_MILLION
