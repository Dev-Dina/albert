"""Model price book for per-tenant cost attribution.

Single source of truth for converting token usage into a USD cost. Used by
``app.cost.record_cost_event`` so every recorded ``cost_events`` row carries a
real dollar amount instead of 0.

Prices are **public list prices** (USD per 1,000,000 tokens) for the default
Gemini models configured in ``app.core.config`` (``gemini_model`` /
``gemini_embedding_model``). Update this table when provider pricing changes.
An unknown model is recorded at cost 0 (and logged) rather than crashing the
serving path.
"""

from __future__ import annotations

import logging
from decimal import ROUND_HALF_UP, Decimal

logger = logging.getLogger(__name__)

_PER_MILLION = Decimal("1000000")

# 6 decimal places — matches CostEvent.cost_usd Numeric(precision=10, scale=6).
_QUANTUM = Decimal("0.000001")

# model -> (input_usd_per_million_tokens, output_usd_per_million_tokens).
# Embedding models bill input only (output rate 0).
_MODEL_PRICING_PER_MILLION: dict[str, tuple[Decimal, Decimal]] = {
    "gemini-2.5-flash-lite": (Decimal("0.10"), Decimal("0.40")),
    "gemini-2.5-flash": (Decimal("0.30"), Decimal("2.50")),
    "gemini-2.5-pro": (Decimal("1.25"), Decimal("10.00")),
    "gemini-embedding-001": (Decimal("0.15"), Decimal("0")),
}


def _rates_for(model: str) -> tuple[Decimal, Decimal] | None:
    """Resolve (input, output) per-million rates for ``model``.

    Exact match first; then a prefix match so versioned ids like
    ``gemini-2.5-flash-lite-preview-09`` still price correctly.
    """
    if model in _MODEL_PRICING_PER_MILLION:
        return _MODEL_PRICING_PER_MILLION[model]
    for key, rates in _MODEL_PRICING_PER_MILLION.items():
        if model.startswith(key):
            return rates
    return None


def compute_cost_usd(model: str, input_tokens: int, output_tokens: int) -> Decimal:
    """USD cost for a single call, quantized to 6 decimal places.

    Unknown model → ``Decimal("0")`` with a warning (never raises — cost
    attribution must not break the serving path).
    """
    rates = _rates_for(model)
    if rates is None:
        logger.warning("pricing.unknown_model model=%s — recording cost 0", model)
        return Decimal("0")
    input_rate, output_rate = rates
    cost = (
        Decimal(int(input_tokens)) * input_rate
        + Decimal(int(output_tokens)) * output_rate
    ) / _PER_MILLION
    return cost.quantize(_QUANTUM, rounding=ROUND_HALF_UP)
