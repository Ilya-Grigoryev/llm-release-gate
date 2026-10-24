"""List prices: a YAML table `model: [input, output]` or `[input, output, cached input]` in USD per 1M tokens,
matched by model name prefix.

An agent resends the whole dialog on every call, and the provider bills the repeated prefix as cached input at a
fraction of the input price (gpt-5.4-mini: 90 % less). Without a cached price, cached tokens cost the full input price.
"""

from pathlib import Path

import yaml

Prices = dict[str, tuple[float, ...]]


def load_prices(path: Path) -> Prices:
    """Model name prefix -> USD per 1M input, output and, if given, cached input tokens."""
    raw = yaml.safe_load(Path(path).read_text())
    ok = isinstance(raw, dict) and all(
        isinstance(k, str)
        and isinstance(v, list)
        and len(v) in (2, 3)
        and all(type(x) in (int, float) and x >= 0 for x in v)
        for k, v in raw.items()
    )
    if not ok:
        raise ValueError(
            f"{path}: expected `model: [input, output]` or `[input, output, cached input]`"
            " in USD per 1M tokens"
        )
    return {k: tuple(float(x) for x in v) for k, v in raw.items()}


def usd(
    model: str | None,
    tokens_in: int | None,
    tokens_out: int | None,
    prices: Prices,
    tokens_cached: int | None = 0,
) -> float | None:
    """USD for one call at list price; None if the model has no price. The longest matching prefix wins.

    `tokens_cached` is the part of `tokens_in` billed as cached input.
    """
    model = str(model or "")
    key = max((k for k in prices if model.startswith(k)), key=len, default=None)
    if key is None:
        return None
    p_in, p_out, *rest = prices[key]
    p_cached = rest[0] if rest else p_in
    tokens_in = tokens_in or 0
    cached = min(tokens_cached or 0, tokens_in)
    return (
        (tokens_in - cached) * p_in + cached * p_cached + (tokens_out or 0) * p_out
    ) / 1e6
