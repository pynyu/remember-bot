"""Загальні команди: /start, /help, /stats, «на сьогодні», скасування."""
from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

import database as db
from keyboards import main_menu, reminder_card
from utils.format import fmt_dt, human_left
from utils.timeparse import REPEAT_LABELS

router = Router()

HELP_TEXT = (
    "🤖 <b>Бот нагадувань і нотаток</b>\n\n"
    "<b>Як створити нагадування</b>\n"
    "Просто напиши, що і коли — я розумію природну мову:\n"
    "• <i>через 30 хвилин подзвонити мамі</i>\n"
    "• <i>завтра о 9:00 зустріч</i>\n"
    "• <i>сьогодні о 18:30 тренування</i>\n"
    "• <i>25.12 о 10:00 купити подарунки</i>\n"
    "• <i>у пʼятницю о 17:00 здати звіт</i>\n\n"
    "<b>Повторювані</b>\n"
    "• <i>щодня о 8:00 зарядка</i>\n"
    "• <i>по буднях о 9:00 планерка</i>\n"
    "• <i>щотижня у понеділок о 10:00 прибирання</i>\n"
    "• <i>щомісяця 1 числа сплатити оренду</i>\n\n"
    "<b>🔔 Щоб не пропустити (телефон беззвучний)</b>\n"
    "Я можу нагадати <b>кілька разів</b> поспіль, поки не натиснеш «✅ Готово».\n"
    "• додай <i>×3</i> у кінці — нагадаю 3 рази\n"
    "• напиши <i>важливо</i> — сповіщення зі звуком\n"
    "• або задай це під кожним нагадуванням / у ⚙️ Налаштуваннях\n"
    "<i>⚠️ Бот не може ввімкнути звук, якщо на iPhone стоїть беззвучний режим. "
    "Тому: відкрий чат із ботом → назва зверху → Notifications → ввімкни звук "
    "і прибери Mute. Повтори сповіщень підстрахують навіть на вібрації.</i>\n\n"
    "<b>Нотатки, фото, голос</b>\n"
    "Текст без часу збережу як нотатку. Можна надсилати <b>фото, голосові, файли</b> "
    "або <b>пересилати</b> будь-яке повідомлення — все потрапить у нотатки.\n\n"
    "<b>Ще можливості</b>\n"
    "• ✅ <b>Чеклісти</b> — списки справ із галочками\n"
    "• 🎯 <b>Дедлайн</b> — нагадаю за тиждень / 3 дні / день / у день\n"
    "• ⭐ <b>Шаблони</b> — збережені фрази для швидких нагадувань\n"
    "• 🌅 <b>Ранковий дайджест</b> — план на день щоранку (у ⚙️ Налаштуваннях)\n\n"
    "<b>Команди</b>\n"
    "/start — меню · /help — довідка\n"
    "/reminders · /notes · /checklists · /templates\n"
    "/deadline · /today · /stats\n"
    "/settings — налаштування · /tz — часовий пояс\n"
)


@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext) -> None:
    await state.clear()
    await db.ensure_user(message.from_user.id, message.from_user.username)
    await message.answer(
        f"Привіт, {message.from_user.first_name}! 👋\n\n"
        "Я бот для нагадувань і нотаток. Напиши, про що тобі нагадати, "
        "наприклад:\n<i>завтра о 9:00 зустріч</i>\n\n"
        "Можу нагадати кілька разів, щоб ти не пропустив. Натисни /help для деталей.",
        reply_markup=main_menu(),
    )


@router.message(Command("help"))
@router.message(F.text == "❓ Допомога")
async def cmd_help(message: Message) -> None:
    await message.answer(HELP_TEXT, reply_markup=main_menu())


@router.message(Command("today"))
@router.message(F.text == "📅 На сьогодні")
async def cmd_today(message: Message) -> None:
    await db.ensure_user(message.from_user.id, message.from_user.username)
    tz_name = await db.get_tz(message.from_user.id)
    tz = ZoneInfo(tz_name)
    now = datetime.now(tz)
    end = now.replace(hour=23, minute=59, second=59)
    rows = await db.list_reminders(message.from_user.id)
    today = [
        r for r in rows
        if datetime.fromisoformat(r["base_at"]).astimezone(tz) <= end
    ]
    if not today:
        await message.answer(
            "📅 На сьогодні активних нагадувань немає. Гарного дня! ☀️",
            reply_markup=main_menu(),
        )
        return
    await message.answer(f"📅 <b>Справи на сьогодні ({len(today)}):</b>")
    for r in today:
        repeat_note = "" if r["repeat"] == "none" else f" · 🔁 {REPEAT_LABELS[r['repeat']]}"
        prio = "🔴 " if r["priority"] == 2 else ""
        await message.answer(
            f"{prio}<b>{r['text']}</b>\n"
            f"🕒 {fmt_dt(r['base_at'], tz_name)} ({human_left(r['base_at'], tz_name)}){repeat_note}",
            reply_markup=reminder_card(r),
        )


@router.message(Command("stats"))
@router.message(F.text == "📊 Статистика")
async def cmd_stats(message: Message) -> None:
    await db.ensure_user(message.from_user.id, message.from_user.username)
    user = await db.get_user(message.from_user.id)
    active = await db.count_active_reminders(message.from_user.id)
    notes = await db.count_notes(message.from_user.id)
    await message.answer(
        "📊 <b>Твоя статистика</b>\n\n"
        f"⏰ Активних нагадувань: <b>{active}</b>\n"
        f"✅ Виконано нагадувань: <b>{user['done_count']}</b>\n"
        f"📝 Нотаток: <b>{notes}</b>\n",
        reply_markup=main_menu(),
    )


@router.message(F.text == "↩️ Скасувати")
@router.message(Command("cancel"))
async def cmd_cancel(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("Скасовано.", reply_markup=main_menu())
