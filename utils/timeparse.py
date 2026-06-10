"""Розпізнавання часу нагадування з природної мови (українська).

Повертає кортеж (fire_at_utc: datetime, repeat: str, clean_text: str), де
clean_text — це текст нагадування без часової частини. Якщо час розпізнати
не вдалося — повертає None.

Приклади того, що розуміється:
    через 30 хвилин купити хліб
    через 2 години
    через 3 дні подзвонити мамі
    завтра о 9:00 зустріч
    сьогодні о 18:30
    післязавтра о 10
    о 15:00 обід              (сьогодні, або завтра якщо час уже минув)
    25.12 о 10:00 подарунки
    25.12.2026 14:00
    щодня о 9:00 зарядка       -> repeat=daily
    щотижня у понеділок о 10   -> repeat=weekly
    щомісяця 1 числа           -> repeat=monthly
    по буднях о 8:00           -> repeat=weekdays
    у пʼятницю о 17:00
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import Optional, Tuple
from zoneinfo import ZoneInfo

Result = Tuple[datetime, str, str]

WEEKDAYS = {
    "понеділок": 0, "понеділка": 0, "пн": 0,
    "вівторок": 1, "вівторка": 1, "вт": 1,
    "середу": 2, "середа": 2, "ср": 2,
    "четвер": 3, "четверга": 3, "чт": 3,
    "пʼятницю": 4, "п'ятницю": 4, "пятницю": 4, "пʼятниця": 4, "пятниця": 4, "пт": 4,
    "суботу": 5, "субота": 5, "сб": 5,
    "неділю": 6, "неділя": 6, "нд": 6,
}

MONTH_UNITS = {"місяц", "міс"}
WEEK_UNITS = {"тиждень", "тижні", "тижнів", "тижня"}
DAY_UNITS = {"день", "дні", "днів", "дня", "д"}
HOUR_UNITS = {"годину", "години", "годин", "год", "г"}
MIN_UNITS = {"хвилину", "хвилини", "хвилин", "хв", "хвилинку"}


def _strip(text: str, *patterns: str) -> str:
    """Прибирає з тексту знайдені часові патерни та зайві пробіли."""
    for p in patterns:
        text = re.sub(p, " ", text, flags=re.IGNORECASE)
    text = re.sub(r"\s+", " ", text).strip(" ,.-—")
    return text


def _parse_time_token(text: str) -> Optional[Tuple[int, int, str]]:
    """Шукає 'о 15:00' / '15:00' / 'о 9'. Повертає (год, хв, matched_substr)."""
    m = re.search(r"(?:об?\s+)?(\d{1,2})[:.](\d{2})", text, re.IGNORECASE)
    if m:
        h, mn = int(m.group(1)), int(m.group(2))
        if 0 <= h <= 23 and 0 <= mn <= 59:
            return h, mn, m.group(0)
    m = re.search(r"\bоб?\s+(\d{1,2})\b", text, re.IGNORECASE)
    if m:
        h = int(m.group(1))
        if 0 <= h <= 23:
            return h, 0, m.group(0)
    return None


def parse_when(text: str, tz_name: str) -> Optional[Result]:
    tz = ZoneInfo(tz_name)
    now = datetime.now(tz)
    low = text.lower()

    repeat = "none"
    if re.search(r"\bпо\s+буднях\b|\bщобуд", low):
        repeat = "weekdays"
    elif re.search(r"\bщодня\b|\bщоденно\b|\bкожен\s+день\b|\bкожного\s+дня\b", low):
        repeat = "daily"
    elif re.search(r"\bщотижня\b|\bкожен\s+тиждень\b|\bщотижнев",  low):
        repeat = "weekly"
    elif re.search(r"\bщомісяця\b|\bкожен\s+місяць\b|\bщомісячно\b", low):
        repeat = "monthly"
    elif re.search(r"\bщороку\b|\bщорічно\b|\bкожен\s+рік\b", low):
        repeat = "yearly"

    # --- 1. Відносний час: "через N одиниць" -------------------------------
    m = re.search(
        r"через\s+(\d+)?\s*([а-яіїєґ']+)", low
    )
    if m and repeat == "none":
        qty = int(m.group(1)) if m.group(1) else 1
        unit = m.group(2)
        delta = None
        if unit.startswith("хв") or unit.startswith("хвил"):
            delta = timedelta(minutes=qty)
        elif unit.startswith("год") or unit == "г":
            delta = timedelta(hours=qty)
        elif unit.startswith("дн") or unit in ("день", "д", "дня"):
            delta = timedelta(days=qty)
        elif unit.startswith("тиж"):
            delta = timedelta(weeks=qty)
        elif unit.startswith("міс"):
            delta = timedelta(days=30 * qty)
        if delta is not None:
            fire = now + delta
            clean = _strip(text, r"через\s+\d*\s*[а-яіїєґ']+")
            return fire.astimezone(ZoneInfo("UTC")), "none", clean or "Нагадування"

    # --- час доби (потрібен майже всюди) -----------------------------------
    tt = _parse_time_token(low)
    hh, mm = (tt[0], tt[1]) if tt else (9, 0)  # дефолт 9:00, якщо час не вказано

    # --- 2. Дата вигляду 25.12 або 25.12.2026 ------------------------------
    md = re.search(r"\b(\d{1,2})\.(\d{1,2})(?:\.(\d{2,4}))?\b", low)
    if md:
        day, month = int(md.group(1)), int(md.group(2))
        year = now.year
        if md.group(3):
            year = int(md.group(3))
            if year < 100:
                year += 2000
        try:
            fire = now.replace(
                year=year, month=month, day=day, hour=hh, minute=mm,
                second=0, microsecond=0,
            )
            if not md.group(3) and fire < now:
                fire = fire.replace(year=year + 1)
            clean = _strip(text, r"\b\d{1,2}\.\d{1,2}(?:\.\d{2,4})?\b",
                           r"(?:об?\s+)?\d{1,2}[:.]\d{2}", r"\bоб?\s+\d{1,2}\b")
            return fire.astimezone(ZoneInfo("UTC")), repeat, clean or "Нагадування"
        except ValueError:
            pass

    # --- 3. Дні тижня ------------------------------------------------------
    for word, wd in WEEKDAYS.items():
        if re.search(rf"\b{re.escape(word)}\b", low):
            days_ahead = (wd - now.weekday()) % 7
            base = now + timedelta(days=days_ahead)
            fire = base.replace(hour=hh, minute=mm, second=0, microsecond=0)
            if days_ahead == 0 and fire < now:
                fire += timedelta(days=7)
            if repeat == "none":
                repeat = "weekly"
            clean = _strip(text, rf"\bу?\s*{re.escape(word)}\b", r"щотижня",
                           r"(?:об?\s+)?\d{1,2}[:.]\d{2}", r"\bоб?\s+\d{1,2}\b")
            return fire.astimezone(ZoneInfo("UTC")), repeat, clean or "Нагадування"

    # --- 4. сьогодні / завтра / післязавтра --------------------------------
    day_offset = None
    if re.search(r"\bпіслязавтра\b", low):
        day_offset = 2
    elif re.search(r"\bзавтра\b", low):
        day_offset = 1
    elif re.search(r"\bсьогодні\b", low):
        day_offset = 0

    if day_offset is not None or tt is not None or repeat != "none":
        offset = day_offset if day_offset is not None else 0
        fire = (now + timedelta(days=offset)).replace(
            hour=hh, minute=mm, second=0, microsecond=0
        )
        # якщо час уже минув і дата не вказана явно — переносимо на завтра
        if day_offset is None and fire < now and repeat == "none":
            fire += timedelta(days=1)
        clean = _strip(
            text,
            r"\bпіслязавтра\b", r"\bзавтра\b", r"\bсьогодні\b",
            r"\bщодня\b", r"\bщоденно\b", r"\bкожен\s+день\b", r"\bкожного\s+дня\b",
            r"\bпо\s+буднях\b", r"\bщобудня\b",
            r"\bщотижня\b", r"\bщомісяця\b", r"\bщороку\b", r"\bщорічно\b",
            r"(?:об?\s+)?\d{1,2}[:.]\d{2}", r"\bоб?\s+\d{1,2}\b",
        )
        return fire.astimezone(ZoneInfo("UTC")), repeat, clean or "Нагадування"

    return None


def extract_extras(text: str) -> tuple[Optional[int], Optional[int], str]:
    """Витягує з тексту необов'язкові «×N повторів» та позначку важливості.

    Повертає (count|None, priority|None, очищений_текст).
      ×3 / x3 / 3 рази      -> count
      !! / важливо / терміново -> priority=2
      тихо / без звуку       -> priority=0
    """
    count = None
    priority = None
    m = re.search(r"[x×х]\s?(\d{1,2})\b|\b(\d{1,2})\s+раз", text, re.IGNORECASE)
    if m:
        count = int(m.group(1) or m.group(2))
        count = max(1, min(count, 20))
        text = text[: m.start()] + text[m.end():]
    low = text.lower()
    if re.search(r"\bважлив|терміново|!!|‼", low):
        priority = 2
    elif re.search(r"\bтихо\b|без\s+звук", low):
        priority = 0
    text = re.sub(r"!!+|‼|\bтихо\b|без\s+звуку|\bважливо\b|\bтерміново\b", " ",
                  text, flags=re.IGNORECASE)
    text = re.sub(r"\s+", " ", text).strip(" ,.-—!")
    return count, priority, text


def advance_until_future(
    base_utc: datetime, repeat: str, tz_name: str, now_utc: datetime
) -> datetime:
    """Наступне майбутнє спрацювання повторюваного нагадування (з пропуском
    прострочених періодів, якщо бот був вимкнений довго)."""
    nxt = base_utc
    for _ in range(2000):  # запобіжник від нескінченного циклу
        nxt = next_fire(nxt, repeat, tz_name) or nxt
        if nxt > now_utc:
            return nxt
    return nxt


def next_fire(prev_utc: datetime, repeat: str, tz_name: str) -> Optional[datetime]:
    """Обчислює наступний час спрацювання для повторюваного нагадування."""
    if repeat == "none":
        return None
    tz = ZoneInfo(tz_name)
    local = prev_utc.astimezone(tz)
    if repeat == "daily":
        nxt = local + timedelta(days=1)
    elif repeat == "weekdays":
        nxt = local + timedelta(days=1)
        while nxt.weekday() >= 5:  # пропускаємо суботу/неділю
            nxt += timedelta(days=1)
    elif repeat == "weekly":
        nxt = local + timedelta(weeks=1)
    elif repeat == "monthly":
        month = local.month + 1
        year = local.year + (month - 1) // 12
        month = (month - 1) % 12 + 1
        day = min(local.day, 28)
        nxt = local.replace(year=year, month=month, day=day)
    elif repeat == "yearly":
        nxt = local.replace(year=local.year + 1)
    else:
        return None
    return nxt.astimezone(ZoneInfo("UTC"))


REPEAT_LABELS = {
    "none": "одноразово",
    "daily": "щодня",
    "weekdays": "по буднях",
    "weekly": "щотижня",
    "monthly": "щомісяця",
    "yearly": "щороку",
}
