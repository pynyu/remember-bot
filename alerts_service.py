"""Перегенерація завчасних попереджень для нагадування.

Викликається при створенні/зміні нагадування та при переході повторюваного
нагадування на наступний період. База рядків reminder_alerts — похідна від
reminders.alert_kinds + base_at + годин користувача.
"""
from __future__ import annotations

from datetime import datetime, timezone

import database as db
from utils.alerts import compute_alert_times, parse_kinds


async def regenerate(reminder, user) -> None:
    rid = reminder["id"]
    await db.clear_alerts(rid)
    kinds = parse_kinds(reminder["alert_kinds"])
    if not kinds:
        return
    base_utc = datetime.fromisoformat(reminder["base_at"])
    now = datetime.now(timezone.utc)
    times = compute_alert_times(
        base_utc, kinds, user["evening_hour"], user["morning_hour"],
        user["tz"], now,
    )
    for kind, fire_utc in times:
        await db.add_alert(reminder["user_id"], rid, kind, fire_utc)


async def regenerate_by_id(reminder_id: int) -> None:
    r = await db.get_reminder(reminder_id)
    if not r:
        return
    user = await db.get_user(r["user_id"])
    await regenerate(r, user)
