"""What a call costs: exact decimals, and no silent zero for a model without a price."""

from decimal import Decimal

import pytest
from nursing_core.providers.pricing import cost_usd


def test_cost_for_opus_5_5() -> None:
    assert cost_usd("claude-opus-5-5", 1_000_000, 0) == Decimal("4.00")
    assert cost_usd("claude-opus-5-5", 0, 1_000_000) == Decimal("20.00")
    assert cost_usd("claude-opus-5-5", 0, 0, cache_creation_tokens=1_000_000) == Decimal("5.00")
    assert cost_usd("claude-opus-5-5", 0, 0, cache_read_tokens=1_000_000) == Decimal("0.20")
    # 1,200 input + 800 output + 1,000 cache write + 5,000 cache read
    assert cost_usd("claude-opus-5-5", 1200, 800, 1000, 5000) == Decimal("0.0268")


def test_unknown_model_has_no_price() -> None:
    with pytest.raises(ValueError, match="no price"):
        cost_usd("claude-made-up", 1, 1)
