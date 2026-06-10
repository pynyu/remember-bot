"""Дедлайни — одна дата, кілька завчасних нагадувань (за тиждень/день/у день)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

import database as db
from keyboards import cancel_kb, main_menu
from states import NewDeadline
from utils.format import fmt_dt
from utils.timeparse import parse_when

router = Router()

# За скільки днів до дедлайну нагадати (день 0 = у сам день)
LEADS = [7, 3, 1, 0]


@router.message(Command("deadline"))
@router.message(F.text == "🎯 Дедлайн")
async def deadline_start(message: Message, state: FSMContext) -> None:
    await db.ensure_user(message.from_user.id, message.from_user.username)
    await state.set_state(NewDeadline.waiting_text)
    await message.answer(
        "🎯 Напиши <b>що</b> і <b>дo якої дати</b>, напр.:\n"
        "<i>Здати річний звіт 25.12</i>\n"
        "<i>Продовжити страховку 1.07 о 12:00</i>\n\n"
        "Я нагадаю завчасно: за тиждень, за 3 дні, за день і в сам день. ⏳",
        reply_markup=cancel_kb(),
    )


@router.message(NewDeadline.waiting_text)
async def deadline_create(message: Message, state: FSMContext) -> None:
    user = await db.get_user(message.from_user.id)
    tz_name = user["tz"]
    parsed = parse_when(message.text or "", tz_name)
    if parsed is None:
        await message.answer(
            "🤔 Не побачив дати. Спробуй, напр.: <i>Здати звіт 25.12</i>",
            reply_markup=cancel_kb(),
        )
        return
    await state.clear()
    deadline_utc, _repeat, clean = parsed
    tz = ZoneInfo(tz_name)
    now = datetime.now(timezone.utc)
    deadline_local = deadline_utc.astimezone(tz)

    created = []
    for lead in LEADS:
        if lead == 0:
            fire_local = deadline_local
            label = "‼️ СЬОГОДНІ дедлайн"
            prio = 2
        else:
            fire_local = (deadline_local - timedelta(days=lead)).replace(
                hour=9, minute=0, second=0, microsecond=0
            )
            label = f"🎯 Дедлайн через {lead} дн."
            prio = 2 if lead == 1 else 1
        fire_utc = fire_local.astimezone(timezone.utc)
        if fire_utc <= now:
            continue  # цей етап уже минув
        text = f"{label}: {clean}"
        await db.add_reminder(
            message.from_user.id, text, fire_utc, "none", prio,
            user["def_count"], user["def_interval"],
        )
        created.append(fire_local)

    if not created:
        await message.answer(
            "⚠️ Ця дата вже надто близько або в минулому — нагадувань не створено.\n"
            "Спробуй дату в майбутньому.",
            reply_markup=main_menu(),
        )
        return

    lines = "\n".join(
        f"• {fmt_dt(d.astimezone(timezone.utc).isoformat(), tz_name)}" for d in created
    )
    await message.answer(
        f"🎯 <b>Дедлайн створено:</b> {clean}\n"
        f"📅 Кінцева дата: {fmt_dt(deadline_utc.isoformat(), tz_name)}\n\n"
        f"Нагадаю {len(created)} раз(и):\n{lines}",
        reply_markup=main_menu(),
    )
