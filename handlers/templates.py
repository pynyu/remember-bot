"""Шаблони нагадувань — збережені типові фрази, які можна швидко повторювати."""
from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

import database as db
from handlers.reminders import build_reminder
from keyboards import cancel_kb, main_menu, template_kb
from states import NewTemplate

router = Router()


@router.message(Command("templates"))
@router.message(F.text == "⭐ Шаблони")
async def show_templates(message: Message) -> None:
    await db.ensure_user(message.from_user.id, message.from_user.username)
    rows = await db.list_templates(message.from_user.id)
    kb = InlineKeyboardBuilder()
    kb.button(text="➕ Новий шаблон", callback_data="tpl_new")
    if not rows:
        await message.answer(
            "⭐ <b>Шаблони</b>\n\nЗбережи фрази, які часто повторюєш, напр.:\n"
            "<i>щодня о 8:00 прийняти вітаміни</i>\n"
            "Потім одним дотиком створюватимеш із них нагадування.",
            reply_markup=kb.as_markup(),
        )
        return
    await message.answer("⭐ <b>Твої шаблони:</b>", reply_markup=kb.as_markup())
    for t in rows:
        await message.answer(f"📌 {t['phrase']}", reply_markup=template_kb(t["id"]))


@router.callback_query(F.data == "tpl_new")
async def tpl_new(call: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(NewTemplate.waiting_phrase)
    await call.message.answer(
        "Напиши фразу-шаблон так само, як писав би нагадування з часом:\n"
        "<i>щотижня у понеділок о 9:00 планерка</i>",
        reply_markup=cancel_kb(),
    )
    await call.answer()


@router.message(NewTemplate.waiting_phrase)
async def tpl_save(message: Message, state: FSMContext) -> None:
    await state.clear()
    await db.add_template(message.from_user.id, message.text or "")
    await message.answer("⭐ Шаблон збережено!", reply_markup=main_menu())


@router.callback_query(F.data.startswith("tpl_use:"))
async def tpl_use(call: CallbackQuery) -> None:
    tid = int(call.data.split(":")[1])
    t = await db.get_template(call.from_user.id, tid)
    if not t:
        await call.answer("Шаблон не знайдено.", show_alert=True)
        return
    await db.ensure_user(call.from_user.id, call.from_user.username)
    result = await build_reminder(call.from_user.id, t["phrase"])
    if result is None:
        await call.answer("У шаблоні немає часу — додай, напр. «о 9:00».", show_alert=True)
        return
    confirm, kb = result
    await call.message.answer(confirm, reply_markup=kb)
    await call.answer("Нагадування створено ✅")


@router.callback_query(F.data.startswith("tpl_del:"))
async def tpl_del(call: CallbackQuery) -> None:
    tid = int(call.data.split(":")[1])
    await db.delete_template(call.from_user.id, tid)
    await call.message.edit_text("🗑 Шаблон видалено.")
    await call.answer()
