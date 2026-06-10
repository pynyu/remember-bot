"""Планувальник нагадувань — модель опитування (polling).

Раз на POLL_SECONDS перевіряємо БД на нагадування, час яких настав, і
надсилаємо їх. Перевага перед «таймером на кожне нагадування»: якщо бот був
вимкнений у момент спрацювання, нагадування все одно надішлеться одразу після
старту — нічого не губиться.

Цикл одного нагадування:
  • спрацьовує о base_at — надсилаємо перше сповіщення;
  • якщо налаштовано кілька сповіщень (notify_count > 1) — надсилаємо ще раз
    кожні notify_interval хвилин, поки користувач не натисне «✅ Готово»;
  • коли сповіщення вичерпано: одноразове -> деактивується, повторюване ->
    переноситься на наступний період.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from aiogram import Bot
from apscheduler.schedulers.asyncio import AsyncIOScheduler

import database as db
from keyboards import fired_actions
from utils.format import PRIORITY_TAG, fmt_dt
from utils.timeparse import REPEAT_LABELS, advance_until_future

log = logging.getLogger(__name__)

POLL_SECONDS = 20

_scheduler: AsyncIOScheduler | None = None
_bot: Bot | None = None


async def setup_scheduler(bot: Bot) -> None:
    global _scheduler, _bot
    _bot = bot
    _scheduler = AsyncIOScheduler(timezone="UTC")
    _scheduler.add_job(
        poll_due, "interval", seconds=POLL_SECONDS,
        id="poll", max_instances=1, coalesce=True,
    )
    _scheduler.start()
    await poll_due()  # одразу підхопити прострочені
    log.info("Планувальник запущено (опитування кожні %s с)", POLL_SECONDS)


async def poll_due(now: datetime | None = None) -> None:
    now = now or datetime.now(timezone.utc)
    try:
        rows = await db.due_reminders(now)
    except Exception as e:
        log.exception("poll_due: помилка читання БД: %s", e)
        return
    for r in rows:
        try:
            await fire_one(r, now)
        except Exception as e:
            log.exception("Помилка спрацювання нагадування %s: %s", r["id"], e)
    try:
        await _check_digests(now)
    except Exception as e:
        log.exception("Помилка дайджесту: %s", e)
    try:
        await _check_subscriptions(now)
    except Exception as e:
        log.exception("Помилка перевірки підписок: %s", e)


async def _check_digests(now: datetime) -> None:
    """Надсилає ранковий дайджест користувачам, у кого настав їхній час."""
    users = await db.users_with_digest()
    for u in users:
        try:
            tz = ZoneInfo(u["tz"])
        except Exception:
            continue
        local = now.astimezone(tz)
        today = local.strftime("%Y-%m-%d")
        if u["digest_last"] == today:
            continue
        try:
            hh, mm = (int(x) for x in u["digest_time"].split(":"))
        except Exception:
            continue
        target = local.replace(hour=hh, minute=mm, second=0, microsecond=0)
        if local >= target:
            await _send_digest(u, now)
            await db.set_digest_last(u["user_id"], today)


async def _send_digest(u, now: datetime) -> None:
    assert _bot is not None
    tz_name = u["tz"]
    tz = ZoneInfo(tz_name)
    local = now.astimezone(tz)
    end = local.replace(hour=23, minute=59, second=59)
    reminders = await db.list_reminders(u["user_id"])
    today = [
        r for r in reminders
        if datetime.fromisoformat(r["base_at"]).astimezone(tz) <= end
    ]
    checklists = await db.list_checklists(u["user_id"])

    lines = [f"🌅 <b>Доброго ранку!</b> План на {local.strftime('%d.%m')}:\n"]
    if today:
        lines.append("⏰ <b>Нагадування на сьогодні:</b>")
        for r in today:
            prio = "🔴 " if r["priority"] == 2 else ""
            lines.append(f"• {prio}{r['text']} — {fmt_dt(r['base_at'], tz_name)}")
    else:
        lines.append("⏰ На сьогодні нагадувань немає.")
    if checklists:
        lines.append(f"\n✅ Активних чеклістів: {len(checklists)}")
    lines.append("\nГарного дня! ☀️")
    try:
        await _bot.send_message(u["user_id"], "\n".join(lines))
    except Exception as e:
        log.warning("Не вдалося надіслати дайджест %s: %s", u["user_id"], e)


async def _check_subscriptions(now: datetime) -> None:
    """Нагадування про оплату підписки та кінець пробного періоду."""
    from datetime import datetime as _dt, timedelta as _td

    subs = await db.all_active_subscriptions()
    tz_cache: dict[int, ZoneInfo] = {}
    for s in subs:
        uid = s["user_id"]
        if uid not in tz_cache:
            try:
                tz_cache[uid] = ZoneInfo(await db.get_tz(uid))
            except Exception:
                tz_cache[uid] = ZoneInfo("Europe/Kyiv")
        local = now.astimezone(tz_cache[uid])

        # --- нагадування про оплату (за remind_days днів, о 09:00) ---
        if s["pay_reminded"] != s["next_date"]:
            try:
                pay_d = _dt.strptime(s["next_date"], "%Y-%m-%d").date()
                remind_on = pay_d - _td(days=s["remind_days"])
                trigger = local.replace(hour=9, minute=0, second=0, microsecond=0)
                trigger = trigger.replace(
                    year=remind_on.year, month=remind_on.month, day=remind_on.day
                )
                if local >= trigger:
                    days_left = (pay_d - local.date()).days
                    when = "сьогодні" if days_left == 0 else (
                        "завтра" if days_left == 1 else f"через {days_left} дн")
                    await _notify(
                        s["user_id"],
                        f"💳 <b>Скоро оплата підписки</b>\n\n"
                        f"<b>{s['name']}</b> — {_amount(s)}\n"
                        f"📆 Оплата {when} ({s['next_date']}).\n\n"
                        f"Коли оплатиш — відкрий 💳 Підписки → «✅ Оплачено».",
                    )
                    await db.update_subscription(s["id"], "pay_reminded", s["next_date"])
            except Exception as e:
                log.warning("sub pay reminder %s: %s", s["id"], e)

        # --- нагадування про кінець пробного періоду (за день, о 09:00) ---
        if s["trial_end"] and not s["trial_reminded"]:
            try:
                trial_d = _dt.strptime(s["trial_end"], "%Y-%m-%d").date()
                remind_on = trial_d - _td(days=1)
                trigger = local.replace(
                    hour=9, minute=0, second=0, microsecond=0
                ).replace(year=remind_on.year, month=remind_on.month, day=remind_on.day)
                if local >= trigger:
                    await _notify(
                        s["user_id"],
                        f"🎁 <b>Закінчується пробний період!</b>\n\n"
                        f"<b>{s['name']}</b> — пробний до {s['trial_end']}.\n"
                        f"⚠️ Якщо не плануєш платити — скасуй <u>зараз</u>, "
                        f"щоб не списали {_amount(s)}.",
                    )
                    await db.update_subscription(s["id"], "trial_reminded", 1)
            except Exception as e:
                log.warning("sub trial reminder %s: %s", s["id"], e)


def _amount(s) -> str:
    a = s["amount"]
    a = int(a) if a == int(a) else round(a, 2)
    return f"{a} {s['currency']}"


async def _notify(user_id: int, text: str) -> None:
    assert _bot is not None
    try:
        await _bot.send_message(user_id, text)
    except Exception as e:
        log.warning("Не вдалося надіслати %s: %s", user_id, e)


async def _send(r, now: datetime, ping_no: int, total: int) -> None:
    assert _bot is not None
    priority = r["priority"]
    tag = PRIORITY_TAG.get(priority, "")
    repeat = r["repeat"]
    parts = [f"🔔 {tag}<b>Нагадування!</b>".strip()]
    parts.append(f"\n{r['text']}")
    if repeat != "none":
        parts.append(f"\n\n🔁 {REPEAT_LABELS.get(repeat, repeat)}")
    if total > 1:
        parts.append(f"\n<i>сповіщення {ping_no}/{total}</i>")
    # priority 0 = тихо (без звуку), 1/2 = зі звуком
    silent = priority == 0
    try:
        await _bot.send_message(
            r["user_id"],
            "".join(parts),
            reply_markup=fired_actions(r["id"]),
            disable_notification=silent,
        )
    except Exception as e:
        log.warning("Не вдалося надіслати нагадування %s: %s", r["id"], e)


async def fire_one(r, now: datetime) -> None:
    """Обробити одне прострочене нагадування (надіслати + оновити стан)."""
    total = r["notify_count"]
    ping_no = total - r["pings_left"] + 1
    await _send(r, now, ping_no, total)

    pings_left = r["pings_left"] - 1
    base_at = datetime.fromisoformat(r["base_at"])

    if pings_left > 0:
        # ще є повтори у цьому циклі — наступний через notify_interval хв
        next_fire = now + timedelta(minutes=r["notify_interval"])
        await db.set_cycle(r["id"], base_at, next_fire, pings_left)
        return

    # цикл сповіщень вичерпано
    if r["repeat"] != "none":
        tz = await db.get_tz(r["user_id"])
        new_base = advance_until_future(base_at, r["repeat"], tz, now)
        await db.set_cycle(r["id"], new_base, new_base, total)
    else:
        await db.deactivate_reminder(r["id"])
