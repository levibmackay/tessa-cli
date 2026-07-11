"""General stock market snapshot — major US indices, not a personal portfolio.

Uses yfinance, which needs no API key. `ticker_factory` is injectable so
tests can supply a fake instead of hitting the network.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

import yfinance as yf

from lydia.connectors import ConnectorError

# (Yahoo Finance symbol, display name)
INDEXES: tuple[tuple[str, str], ...] = (
    ("^GSPC", "S&P 500"),
    ("^IXIC", "Nasdaq"),
    ("^DJI", "Dow Jones"),
)


class _Quotable(Protocol):
    @property
    def fast_info(self) -> dict: ...


@dataclass
class IndexSnapshot:
    symbol: str
    name: str
    price: float
    change_pct: float


def get_market_summary(
    ticker_factory: Callable[[str], _Quotable] = yf.Ticker,
) -> list[IndexSnapshot]:
    """Last price and % change from previous close for each tracked index.

    A single index failing to fetch doesn't block the others — Yahoo's
    unofficial endpoint occasionally rate-limits or drops one symbol.
    """
    snapshots: list[IndexSnapshot] = []
    errors: list[str] = []
    for symbol, name in INDEXES:
        try:
            info = ticker_factory(symbol).fast_info
            price = float(info["last_price"])
            previous_close = float(info["previous_close"])
        except Exception as exc:  # yfinance raises a mix of its own + requests errors
            errors.append(f"{name} ({symbol}): {exc}")
            continue
        change_pct = ((price - previous_close) / previous_close * 100) if previous_close else 0.0
        snapshots.append(IndexSnapshot(symbol=symbol, name=name, price=price, change_pct=change_pct))
    if not snapshots:
        raise ConnectorError("Could not fetch any market data: " + "; ".join(errors))
    return snapshots


def format_market_summary(snapshots: list[IndexSnapshot]) -> str:
    lines = []
    for s in snapshots:
        sign = "+" if s.change_pct >= 0 else ""
        lines.append(f"{s.name} ({s.symbol}): {s.price:,.2f} ({sign}{s.change_pct:.2f}%)")
    return "\n".join(lines)
