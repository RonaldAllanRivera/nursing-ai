"""What a model call costs, from its token counts. Exact decimals, never floats."""

from dataclasses import dataclass
from decimal import Decimal

_MILLION = Decimal(1_000_000)


@dataclass(frozen=True)
class _PerMillion:
    """Dollars per million tokens."""

    input: Decimal
    output: Decimal
    cache_write: Decimal
    cache_read: Decimal


_PRICES: dict[str, _PerMillion] = {
    "claude-opus-5-5": _PerMillion(
        input=Decimal("4.00"),
        output=Decimal("20.00"),
        cache_write=Decimal("5.00"),
        cache_read=Decimal("0.20"),
    ),
}


def _price_of(model: str) -> _PerMillion:
    try:
        return _PRICES[model]
    except KeyError:
        raise ValueError("no price is known for this model") from None


def cost_usd(
    model: str,
    input_tokens: int,
    output_tokens: int,
    cache_creation_tokens: int = 0,
    cache_read_tokens: int = 0,
) -> Decimal:
    """Raises ValueError for a model with no price, so a call is never silently free."""
    price = _price_of(model)
    return (
        price.input * input_tokens
        + price.output * output_tokens
        + price.cache_write * cache_creation_tokens
        + price.cache_read * cache_read_tokens
    ) / _MILLION
