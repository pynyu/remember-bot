"""Чеклісти — списки справ із галочками."""
from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

import database as db
from keyboards import checklist_kb, checklists_list_kb, done_kb, main_menu
from states import AddItem, NewChecklist

router = Router()


async def _render(checklist_id: int):
    items = await db.list_items(checklist_id)
    done = sum(1 for i in items if i["done"])
    return items, done


async def _checklist_text(checklist, items, done) -> str:
    total = len(items)
    bar = ""
    if total:
        filled = round(done / total * 10)
        bar = "▰" * filled + "▱" * (10 - filled) + f"  {done}/{total}"
    return f"📋 <b>{checklist['title']}</b>\n{bar}" if total else f"📋 <b>{checklist['title']}</b>\n<i>(порожній — додай пункти)</i>"


@router.message(Command("checklists"))
@router.message(F.text == "✅ Чеклісти")
async def show_checklists(message: Message) -> None:
    await db.ensure_user(message.from_user.id, message.from_user.username)
    rows = await db.list_checklists(message.from_user.id)
    if not rows:
        await message.answer(
            "✅ <b>Чеклісти</b>\n\nУ тебе ще немає списків. Створи перший!",
            reply_markup=checklists_list_kb([]),
        )
        return
    await message.answer(
        "✅ <b>Твої чеклісти</b>\nОбери, щоб відкрити:",
        reply_markup=checklists_list_kb(rows),
    )


@router.callback_query(F.data == "chk_new")
async def chk_new(call: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(NewChecklist.waiting_title)
    await call.message.answer(
        "Як назвемо чекліст? (напр. <i>Покупки</i> або <i>Збори у відрядження</i>)",
        reply_markup=done_kb(),
    )
    await call.answer()


@router.message(NewChecklist.waiting_title)
async def chk_title(message: Message, state: FSMContext) -> None:
    cid = await db.add_checklist(message.from_user.id, message.text or "Список")
    await state.set_state(NewChecklist.waiting_items)
    await state.update_data(checklist_id=cid)
    await message.answer(
        "Чудово! Тепер надсилай пункти — <b>по одному повідомленню</b>.\n"
        "Коли закінчиш — натисни «✔️ Готово».",
        reply_markup=done_kb(),
    )


@router.message(NewChecklist.waiting_items, F.text == "✔️ Готово")
async def chk_finish(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    cid = data["checklist_id"]
    await state.clear()
    checklist = await db.get_checklist(message.from_user.id, cid)
    items, done = await _render(cid)
    await message.answer("Готово! Ось твій чекліст 👇", reply_markup=main_menu())
    await message.answer(
        await _checklist_text(checklist, items, done),
        reply_markup=checklist_kb(cid, items),
    )


@router.message(NewChecklist.waiting_items)
async def chk_collect_item(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    cid = data["checklist_id"]
    await db.add_item(cid, message.text or "—")
    await message.answer("➕ Додав. Ще пункт або «✔️ Готово».", reply_markup=done_kb())


@router.callback_query(F.data.startswith("chk_open:"))
async def chk_open(call: CallbackQuery) -> None:
    cid = int(call.data.split(":")[1])
    checklist = await db.get_checklist(call.from_user.id, cid)
    if not checklist:
        await call.answer("Список не знайдено.", show_alert=True)
        return
    items, done = await _render(cid)
    await call.message.answer(
        await _checklist_text(checklist, items, done),
        reply_markup=checklist_kb(cid, items),
    )
    await call.answer()


@router.callback_query(F.data.startswith("chk_tog:"))
async def chk_toggle(call: CallbackQuery) -> None:
    item_id = int(call.data.split(":")[1])
    item = await db.get_item(item_id)
    if not item:
        await call.answer("Пункт зник.", show_alert=True)
        return
    await db.toggle_item(item_id)
    cid = item["checklist_id"]
    checklist = await db.get_checklist(call.from_user.id, cid)
    items, done = await _render(cid)
    try:
        await call.message.edit_text(
            await _checklist_text(checklist, items, done),
            reply_markup=checklist_kb(cid, items),
        )
    except Exception:
        pass
    await call.answer()


@router.callback_query(F.data.startswith("chk_add:"))
async def chk_add(call: CallbackQuery, state: FSMContext) -> None:
    cid = int(call.data.split(":")[1])
    await state.set_state(AddItem.waiting_text)
    await state.update_data(checklist_id=cid)
    await call.message.answer("Напиши новий пункт:", reply_markup=done_kb())
    await call.answer()


@router.message(AddItem.waiting_text, F.text == "✔️ Готово")
async def chk_add_done(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    cid = data["checklist_id"]
    await state.clear()
    checklist = await db.get_checklist(message.from_user.id, cid)
    items, done = await _render(cid)
    await message.answer("Оновлено 👇", reply_markup=main_menu())
    await message.answer(
        await _checklist_text(checklist, items, done),
        reply_markup=checklist_kb(cid, items),
    )


@router.message(AddItem.waiting_text)
async def chk_add_item(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    cid = data["checklist_id"]
    await db.add_item(cid, message.text or "—")
    await message.answer("➕ Додав. Ще пункт або «✔️ Готово».", reply_markup=done_kb())


@router.callback_query(F.data.startswith("chk_del:"))
async def chk_delete(call: CallbackQuery) -> None:
    cid = int(call.data.split(":")[1])
    await db.delete_checklist(call.from_user.id, cid)
    await call.message.edit_text("🗑 Чекліст видалено.")
    await call.answer()
