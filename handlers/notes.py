"""Хендлери нотаток: створення, перелік, редагування, пошук, видалення."""
from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

import database as db
from handlers.media import extract_media, send_note
from keyboards import (
    cancel_kb,
    confirm_delete,
    main_menu,
    note_actions,
    paginated_kb,
)
from states import AddNote, EditNote, SearchNotes
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

router = Router()

_MEDIA_ICON = {
    "photo": "🖼 ", "voice": "🎤 ", "document": "📎 ",
    "audio": "🎵 ", "video": "🎬 ", "video_note": "🎥 ",
}


def _format_note(text: str, pinned: bool) -> str:
    pin = "📌 " if pinned else ""
    return f"{pin}{text}"


def _preview(n) -> str:
    pin = "📌 " if n["pinned"] else ""
    media = _MEDIA_ICON.get(n["media_type"], "")
    text = (n["text"] or "").replace("\n", " ").strip() or "(вкладення)"
    if len(text) > 30:
        text = text[:30] + "…"
    return f"{pin}{media}{text}"


async def _notes_list(user_id: int, page: int):
    notes = await db.list_notes(user_id)
    rows = [(n["id"], _preview(n)) for n in notes]
    kb = paginated_kb(
        rows, page, "note_open:", "notes_pg:",
        clear_cb="notes_clear" if rows else None,
        clear_label="🗑 Видалити всі нотатки",
    )
    if notes:
        text = (
            f"📒 <b>Твої нотатки ({len(notes)})</b>\n"
            "Натисни нотатку, щоб відкрити її повністю:"
        )
    else:
        text = ("Нотаток поки немає. Надішли текст, фото, голосове чи файл — "
                "і я збережу його. ✨")
    return text, kb


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
    text, kb = await _notes_list(message.from_user.id, 0)
    await message.answer(text, reply_markup=kb)


@router.callback_query(F.data.startswith("notes_pg:"))
async def cb_notes_page(call: CallbackQuery) -> None:
    page = int(call.data.split(":")[1])
    text, kb = await _notes_list(call.from_user.id, page)
    try:
        await call.message.edit_text(text, reply_markup=kb)
    except Exception:
        pass
    await call.answer()


@router.callback_query(F.data.startswith("note_open:"))
async def cb_note_open(call: CallbackQuery) -> None:
    nid = int(call.data.split(":")[1])
    n = await db.get_note(call.from_user.id, nid)
    if not n:
        await call.answer("Нотатку не знайдено.", show_alert=True)
        return
    await send_note(call.message, n, reply_markup=note_actions(nid, bool(n["pinned"])))
    await call.answer()


@router.callback_query(F.data == "notes_clear")
async def cb_notes_clear(call: CallbackQuery) -> None:
    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✅ Так, видалити всі", callback_data="notes_clear_yes"),
        InlineKeyboardButton(text="↩️ Ні", callback_data="notes_pg:0"),
    ]])
    await call.message.edit_text(
        "⚠️ <b>Видалити ВСІ нотатки?</b>\nЦю дію не можна скасувати.",
        reply_markup=kb,
    )
    await call.answer()


@router.callback_query(F.data == "notes_clear_yes")
async def cb_notes_clear_yes(call: CallbackQuery) -> None:
    n = await db.delete_all_notes(call.from_user.id)
    await call.message.edit_text(f"🗑 Видалено нотаток: {n}.")
    await call.answer("Готово")


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
