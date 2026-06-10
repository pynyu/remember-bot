"""Хендлери нотаток: створення, перелік, редагування, пошук, видалення."""
from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

import database as db
from handlers.media import extract_media, send_note
from keyboards import cancel_kb, confirm_delete, main_menu, note_actions
from states import AddNote, EditNote, SearchNotes

router = Router()


def _format_note(text: str, pinned: bool) -> str:
    pin = "📌 " if pinned else ""
    return f"{pin}{text}"


@router.message(F.text == "📝 Нотатка")
async def add_note_start(message: Message, state: FSMContext) -> None:
    await state.set_state(AddNote.waiting_text)
    await message.answer(
        "Напиши текст нотатки (або надішли фото / голосове / файл):",
        reply_markup=cancel_kb(),
    )


@router.message(AddNote.waiting_text)
async def add_note_text(message: Message, state: FSMContext) -> None:
    await db.ensure_user(message.from_user.id, message.from_user.username)
    mt, fid = extract_media(message)
    text = message.text or message.caption or ""
    if not text and not fid:
        await message.answer("Порожньо 🤔 Надішли текст або вкладення.", reply_markup=cancel_kb())
        return
    await db.add_note(message.from_user.id, text, mt, fid)
    await state.clear()
    await message.answer("✅ Нотатку збережено.", reply_markup=main_menu())


@router.message(Command("notes"))
@router.message(F.text == "📒 Мої нотатки")
async def list_notes(message: Message) -> None:
    await db.ensure_user(message.from_user.id, message.from_user.username)
    rows = await db.list_notes(message.from_user.id)
    if not rows:
        await message.answer(
            "Нотаток поки немає. Напиши будь-який текст без часу — і я збережу його. "
            "Можна надсилати фото, голосові та файли.",
            reply_markup=main_menu(),
        )
        return
    await message.answer(f"📒 <b>Твої нотатки ({len(rows)}):</b>")
    for n in rows:
        await send_note(message, n, reply_markup=note_actions(n["id"], bool(n["pinned"])))


@router.message(F.text == "🔍 Пошук")
async def search_start(message: Message, state: FSMContext) -> None:
    await state.set_state(SearchNotes.waiting_query)
    await message.answer("Що шукаємо в нотатках?", reply_markup=cancel_kb())


@router.message(SearchNotes.waiting_query)
async def search_run(message: Message, state: FSMContext) -> None:
    await state.clear()
    rows = await db.search_notes(message.from_user.id, message.text or "")
    if not rows:
        await message.answer("Нічого не знайдено.", reply_markup=main_menu())
        return
    await message.answer(f"🔍 Знайдено: {len(rows)}", reply_markup=main_menu())
    for n in rows:
        await send_note(message, n, reply_markup=note_actions(n["id"], bool(n["pinned"])))


async def _safe_edit(call: CallbackQuery, text: str, markup=None) -> None:
    """Редагує підпис (для медіа) або текст повідомлення — що доступне."""
    try:
        await call.message.edit_text(text, reply_markup=markup)
    except Exception:
        try:
            await call.message.edit_caption(caption=text, reply_markup=markup)
        except Exception:
            try:
                await call.message.edit_reply_markup(reply_markup=markup)
            except Exception:
                pass


@router.callback_query(F.data.startswith("note_pin:"))
async def cb_pin(call: CallbackQuery) -> None:
    nid = int(call.data.split(":")[1])
    await db.toggle_pin(call.from_user.id, nid)
    n = await db.get_note(call.from_user.id, nid)
    if n:
        await _safe_edit(
            call,
            _format_note(n["text"], bool(n["pinned"])),
            note_actions(nid, bool(n["pinned"])),
        )
    await call.answer("Готово")


@router.callback_query(F.data.startswith("note_edit:"))
async def cb_edit(call: CallbackQuery, state: FSMContext) -> None:
    nid = int(call.data.split(":")[1])
    await state.set_state(EditNote.waiting_text)
    await state.update_data(note_id=nid)
    await call.message.answer("Надішли новий текст нотатки:", reply_markup=cancel_kb())
    await call.answer()


@router.message(EditNote.waiting_text)
async def edit_note_text(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    nid = data.get("note_id")
    await state.clear()
    if nid is None:
        await message.answer("Щось пішло не так. Спробуй ще раз.", reply_markup=main_menu())
        return
    await db.update_note(message.from_user.id, nid, message.text or "")
    await message.answer("✅ Нотатку оновлено.", reply_markup=main_menu())


@router.callback_query(F.data.startswith("note_del:"))
async def cb_del(call: CallbackQuery) -> None:
    nid = int(call.data.split(":")[1])
    await call.message.edit_reply_markup(reply_markup=confirm_delete("note", nid))
    await call.answer()


@router.callback_query(F.data.startswith("note_delyes:"))
async def cb_del_yes(call: CallbackQuery) -> None:
    nid = int(call.data.split(":")[1])
    await db.delete_note(call.from_user.id, nid)
    await _safe_edit(call, "🗑 Нотатку видалено.")
    await call.answer()


@router.callback_query(F.data.startswith("note_delno:"))
async def cb_del_no(call: CallbackQuery) -> None:
    nid = int(call.data.split(":")[1])
    n = await db.get_note(call.from_user.id, nid)
    if n:
        await call.message.edit_reply_markup(
            reply_markup=note_actions(nid, bool(n["pinned"]))
        )
    await call.answer("Скасовано")
