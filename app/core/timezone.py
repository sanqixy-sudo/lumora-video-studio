from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

SHANGHAI_TZ = ZoneInfo("Asia/Shanghai")


def utcnow() -> datetime:
    return datetime.now(UTC)


def shanghai_now() -> datetime:
    return datetime.now(SHANGHAI_TZ)


def month_bounds_utc(year: int, month: int) -> tuple[datetime, datetime]:
    start_local = datetime(year, month, 1, 0, 0, 0, tzinfo=SHANGHAI_TZ)
    if month == 12:
        end_local = datetime(year + 1, 1, 1, 0, 0, 0, tzinfo=SHANGHAI_TZ)
    else:
        end_local = datetime(year, month + 1, 1, 0, 0, 0, tzinfo=SHANGHAI_TZ)
    return start_local.astimezone(UTC), end_local.astimezone(UTC)


def date_bounds_utc(value: date) -> tuple[datetime, datetime]:
    start_local = datetime.combine(value, time.min, tzinfo=SHANGHAI_TZ)
    end_local = start_local + timedelta(days=1)
    return start_local.astimezone(UTC), end_local.astimezone(UTC)


def to_shanghai_date(value: datetime) -> date:
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(SHANGHAI_TZ).date()


def _to_shanghai_datetime(value: datetime | str | None) -> datetime | str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(SHANGHAI_TZ)


def format_shanghai_datetime(value: datetime | None) -> str:
    converted = _to_shanghai_datetime(value)
    if converted is None:
        return "-"
    if isinstance(converted, str):
        return converted
    return converted.strftime("%Y-%m-%d %H:%M:%S")


def format_shanghai_datetime_short(value: datetime | None) -> str:
    converted = _to_shanghai_datetime(value)
    if converted is None:
        return "-"
    if isinstance(converted, str):
        # API serializers may already have produced a full Shanghai timestamp.
        return converted[:16] if len(converted) >= 16 else converted
    return converted.strftime("%Y-%m-%d %H:%M")
