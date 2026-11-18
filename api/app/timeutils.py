"""Conversions between Odoo datetimes (naive UTC strings) and local time."""
from __future__ import annotations

from datetime import datetime, timezone
from urllib.parse import unquote
from zoneinfo import ZoneInfo

ODOO_FORMAT = "%Y-%m-%d %H:%M:%S"


def odoo_to_local(value: str | bool | None, tz: str) -> str | None:
    """'2025-10-31 21:00:00' (UTC, as stored by Odoo) -> '2025-10-31 22:00:00' in `tz`."""
    if not value:
        return None
    utc_dt = datetime.strptime(str(value), ODOO_FORMAT).replace(tzinfo=timezone.utc)
    return utc_dt.astimezone(ZoneInfo(tz)).strftime(ODOO_FORMAT)


def parse_user_datetime(value: str, tz: str) -> datetime:
    """Parse a date entered by a user ('2025-10-20 15:30', '2025-10-20T15:30:00',
    URL-encoded or not, with or without offset). Naive values are read in `tz`.
    Raises ValueError if the value is not a valid date-time."""
    text = unquote(value).strip()
    if not text or text.lower() in {"undefined", "null", "none"}:
        raise ValueError("empty date")
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=ZoneInfo(tz))
    return dt


def to_odoo(dt: datetime) -> str:
    """Aware datetime -> naive UTC string expected by Odoo."""
    return dt.astimezone(timezone.utc).strftime(ODOO_FORMAT)
