"""Model list prices, used to turn token counts into money.

**These are published list prices transcribed by hand, not measured spend.** They are the basis of
the spend cap and of every cost figure this system reports, so:

* They are configuration, not a hidden constant, and the source and date are recorded below.
* `cost_usd` derived from them is labelled an *estimate* everywhere it surfaces.
* An unknown model raises rather than silently costing zero — a cost guard that reports $0.00 for
  an unrecognised model is worse than no cost guard, because it looks like it is working.

Cache multipliers: a cache write costs ~1.25x the input rate and a cache read ~0.1x. Verify both
the rates and the multipliers against the current pricing page before trusting a bill.

Source: Anthropic published pricing, transcribed 2026-09-18.
"""

from __future__ import annotations

from dataclasses import dataclass

CACHE_WRITE_MULTIPLIER = 1.25
CACHE_READ_MULTIPLIER = 0.1


@dataclass(frozen=True)
class ModelPrice:
    """Rates in US dollars per million tokens."""

    input_per_mtok: float
    output_per_mtok: float


PRICES: dict[str, ModelPrice] = {
    "claude-opus-5": ModelPrice(input_per_mtok=5.00, output_per_mtok=25.00),
    "claude-opus-4-8": ModelPrice(input_per_mtok=5.00, output_per_mtok=25.00),
    "claude-sonnet-5": ModelPrice(input_per_mtok=2.00, output_per_mtok=10.00),
    "claude-haiku-4-5": ModelPrice(input_per_mtok=1.00, output_per_mtok=5.00),
    # Test doubles cost nothing, which keeps the ledger exercised in CI without pretending a
    # fake provider has a price.
    "fake-llm-1": ModelPrice(input_per_mtok=0.0, output_per_mtok=0.0),
}


class UnknownModelPriceError(KeyError):
    def __init__(self, model: str) -> None:
        super().__init__(
            f"no list price recorded for model {model!r}; add it to app/core/pricing.py "
            "rather than letting its cost be counted as zero"
        )
        self.model = model


def estimate_cost_usd(
    model: str,
    *,
    input_tokens: int,
    output_tokens: int,
    cache_creation_input_tokens: int = 0,
    cache_read_input_tokens: int = 0,
) -> float:
    """Estimated cost of one request, from list prices.

    An estimate: it ignores taxes, negotiated rates, partner-platform pricing and any rate change
    since the transcription date above.
    """
    try:
        price = PRICES[model]
    except KeyError as exc:
        raise UnknownModelPriceError(model) from exc

    per_token_in = price.input_per_mtok / 1_000_000
    per_token_out = price.output_per_mtok / 1_000_000
    return (
        input_tokens * per_token_in
        + cache_creation_input_tokens * per_token_in * CACHE_WRITE_MULTIPLIER
        + cache_read_input_tokens * per_token_in * CACHE_READ_MULTIPLIER
        + output_tokens * per_token_out
    )
