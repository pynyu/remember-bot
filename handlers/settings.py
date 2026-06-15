"""Налаштування користувача: типові повтори/звук та часовий пояс."""
from __future__ import annotations

from zoneinfo import available_timezones

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

import database as db
from keyboards import (
    COUNT_OPTIONS,
    INTERVAL_OPTIONS,
    PRIORITY_OPTIONS,
    cancel_kb,
    cycle,
    digest_kb,
    fmt_interval,
    main_menu,
    settings_kb,
    tz_kb,
)

DIGEST_TIMES = ["06:30", "07:00", "08:00", "09:00", "10:00", "21:00"]
EVENING_HOURS = [18, 19, 20, 21, 22]
MORNING_HOURS = [6, 7, 8, 9, 10]
from states import SetTimezone
from utils.format import PRIORITY_LABEL

router = Router()

POPULAR_TZ = [
    "Europe/Kyiv",
    "Europe/Warsaw",
    "Europe/Berlin",
    "Europe/London",
    "Europe/Lisbon",
    "America/New_York",
    "Asia/Dubai",
    "Asia/Tokyo",
]

SETTINGS_HEADER = (
    "⚙️ <b>Налаштування</b>\n\n"
    "Значення за замовчуванням для <b>нових</b> нагадувань. Кожне окреме "
    "нагадування можна підлаштувати кнопками під ним.\n\n"
    "• <b>Повторів / інтервал</b> — скільки разів і як часто пінгувати, поки не "
    "натиснеш «Готово» (рятує, коли телефон беззвучний).\n"
    "• <b>Звук</b> — 🔔 зі звуком / 🔇 тихо / 🔴 важливо.\n"
    "• <b>Авто-попередження</b> — до кожного нового нагадування з часом автоматично "
    "додавати нагадування <b>напередодні ввечері</b> та <b>зранку</b>, щоб не "
    "проспати подію.\n"
    "• <b>Вечірнє / ранкове</b> — о котрій годині надсилати ці попередження."
)


async def _show_settings(message_or_call, user) -> None:
    if isinstance(message_or_call, CallbackQuery):
        await message_or_call.message.edit_text(
            SETTINGS_HEADER, reply_markup=settings_kb(user)
        )
    else:
        await message_or_call.answer(SETTINGS_HEADER, reply_markup=settings_kb(user))


@router.message(Command("settings"))
@router.message(F.text == "⚙️ Налаштування")
async def settings_menu(message: Message) -> None:
    await db.ensure_user(message.from_user.id, message.from_user.username)
    user = await db.get_user(message.from_user.id)
    await message.answer(SETTINGS_HEADER, reply_markup=settings_kb(user))


@router.callback_query(F.data == "scfg_count")
async def cb_def_count(call: CallbackQuery) -> None:
    user = await db.get_user(call.from_user.id)
    new = cycle(COUNT_OPTIONS, user["def_count"])
    await db.set_user_default(call.from_user.id, "def_count", new)
    await _show_settings(call, await db.get_user(call.from_user.id))
    await call.answer(f"Повторів: {new}")


@router.callback_query(F.data == "scfg_int")
async def cb_def_int(call: CallbackQuery) -> None:
    user = await db.get_user(call.from_user.id)
    new = cycle(INTERVAL_OPTIONS, user["def_interval"])
    await db.set_user_default(call.from_user.id, "def_interval", new)
    await _show_settings(call, await db.get_user(call.from_user.id))
    await call.answer(f"Інтервал: {fmt_interval(new)}")


@router.callback_query(F.data == "scfg_prio")
async def cb_def_prio(call: CallbackQuery) -> None:
    user = await db.get_user(call.from_user.id)
    new = cycle(PRIORITY_OPTIONS, user["def_priority"])
    await db.set_user_default(call.from_user.id, "def_priority", new)
    await _show_settings(call, await db.get_user(call.from_user.id))
    await call.answer(PRIORITY_LABEL[new])


@router.callback_query(F.data == "scfg_auto")
async def cb_auto(call: CallbackQuery) -> None:
    user = await db.get_user(call.from_user.id)
    await db.set_user_default(call.from_user.id, "auto_advance", 0 if user["auto_advance"] else 1)
    await _show_settings(call, await db.get_user(call.from_user.id))
    await call.answer()


@router.callback_query(F.data == "scfg_evening")
async def cb_evening(call: CallbackQuery) -> None:
    user = await db.get_user(call.from_user.id)
    new = cycle(EVENING_HOURS, user["evening_hour"])
    await db.set_user_default(call.from_user.id, "evening_hour", new)
    await _show_settings(call, await db.get_user(call.from_user.id))
    await call.answer(f"Вечірнє о {new:02d}:00")


@router.callback_query(F.data == "scfg_morning")
async def cb_morning(call: CallbackQuery) -> None:
    user = await db.get_user(call.from_user.id)
    new = cycle(MORNING_HOURS, user["morning_hour"])
    await db.set_user_default(call.from_user.id, "morning_hour", new)
    await _show_settings(call, await db.get_user(call.from_user.id))
    await call.answer(f"Ранкове о {new:02d}:00")


@router.callback_query(F.data == "scfg_digest")
async def cb_digest_menu(call: CallbackQuery) -> None:
    await call.message.edit_text(
        "🌅 <b>Ранковий дайджест</b>\n\n"
        "Щодня в обраний час я надсилатиму список справ і нагадувань на день.\n"
        "Обери час (за твоїм часовим поясом) або вимкни:",
        reply_markup=digest_kb(DIGEST_TIMES),
    )
    await call.answer()


@router.callback_query(F.data.startswith("digest_set:"))
async def cb_digest_set(call: CallbackQuery) -> None:
    val = call.data.split(":", 1)[1]
    if val == "off":
        await db.set_digest_time(call.from_user.id, None)
        msg = "🚫 Дайджест вимкнено."
    else:
        await db.set_digest_time(call.from_user.id, val)
        await db.set_digest_last(call.from_user.id, "")  # дозволити сьогодні
        msg = f"✅ Дайджест щодня о {val}."
    user = await db.get_user(call.from_user.id)
    await call.message.edit_text(
        f"{msg}\n\n" + SETTINGS_HEADER, reply_markup=settings_kb(user)
    )
    await call.answer()


@router.callback_query(F.data == "scfg_tz")
async def cb_tz_menu(call: CallbackQuery) -> None:
    user = await db.get_user(call.from_user.id)
    await call.message.edit_text(
        f"🌍 Поточний часовий пояс: <b>{user['tz']}</b>\n\n"
        "Обери зі списку або натисни /settz, щоб ввести свій.",
        reply_markup=tz_kb(POPULAR_TZ),
    )
    await call.answer()


@router.callback_query(F.data.startswith("tz:"))
async def cb_set_tz(call: CallbackQuery) -> None:
    tz = call.data.split(":", 1)[1]
    await db.set_tz(call.from_user.id, tz)
    await call.message.edit_text(f"✅ Часовий пояс встановлено: <b>{tz}</b>")
    await call.answer("Збережено")


# Команда /tz — швидкий доступ до вибору поясу
@router.message(Command("tz"))
async def cmd_tz(message: Message) -> None:
    await db.ensure_user(message.from_user.id, message.from_user.username)
    user = await db.get_user(message.from_user.id)
    await message.answer(
        f"🌍 Поточний часовий пояс: <b>{user['tz']}</b>\n\nОбери зі списку:",
        reply_markup=tz_kb(POPULAR_TZ),
    )


@router.message(Command("settz"))
async def settz_start(message: Message, state: FSMContext) -> None:
    await state.set_state(SetTimezone.waiting_tz)
    await message.answer(
        "Введи назву часового поясу у форматі IANA, наприклад:\n"
        "<i>Europe/Kyiv</i>, <i>Asia/Tokyo</i>, <i>America/Los_Angeles</i>",
        reply_markup=cancel_kb(),
    )


@router.message(SetTimezone.waiting_tz)
async def settz_save(message: Message, state: FSMContext) -> None:
    tz = (message.text or "").strip()
    if tz not in available_timezones():
        await message.answer(
            "❌ Невідомий часовий пояс. Перевір написання, напр. <i>Europe/Kyiv</i>.",
            reply_markup=cancel_kb(),
        )
        return
    await db.set_tz(message.from_user.id, tz)
    await state.clear()
    await message.answer(f"✅ Часовий пояс встановлено: <b>{tz}</b>", reply_markup=main_menu())
