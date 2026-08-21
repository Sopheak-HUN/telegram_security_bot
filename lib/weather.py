"""Current-weather lookups for the "@bot weather" mention feature.

Telegram never reveals a user's position on its own, so the bot remembers the
last location each user shared (the 📎 attach → Location message) in Redis and
answers weather requests from that.

Providers, in order:

- Google Weather API (weather.googleapis.com) when GOOGLE_WEATHER_API_KEY is
  set — enable "Weather API" in a Google Maps Platform project.
- Open-Meteo (open-meteo.com) otherwise — keyless, so the feature works out of
  the box.

Apple WeatherKit is intentionally not wired in: it requires an Apple Developer
membership plus ES256-signed JWTs, which is heavy for a serverless webhook.
"""

import json
import os
import time

import httpx  # bundled with python-telegram-bot

from .whitelist import _get_redis

LOCATION_KEY = "weather:loc:{user_id}"

# WMO interpretation codes used by Open-Meteo.
_WMO_CODES = {
    0: "Clear sky",
    1: "Mainly clear",
    2: "Partly cloudy",
    3: "Overcast",
    45: "Fog",
    48: "Depositing rime fog",
    51: "Light drizzle",
    53: "Drizzle",
    55: "Dense drizzle",
    56: "Freezing drizzle",
    57: "Dense freezing drizzle",
    61: "Light rain",
    63: "Rain",
    65: "Heavy rain",
    66: "Freezing rain",
    67: "Heavy freezing rain",
    71: "Light snow",
    73: "Snow",
    75: "Heavy snow",
    77: "Snow grains",
    80: "Light rain showers",
    81: "Rain showers",
    82: "Violent rain showers",
    85: "Snow showers",
    86: "Heavy snow showers",
    95: "Thunderstorm",
    96: "Thunderstorm with hail",
    99: "Thunderstorm with heavy hail",
}


async def save_location(user_id: int, latitude: float, longitude: float) -> None:
    record = {"lat": latitude, "lon": longitude, "ts": int(time.time())}
    await _get_redis().set(LOCATION_KEY.format(user_id=user_id), json.dumps(record))


async def get_location(user_id: int) -> dict | None:
    raw = await _get_redis().get(LOCATION_KEY.format(user_id=user_id))
    if not raw:
        return None
    try:
        record = json.loads(raw)
        return {"lat": float(record["lat"]), "lon": float(record["lon"])}
    except (TypeError, ValueError, KeyError):
        return None


async def _from_google(lat: float, lon: float, api_key: str) -> dict | None:
    params = {
        "key": api_key,
        "location.latitude": lat,
        "location.longitude": lon,
        "unitsSystem": "METRIC",
    }
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(
            "https://weather.googleapis.com/v1/currentConditions:lookup",
            params=params,
        )
        resp.raise_for_status()
        data = resp.json()

    condition = (data.get("weatherCondition") or {}).get("description") or {}
    wind_speed = ((data.get("wind") or {}).get("speed") or {}).get("value")
    return {
        "desc": condition.get("text") or "—",
        "temp_c": (data.get("temperature") or {}).get("degrees"),
        "feels_c": (data.get("feelsLikeTemperature") or {}).get("degrees"),
        "humidity": data.get("relativeHumidity"),
        "wind_kmh": wind_speed,
        "source": "Google Weather",
    }


async def _from_open_meteo(lat: float, lon: float) -> dict | None:
    params = {
        "latitude": lat,
        "longitude": lon,
        "current": (
            "temperature_2m,apparent_temperature,relative_humidity_2m,"
            "weather_code,wind_speed_10m"
        ),
    }
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get("https://api.open-meteo.com/v1/forecast", params=params)
        resp.raise_for_status()
        data = resp.json()

    current = data.get("current") or {}
    return {
        "desc": _WMO_CODES.get(current.get("weather_code"), "—"),
        "temp_c": current.get("temperature_2m"),
        "feels_c": current.get("apparent_temperature"),
        "humidity": current.get("relative_humidity_2m"),
        "wind_kmh": current.get("wind_speed_10m"),
        "source": "Open-Meteo",
    }


async def get_current_weather(lat: float, lon: float) -> dict | None:
    """Fetch current conditions, or None if every provider fails."""
    api_key = os.environ.get("GOOGLE_WEATHER_API_KEY")
    if api_key:
        try:
            return await _from_google(lat, lon, api_key)
        except Exception as err:
            print(f"[weather] Google Weather failed, trying Open-Meteo: {err}")
    try:
        return await _from_open_meteo(lat, lon)
    except Exception as err:
        print(f"[weather] Open-Meteo failed: {err}")
        return None


def _condition_emoji(desc: str) -> str:
    d = desc.lower()
    if "thunder" in d or "storm" in d:
        return "⛈️"
    if "snow" in d or "ice" in d or "freezing" in d:
        return "❄️"
    if "rain" in d or "drizzle" in d or "shower" in d:
        return "🌧️"
    if "fog" in d or "mist" in d or "haze" in d:
        return "🌫️"
    if "overcast" in d or "cloud" in d:
        return "☁️"
    if "clear" in d or "sun" in d:
        return "☀️"
    return "🌤️"


def _fmt_num(value, suffix: str) -> str:
    if value is None:
        return "—"
    return f"{round(float(value))}{suffix}"


def format_weather(name: str, weather: dict) -> str:
    emoji = _condition_emoji(weather["desc"])
    lines = [
        f"{emoji} Weather for {name}: {weather['desc']}",
        (
            f"🌡️ {_fmt_num(weather['temp_c'], '°C')}"
            f" (feels like {_fmt_num(weather['feels_c'], '°C')})"
        ),
        (
            f"💧 Humidity {_fmt_num(weather['humidity'], '%')}"
            f" · 💨 Wind {_fmt_num(weather['wind_kmh'], ' km/h')}"
        ),
        f"— {weather['source']}",
    ]
    return "\n".join(lines)
