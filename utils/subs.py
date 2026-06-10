"""Допоміжні функції для підписок: парсинг суми, дати, цикли, статистика."""
from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from utils.timeparse import parse_when

CYCLE_LABELS = {
    "monthly": "щомісяця",
    "yearly": "щороку",
    "weekly": "щотижня",
}

# Нормалізація валют до символу
CURRENCY_MAP = {
    "грн": "₴", "uah": "₴", "₴": "₴", "гривень": "₴", "гривня": "₴",
    "usd": "$", "$": "$", "долар": "$", "доларів": "$", "бакс": "$",
    "eur": "€", "€": "€", "євро": "€",
    "pln": "zł", "zł": "zł", "zl": "zł", "злотих": "zł",
    "gbp": "£", "£": "£",
}


def parse_amount(text: str) -> tuple[float, str] | None:
    """'199 грн' / '9.99 USD' / '12,50€' / '500' -> (199.0, '₴')."""
    m = re.search(r"(\d+(?:[.,]\d+)?)", text)
    if not m:
        return None
    amount = float(m.group(1).replace(",", "."))
    rest = (text[: m.start()] + " " + text[m.end():]).lower()
    currency = "₴"
    for key, sym in CURRENCY_MAP.items():
        if key in rest:
            currency = sym
            break
    return amount, currency


def parse_date_only(text: str, tz_name: str) -> str | None:
    """Повертає дату YYYY-MM-DD (локальну) з тексту або None."""
    parsed = parse_when(text, tz_name)
    if parsed is None:
        return None
    dt_utc = parsed[0]
    local = dt_utc.astimezone(ZoneInfo(tz_name))
    return local.strftime("%Y-%m-%d")


def advance_date(date_str: str, cycle: str) -> str:
    """Наступна дата оплати після поточної згідно з циклом."""
    d = datetime.strptime(date_str, "%Y-%m-%d").date()
    if cycle == "weekly":
        d = d + timedelta(days=7)
    elif cycle == "yearly":
        try:
            d = d.replace(year=d.year + 1)
        except ValueError:  # 29 лютого
            d = d.replace(year=d.year + 1, day=28)
    else:  # monthly
        month = d.month + 1
        year = d.year + (month - 1) // 12
        month = (month - 1) % 12 + 1
        day = min(d.day, 28)
        d = date(year, month, day)
    return d.strftime("%Y-%m-%d")


def advance_until_future_date(date_str: str, cycle: str, today: date) -> str:
    """Прокручує дату оплати вперед, поки вона не стане сьогодні/в майбутньому."""
    d = date_str
    for _ in range(600):
        if datetime.strptime(d, "%Y-%m-%d").date() >= today:
            return d
        d = advance_date(d, cycle)
    return d


def monthly_equiv(amount: float, cycle: str) -> float:
    if cycle == "yearly":
        return amount / 12
    if cycle == "weekly":
        return amount * 52 / 12
    return amount


def days_until(date_str: str, tz_name: str) -> int:
    today = datetime.now(ZoneInfo(tz_name)).date()
    d = datetime.strptime(date_str, "%Y-%m-%d").date()
    return (d - today).days


def fmt_date(date_str: str) -> str:
    from utils.format import MONTHS
    d = datetime.strptime(date_str, "%Y-%m-%d").date()
    return f"{d.day} {MONTHS[d.month - 1]} {d.year}"


def fmt_amount(amount: float, currency: str) -> str:
    if amount == int(amount):
        return f"{int(amount)} {currency}"
    return f"{amount:.2f} {currency}"


def compute_stats(subs: list) -> dict:
    """Підсумкова статистика по підписках, згрупована за валютою."""
    by_currency: dict[str, dict] = {}
    for s in subs:
        cur = s["currency"]
        b = by_currency.setdefault(cur, {"monthly": 0.0, "count": 0})
        b["monthly"] += monthly_equiv(s["amount"], s["cycle"])
        b["count"] += 1
    return by_currency
