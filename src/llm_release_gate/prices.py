"""List prices: a YAML table `model: [input, output]` in USD per 1M tokens, matched by model name prefix."""

from pathlib import Path

import yaml

Prices = dict[str, tuple[float, float]]


def load_prices(path: Path) -> Prices:
    """Model name prefix -> USD per 1M input tokens and per 1M output tokens."""
    raw = yaml.safe_load(Path(path).read_text())
    ok = isinstance(raw, dict) and all(
        isinstance(k, str)
        and isinstance(v, list)
        and len(v) == 2
        and all(type(x) in (int, float) and x >= 0 for x in v)
        for k, v in raw.items()
    )
    if not ok:
        raise ValueError(
            f"{path}: expected `model: [input, output]` in USD per 1M tokens"
        )
    return {k: (float(v[0]), float(v[1])) for k, v in raw.items()}


def usd(
    model: str | None, tokens_in: int, tokens_out: int, prices: Prices
) -> float | None:
    """USD for one call at list price; None if the model has no price. The longest matching prefix wins."""
    model = str(model or "")
    key = max((k for k in prices if model.startswith(k)), key=len, default=None)
    if key is None:
        return None
    p_in, p_out = prices[key]
    return ((tokens_in or 0) * p_in + (tokens_out or 0) * p_out) / 1e6
