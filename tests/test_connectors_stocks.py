"""Tests for the stock market snapshot connector (no live network calls)."""

import pytest

from lydia.connectors import ConnectorError
from lydia.connectors.stocks import format_market_summary, get_market_summary


class _FakeTicker:
    def __init__(self, last_price: float, previous_close: float) -> None:
        self._info = {"last_price": last_price, "previous_close": previous_close}

    @property
    def fast_info(self) -> dict:
        return self._info


class _BrokenTicker:
    @property
    def fast_info(self) -> dict:
        raise RuntimeError("rate limited")


def test_get_market_summary_computes_change_pct() -> None:
    factory = {
        "^GSPC": _FakeTicker(110.0, 100.0),
        "^IXIC": _FakeTicker(90.0, 100.0),
        "^DJI": _FakeTicker(100.0, 100.0),
    }
    snapshots = get_market_summary(ticker_factory=lambda symbol: factory[symbol])
    by_symbol = {s.symbol: s for s in snapshots}
    assert by_symbol["^GSPC"].change_pct == pytest.approx(10.0)
    assert by_symbol["^IXIC"].change_pct == pytest.approx(-10.0)
    assert by_symbol["^DJI"].change_pct == pytest.approx(0.0)


def test_one_index_failing_does_not_block_the_others() -> None:
    factory = {
        "^GSPC": _FakeTicker(110.0, 100.0),
        "^IXIC": _BrokenTicker(),
        "^DJI": _FakeTicker(100.0, 100.0),
    }
    snapshots = get_market_summary(ticker_factory=lambda symbol: factory[symbol])
    assert {s.symbol for s in snapshots} == {"^GSPC", "^DJI"}


def test_all_indexes_failing_raises_connector_error() -> None:
    with pytest.raises(ConnectorError):
        get_market_summary(ticker_factory=lambda symbol: _BrokenTicker())


def test_format_market_summary() -> None:
    factory = {"^GSPC": _FakeTicker(110.0, 100.0)}
    snapshots = get_market_summary(ticker_factory=lambda symbol: factory[symbol])
    text = format_market_summary(snapshots)
    assert "S&P 500" in text
    assert "+10.00%" in text
