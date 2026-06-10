"""Розумна обробка вільного тексту поза станами.

Логіка: якщо в повідомленні вдається розпізнати час — створюємо нагадування.
Якщо часу немає — зберігаємо текст як нотатку. Так користувач може просто
писати боту що завгодно, не натискаючи кнопок.
"""
from __future__ import annotations

from aiogram import F, Router
from aiogram.types import Message

import database as db
from handlers.reminders import create_reminder_from_text
from keyboards import note_actions

router = Router()


@router.message(F.text & ~F.text.startswith("/"))
async def smart_text(message: Message) -> None:
    await db.ensure_user(message.from_user.id, message.from_user.username)
    text = message.text or ""

    # спершу пробуємо як нагадування
    if await create_reminder_from_text(message, text):
        return

    # інакше — зберігаємо як нотатку
    nid = await db.add_note(message.from_user.id, text)
    await message.answer(
        "📝 Часу не знайшов, тож зберіг як нотатку.\n"
        "<i>Підказка: додай час (напр. «завтра о 9:00»), щоб зробити нагадування.</i>",
        reply_markup=note_actions(nid, False),
    )
