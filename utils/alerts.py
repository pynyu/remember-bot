"""Обчислення часу завчасних попереджень про нагадування.

Види (kind):
  evening — ввечері напередодні (о evening_hour годині дня, що передує події)
  morning — зранку в день події (о morning_hour годині)
  hour    — за годину до події
  day     — за добу до події (о morning_hour годині)
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

ALERT_KINDS = ["evening", "morning", "hour", "day"]

ALERT_LABEL = {
    "evening": "🌙 Напередодні",
    "morning": "☀️ Вранці",
    "hour": "⏰ За годину",
    "day": "📅 За добу",
}


def compute_alert_times(
    base_utc: datetime, kinds: list[str], evening_hour: int, morning_hour: int,
    tz_name: str, now_utc: datetime,
) -> list[tuple[str, datetime]]:
    """Повертає [(kind, fire_at_utc), ...] лише для майбутніх і доречних
    попереджень (раніших за саму подію)."""
    tz = ZoneInfo(tz_name)
    base_local = base_utc.astimezone(tz)
    out: list[tuple[str, datetime]] = []

    for kind in kinds:
        fire_local = None
        if kind == "evening":
            prev_day = base_local - timedelta(days=1)
            fire_local = prev_day.replace(
                hour=evening_hour, minute=0, second=0, microsecond=0
            )
        elif kind == "morning":
            fire_local = base_local.replace(
                hour=morning_hour, minute=0, second=0, microsecond=0
            )
        elif kind == "hour":
            fire_local = base_local - timedelta(hours=1)
        elif kind == "day":
            fire_local = (base_local - timedelta(days=1)).replace(
                hour=morning_hour, minute=0, second=0, microsecond=0
            )
        if fire_local is None:
            continue
        fire_utc = fire_local.astimezone(timezone.utc)
        # тільки в майбутньому і строго раніше за саму подію
        if fire_utc > now_utc and fire_utc < base_utc:
            out.append((kind, fire_utc))
    return out


def parse_kinds(s: str) -> list[str]:
    return [k for k in (s or "").split(",") if k in ALERT_KINDS]


def join_kinds(kinds: list[str]) -> str:
    seen = []
    for k in ALERT_KINDS:
        if k in kinds and k not in seen:
            seen.append(k)
    return ",".join(seen)
