"""Cost arithmetic. These are list-price estimates, and the tests say so."""

import pytest

from app.core.pricing import (
    CACHE_READ_MULTIPLIER,
    CACHE_WRITE_MULTIPLIER,
    PRICES,
    UnknownModelPriceError,
    estimate_cost_usd,
)


def test_plain_input_and_output_cost() -> None:
    # 1M input + 1M output on claude-opus-5 at $5 / $25 per MTok.
    cost = estimate_cost_usd("claude-opus-5", input_tokens=1_000_000, output_tokens=1_000_000)
    assert cost == pytest.approx(30.0)


def test_a_realistic_turn_costs_cents_not_dollars() -> None:
    """Sanity check on the order of magnitude, which is what the spend cap depends on."""
    cost = estimate_cost_usd("claude-opus-5", input_tokens=3_000, output_tokens=150)
    assert 0.01 < cost < 0.03


def test_cache_reads_are_much_cheaper_than_fresh_input() -> None:
    fresh = estimate_cost_usd("claude-opus-5", input_tokens=100_000, output_tokens=0)
    cached = estimate_cost_usd(
        "claude-opus-5", input_tokens=0, output_tokens=0, cache_read_input_tokens=100_000
    )
    assert cached == pytest.approx(fresh * CACHE_READ_MULTIPLIER)
    assert cached < fresh / 5


def test_cache_writes_cost_more_than_fresh_input() -> None:
    """Caching is not free on the first turn — worth remembering before caching tiny prefixes."""
    fresh = estimate_cost_usd("claude-opus-5", input_tokens=100_000, output_tokens=0)
    written = estimate_cost_usd(
        "claude-opus-5", input_tokens=0, output_tokens=0, cache_creation_input_tokens=100_000
    )
    assert written == pytest.approx(fresh * CACHE_WRITE_MULTIPLIER)
    assert written > fresh


def test_unknown_model_raises_rather_than_costing_nothing() -> None:
    """A cost guard that silently reports $0.00 looks like it is working and is not."""
    with pytest.raises(UnknownModelPriceError, match="no list price recorded"):
        estimate_cost_usd("some-model-we-have-not-priced", input_tokens=1000, output_tokens=100)


def test_the_test_double_is_priced_at_zero() -> None:
    assert estimate_cost_usd("fake-llm-1", input_tokens=10_000, output_tokens=10_000) == 0.0


def test_cheaper_tiers_are_actually_cheaper() -> None:
    """Guards a transcription slip that would misrank models in a cost comparison."""
    opus = PRICES["claude-opus-5"]
    sonnet = PRICES["claude-sonnet-5"]
    haiku = PRICES["claude-haiku-4-5"]
    assert opus.input_per_mtok > sonnet.input_per_mtok > haiku.input_per_mtok
    assert opus.output_per_mtok > sonnet.output_per_mtok > haiku.output_per_mtok


def test_output_is_dearer_than_input_for_every_priced_model() -> None:
    for model, price in PRICES.items():
        if price.input_per_mtok == 0:
            continue
        assert price.output_per_mtok > price.input_per_mtok, model
