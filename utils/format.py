"""Допоміжні функції форматування для відображення користувачу."""
from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

MONTHS = [
    "січня", "лютого", "березня", "квітня", "травня", "червня",
    "липня", "серпня", "вересня", "жовтня", "листопада", "грудня",
]
WEEKDAYS_SHORT = ["пн", "вт", "ср", "чт", "пт", "сб", "нд"]


# Емодзі-позначка пріоритету для тексту повідомлень
PRIORITY_TAG = {0: "", 1: "", 2: "🔴 "}
# Підпис пріоритету для кнопок/списків
PRIORITY_LABEL = {0: "🔇 Тихо", 1: "🔔 Звичайно", 2: "🔴 Важливо"}
PRIORITY_MARK = {0: "🔇", 1: "", 2: "🔴"}


def fmt_dt(utc_iso: str, tz_name: str) -> str:
    dt = datetime.fromisoformat(utc_iso).astimezone(ZoneInfo(tz_name))
    wd = WEEKDAYS_SHORT[dt.weekday()]
    return f"{dt.day} {MONTHS[dt.month - 1]}, {wd} о {dt.strftime('%H:%M')}"


def human_left(utc_iso: str, tz_name: str) -> str:
    dt = datetime.fromisoformat(utc_iso)
    now = datetime.now(dt.tzinfo)
    delta = dt - now
    secs = int(delta.total_seconds())
    if secs < 0:
        return "зараз"
    if secs < 3600:
        return f"через {secs // 60} хв"
    if secs < 86400:
        h = secs // 3600
        return f"через {h} год"
    d = secs // 86400
    return f"через {d} дн"
