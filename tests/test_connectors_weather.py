"""Tests for the weather connector (no live network calls)."""

import httpx
import pytest

from lydia.connectors.base import ConnectorError
from lydia.connectors.weather import get_weather


def _transport(handlers):
    def handle(request):
        for prefix, payload in handlers.items():
            if request.url.host.startswith(prefix):
                return httpx.Response(200, json=payload)
        return httpx.Response(404)
    return httpx.MockTransport(handle)


FORECAST = {
    "current": {"temperature_2m": 87.1, "apparent_temperature": 84.0,
                "precipitation": 0.0, "weather_code": 1, "wind_speed_10m": 7.0},
    "daily": {"time": ["2026-07-18", "2026-07-19"],
              "temperature_2m_max": [95.0, 97.2], "temperature_2m_min": [61.0, 63.5],
              "precipitation_probability_max": [5, 10]},
}


def test_named_location_geocodes_then_fetches():
    transport = _transport({
        "geocoding-api": {"results": [{"latitude": 43.1, "longitude": -115.7, "name": "Mountain Home"}]},
        "api.open-meteo": FORECAST,
    })
    out = get_weather("Mountain Home", transport=transport)
    assert "Mountain Home" in out and "87" in out and "Mostly clear" in out and "95" in out


def test_no_location_uses_ip_geolocation():
    transport = _transport({
        "ipapi": {"latitude": 43.1, "longitude": -115.7, "city": "Boise"},
        "api.open-meteo": FORECAST,
    })
    out = get_weather(transport=transport)
    assert "Boise" in out


def test_unknown_location_raises():
    transport = _transport({"geocoding-api": {"results": []}})
    with pytest.raises(ConnectorError):
        get_weather("Nowhereville", transport=transport)
