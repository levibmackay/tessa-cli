"""Current weather + 2-day outlook via Open-Meteo.

Free, no API key. Location comes from an explicit name (geocoded), or, when
none is given, IP geolocation via ipapi.co — right wherever the laptop is.
ipapi.co over ip-api.com because its free tier supports HTTPS: this text ends
up in the model's prompt, so it must not be injectable by a hostile network.
"""

from __future__ import annotations

import httpx

from lydia.connectors.base import ConnectorError

GEOCODE_URL = "https://geocoding-api.open-meteo.com/v1/search"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
IP_LOCATE_URL = "https://ipapi.co/json/"

# WMO weather interpretation codes, abbreviated to what Open-Meteo emits.
_CODES = {
    0: "Clear", 1: "Mostly clear", 2: "Partly cloudy", 3: "Overcast",
    45: "Fog", 48: "Icy fog", 51: "Light drizzle", 53: "Drizzle",
    55: "Heavy drizzle", 61: "Light rain", 63: "Rain", 65: "Heavy rain",
    71: "Light snow", 73: "Snow", 75: "Heavy snow", 80: "Rain showers",
    81: "Rain showers", 82: "Violent rain showers", 95: "Thunderstorm",
    96: "Thunderstorm with hail", 99: "Thunderstorm with heavy hail",
}


def _locate(client: httpx.Client, location: str | None) -> tuple[float, float, str]:
    if location:
        resp = client.get(GEOCODE_URL, params={"name": location, "count": 1})
        resp.raise_for_status()
        results = resp.json().get("results") or []
        if not results:
            raise ConnectorError(f"Could not find a place called '{location}'.")
        hit = results[0]
        return hit["latitude"], hit["longitude"], hit.get("name", location)
    resp = client.get(IP_LOCATE_URL)
    resp.raise_for_status()
    data = resp.json()
    if data.get("error") or "latitude" not in data:
        raise ConnectorError("Could not determine your location from your IP.")
    return data["latitude"], data["longitude"], data.get("city", "your area")


def get_weather(location: str | None = None, transport=None) -> str:
    try:
        with httpx.Client(transport=transport, timeout=10.0) as client:
            lat, lon, name = _locate(client, location)
            resp = client.get(FORECAST_URL, params={
                "latitude": lat, "longitude": lon,
                "current": "temperature_2m,apparent_temperature,precipitation,weather_code,wind_speed_10m",
                "daily": "temperature_2m_max,temperature_2m_min,precipitation_probability_max",
                "timezone": "auto", "forecast_days": 2,
                "temperature_unit": "fahrenheit", "wind_speed_unit": "mph",
            })
            resp.raise_for_status()
            data = resp.json()
    except httpx.HTTPError as exc:
        raise ConnectorError(f"Weather lookup failed: {exc}") from exc

    cur, daily = data["current"], data["daily"]
    sky = _CODES.get(cur.get("weather_code"), "Unknown conditions")
    lines = [
        f"Weather in {name}: {sky}, {cur['temperature_2m']:.0f}F "
        f"(feels like {cur['apparent_temperature']:.0f}F), wind {cur['wind_speed_10m']:.0f} mph.",
    ]
    for i, day in enumerate(daily["time"]):
        label = "Today" if i == 0 else "Tomorrow"
        lines.append(
            f"{label}: high {daily['temperature_2m_max'][i]:.0f}F, "
            f"low {daily['temperature_2m_min'][i]:.0f}F, "
            f"{daily['precipitation_probability_max'][i]}% chance of precipitation."
        )
    return "\n".join(lines)
