from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


DEFAULT_TIMEZONE = "Asia/Shanghai"
WEEKDAYS_ZH = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"]
WEEKDAYS_EN = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
FALLBACK_TIMEZONES = {
    "asia/shanghai": timezone(timedelta(hours=8), "Asia/Shanghai"),
    "utc": timezone.utc,
}


def _resolve_timezone(timezone_name: Optional[str]):
    normalized = (timezone_name or DEFAULT_TIMEZONE).strip()
    try:
        return ZoneInfo(normalized)
    except ZoneInfoNotFoundError:
        return FALLBACK_TIMEZONES.get(normalized.lower(), FALLBACK_TIMEZONES["asia/shanghai"])


def _parse_datetime(value: str) -> datetime:
    if "T" in value:
        return datetime.fromisoformat(value)
    return datetime.strptime(value, "%Y-%m-%d %H:%M:%S")


async def get_current_time(timezone: str = DEFAULT_TIMEZONE, format: str = "full") -> Dict[str, Any]:
    """Return the current time in the requested timezone."""
    tz = _resolve_timezone(timezone)
    now = datetime.now(tz)

    if format == "date":
        time_str = now.strftime("%Y-%m-%d")
    elif format == "time":
        time_str = now.strftime("%H:%M:%S")
    elif format == "iso":
        time_str = now.isoformat()
    else:
        time_str = now.strftime("%Y-%m-%d %H:%M:%S %Z")

    return {
        "time_str": time_str,
        "timestamp": now.timestamp(),
        "timezone": str(tz),
        "year": now.year,
        "month": now.month,
        "day": now.day,
        "hour": now.hour,
        "minute": now.minute,
        "weekday": WEEKDAYS_ZH[now.weekday()],
    }


async def convert_timezone(
    source_time: str,
    target_tz: str,
    source_tz: Optional[str] = None,
) -> Dict[str, Any]:
    """Convert a datetime string between timezones."""
    try:
        dt = _parse_datetime(source_time)

        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=_resolve_timezone(source_tz))

        target_timezone = _resolve_timezone(target_tz)
        target_dt = dt.astimezone(target_timezone)

        return {
            "source": {
                "time": dt.strftime("%Y-%m-%d %H:%M:%S"),
                "timezone": str(dt.tzinfo),
            },
            "target": {
                "time": target_dt.strftime("%Y-%m-%d %H:%M:%S"),
                "timezone": str(target_timezone),
            },
        }
    except Exception as exc:
        return {
            "error": str(exc),
            "message": "Time format is invalid. Use ISO format or 'YYYY-MM-DD HH:MM:SS'.",
        }


async def calculate_duration(start_time: str, end_time: str) -> Dict[str, Any]:
    """Calculate the duration between two datetime strings."""
    try:
        start_dt = _parse_datetime(start_time)
        end_dt = _parse_datetime(end_time)
        delta = abs(end_dt - start_dt)

        return {
            "start": start_time,
            "end": end_time,
            "total_seconds": delta.total_seconds(),
            "total_minutes": delta.total_seconds() / 60,
            "total_hours": delta.total_seconds() / 3600,
            "total_days": delta.days,
            "days": delta.days,
            "hours": delta.seconds // 3600,
            "minutes": (delta.seconds % 3600) // 60,
            "seconds": delta.seconds % 60,
            "human_readable": f"{delta.days} days {delta.seconds // 3600} hours {(delta.seconds % 3600) // 60} minutes",
        }
    except Exception as exc:
        return {
            "error": str(exc),
            "message": "Time format is invalid.",
        }


async def get_day_info(date: Optional[str] = None) -> Dict[str, Any]:
    """Return calendar information for a given day."""
    if date:
        try:
            dt = datetime.strptime(date, "%Y-%m-%d")
        except ValueError:
            dt = datetime.now()
    else:
        dt = datetime.now()

    is_weekend = dt.weekday() >= 5

    return {
        "date": dt.strftime("%Y-%m-%d"),
        "year": dt.year,
        "month": dt.month,
        "day": dt.day,
        "weekday": WEEKDAYS_ZH[dt.weekday()],
        "weekday_en": WEEKDAYS_EN[dt.weekday()],
        "weekday_num": dt.weekday() + 1,
        "is_weekend": is_weekend,
        "is_workday": not is_weekend,
        "day_of_year": dt.timetuple().tm_yday,
        "week_of_year": dt.isocalendar()[1],
    }
