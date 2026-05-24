import asyncio
import json
from typing import Any
from urllib.parse import quote
from urllib.request import urlopen


def _http_get_json(url: str) -> dict[str, Any]:
    with urlopen(url, timeout=10) as response:
        return json.loads(response.read().decode("utf-8"))


def _normalize_location_name(requested_location: str, resolved_location: str | None) -> str:
    normalized_requested = requested_location.strip()
    normalized_resolved = (resolved_location or "").strip()

    city_aliases = {
        "上海": {"shanghai", "hongkou", "hongkew", "pudong", "pootung", "xuhui", "minhang"},
        "北京": {"beijing", "chaoyang", "haidian", "dongcheng", "xicheng"},
    }

    requested_lower = normalized_requested.lower()
    resolved_lower = normalized_resolved.lower()

    for preferred_name, aliases in city_aliases.items():
        if requested_lower == preferred_name.lower():
            return preferred_name
        if requested_lower in aliases:
            return preferred_name
        if resolved_lower in aliases and requested_lower in {preferred_name.lower(), *aliases}:
            return preferred_name

    if normalized_requested:
        return normalized_requested
    return normalized_resolved or "当前位置"


def _wttr_units_suffix(units: str) -> str:
    return "" if units == "metric" else "&u"


async def _fetch_wttr_weather(location: str, units: str) -> dict[str, Any]:
    encoded_location = quote(location.replace(" ", "+"))
    url = f"https://wttr.in/{encoded_location}?format=j1{_wttr_units_suffix(units)}"
    return await asyncio.to_thread(_http_get_json, url)


async def _fetch_open_meteo_weather(location: str, units: str) -> dict[str, Any]:
    encoded_location = quote(location)
    geocode_url = (
        "https://geocoding-api.open-meteo.com/v1/search"
        f"?name={encoded_location}&count=1&language=zh&format=json"
    )
    geocode_payload = await asyncio.to_thread(_http_get_json, geocode_url)
    results = geocode_payload.get("results") or []
    if not results:
        raise ValueError(f"无法解析地点：{location}")

    coordinates = results[0]
    temp_unit = "celsius" if units == "metric" else "fahrenheit"
    wind_unit = "kmh" if units == "metric" else "mph"
    forecast_url = (
        "https://api.open-meteo.com/v1/forecast"
        f"?latitude={coordinates['latitude']}"
        f"&longitude={coordinates['longitude']}"
        "&current=temperature_2m,relative_humidity_2m,weather_code,wind_speed_10m"
        "&daily=weather_code,temperature_2m_max,temperature_2m_min"
        f"&temperature_unit={temp_unit}"
        f"&wind_speed_unit={wind_unit}"
        "&timezone=auto&forecast_days=3"
    )
    forecast_payload = await asyncio.to_thread(_http_get_json, forecast_url)
    forecast_payload["_resolved_location"] = coordinates.get("name", location)
    return forecast_payload


def _weather_code_to_text(code: int | None) -> str:
    weather_map = {
        0: "晴朗",
        1: "基本晴朗",
        2: "局部多云",
        3: "阴天",
        45: "有雾",
        48: "冻雾",
        51: "小毛毛雨",
        53: "中等毛毛雨",
        55: "强毛毛雨",
        61: "小雨",
        63: "中雨",
        65: "大雨",
        71: "小雪",
        73: "中雪",
        75: "大雪",
        80: "阵雨",
        81: "强阵雨",
        82: "暴雨阵雨",
        95: "雷暴",
    }
    return weather_map.get(code, "未知")


def _translate_condition(condition: str) -> str:
    condition_map = {
        "clear": "晴朗",
        "sunny": "晴朗",
        "mainly clear": "大致晴朗",
        "partly cloudy": "局部多云",
        "cloudy": "多云",
        "overcast": "阴天",
        "mist": "薄雾",
        "fog": "有雾",
        "patchy rain nearby": "附近有零星降雨",
        "light drizzle": "小毛毛雨",
        "moderate drizzle": "中等毛毛雨",
        "dense drizzle": "强毛毛雨",
        "light rain": "小雨",
        "moderate rain": "中雨",
        "heavy rain": "大雨",
        "light snow": "小雪",
        "moderate snow": "中雪",
        "heavy snow": "大雪",
        "thundery outbreaks nearby": "附近有雷暴",
        "thunderstorm": "雷暴",
    }
    return condition_map.get(condition.strip().lower(), condition)


def _temperature_unit(units: str) -> str:
    return "度" if units == "metric" else "华氏度"


def _wind_unit(units: str) -> str:
    return "公里/小时" if units == "metric" else "英里/小时"


async def get_current_weather(location: str, units: str = "metric") -> dict[str, Any]:
    units = "metric" if units not in {"metric", "us"} else units

    try:
        payload = await _fetch_wttr_weather(location, units)
        current = (payload.get("current_condition") or [{}])[0]
        area = (payload.get("nearest_area") or [{}])[0]
        weather_desc = _translate_condition((current.get("weatherDesc") or [{}])[0].get("value", "未知"))
        resolved_location = area.get("areaName", [{}])[0].get("value", location)
        location_name = _normalize_location_name(location, resolved_location)
        humidity = current.get("humidity")
        wind = current.get("windspeedKmph") if units == "metric" else current.get("windspeedMiles")
        temperature = current.get("temp_C") if units == "metric" else current.get("temp_F")
        feels_like = current.get("FeelsLikeC") if units == "metric" else current.get("FeelsLikeF")

        summary = (
            f"{location_name}：{weather_desc}，当前 {temperature}{_temperature_unit(units)}，"
            f"体感 {feels_like}{_temperature_unit(units)}，湿度 {humidity}%，"
            f"风速 {wind} {_wind_unit(units)}"
        )
        return {
            "source": "wttr.in",
            "location": location_name,
            "condition": weather_desc,
            "temperature": temperature,
            "feels_like": feels_like,
            "humidity": humidity,
            "wind_speed": wind,
            "units": units,
            "summary": summary,
        }
    except Exception as primary_error:
        fallback = await _fetch_open_meteo_weather(location, units)
        current = fallback.get("current", {})
        location_name = _normalize_location_name(location, fallback.get("_resolved_location", location))
        summary = (
            f"{location_name}："
            f"{_weather_code_to_text(current.get('weather_code'))}，当前 "
            f"{current.get('temperature_2m')}{_temperature_unit(units)}，湿度 "
            f"{current.get('relative_humidity_2m')}%，风速 "
            f"{current.get('wind_speed_10m')} {_wind_unit(units)}"
        )
        return {
            "source": "open-meteo",
            "location": location_name,
            "condition": _weather_code_to_text(current.get("weather_code")),
            "temperature": current.get("temperature_2m"),
            "humidity": current.get("relative_humidity_2m"),
            "wind_speed": current.get("wind_speed_10m"),
            "units": units,
            "summary": summary,
            "fallback_reason": str(primary_error),
        }


async def get_forecast(location: str, days: int = 1, units: str = "metric") -> dict[str, Any]:
    units = "metric" if units not in {"metric", "us"} else units
    days = max(1, min(days, 3))

    try:
        payload = await _fetch_wttr_weather(location, units)
        forecast_days = payload.get("weather") or []
        selected_days = forecast_days[:days]
        summaries = []
        for day in selected_days:
            hourly_values = day.get("hourly") or [{}]
            hourly = hourly_values[min(4, len(hourly_values) - 1)]
            condition = _translate_condition((hourly.get("weatherDesc") or [{}])[0].get("value", "未知"))
            max_temp = day.get("maxtempC") if units == "metric" else day.get("maxtempF")
            min_temp = day.get("mintempC") if units == "metric" else day.get("mintempF")
            summaries.append(
                {
                    "date": day.get("date"),
                    "condition": condition,
                    "max_temp": max_temp,
                    "min_temp": min_temp,
                    "summary": (
                        f"{day.get('date')}：{condition}，"
                        f"{min_temp}{_temperature_unit(units)} 到 {max_temp}{_temperature_unit(units)}"
                    ),
                }
            )
        return {
            "source": "wttr.in",
            "location": _normalize_location_name(location, location),
            "days": summaries,
            "summary": " | ".join(day["summary"] for day in summaries),
        }
    except Exception as primary_error:
        fallback = await _fetch_open_meteo_weather(location, units)
        daily = fallback.get("daily", {})
        summaries = []
        for index in range(min(days, len(daily.get("time", [])))):
            condition = _weather_code_to_text((daily.get("weather_code") or [None])[index])
            min_temp = (daily.get("temperature_2m_min") or [None])[index]
            max_temp = (daily.get("temperature_2m_max") or [None])[index]
            day = (daily.get("time") or [None])[index]
            summaries.append(
                {
                    "date": day,
                    "condition": condition,
                    "max_temp": max_temp,
                    "min_temp": min_temp,
                    "summary": (
                        f"{day}：{condition}，"
                        f"{min_temp}{_temperature_unit(units)} 到 {max_temp}{_temperature_unit(units)}"
                    ),
                }
            )
        return {
            "source": "open-meteo",
            "location": _normalize_location_name(location, fallback.get("_resolved_location", location)),
            "days": summaries,
            "summary": " | ".join(day["summary"] for day in summaries),
            "fallback_reason": str(primary_error),
        }
