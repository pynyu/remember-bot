"""Медіа та пересилання: фото/голос/файл → нотатка, форвард → нотатка."""
from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import StateFilter
from aiogram.types import Message

import database as db
from keyboards import note_actions

router = Router()


def extract_media(message: Message) -> tuple[str | None, str | None]:
    """Повертає (media_type, file_id) або (None, None), якщо вкладень немає."""
    if message.photo:
        return "photo", message.photo[-1].file_id
    if message.voice:
        return "voice", message.voice.file_id
    if message.audio:
        return "audio", message.audio.file_id
    if message.document:
        return "document", message.document.file_id
    if message.video:
        return "video", message.video.file_id
    if message.video_note:
        return "video_note", message.video_note.file_id
    return None, None


async def send_note(message: Message, note, reply_markup=None) -> None:
    """Надсилає нотатку з урахуванням вкладення (для перегляду/пошуку)."""
    pin = "📌 " if note["pinned"] else ""
    text = f"{pin}{note['text']}".strip() or pin or " "
    mt, fid = note["media_type"], note["file_id"]
    if mt == "photo":
        await message.answer_photo(fid, caption=text, reply_markup=reply_markup)
    elif mt == "voice":
        await message.answer_voice(fid, caption=text, reply_markup=reply_markup)
    elif mt == "audio":
        await message.answer_audio(fid, caption=text, reply_markup=reply_markup)
    elif mt == "video":
        await message.answer_video(fid, caption=text, reply_markup=reply_markup)
    elif mt == "document":
        await message.answer_document(fid, caption=text, reply_markup=reply_markup)
    elif mt == "video_note":
        await message.answer_video_note(fid)
        await message.answer(text or "🎥 Відеоповідомлення", reply_markup=reply_markup)
    else:
        await message.answer(text, reply_markup=reply_markup)


def _is_forwarded(message: Message) -> bool:
    return getattr(message, "forward_origin", None) is not None or \
        getattr(message, "forward_date", None) is not None


@router.message(StateFilter(None), F.forward_date)
async def forwarded_to_note(message: Message) -> None:
    """Будь-яке переслане повідомлення зберігаємо як нотатку."""
    await db.ensure_user(message.from_user.id, message.from_user.username)
    text = message.text or message.caption or ""
    mt, fid = extract_media(message)
    if not text and not fid:
        return
    nid = await db.add_note(
        message.from_user.id, text or "(переслане повідомлення)", mt, fid
    )
    note = await db.get_note(message.from_user.id, nid)
    await message.answer("📥 Збережено в нотатки з пересланого 👇")
    await send_note(message, note, reply_markup=note_actions(nid, False))


@router.message(
    StateFilter(None),
    F.photo | F.voice | F.audio | F.document | F.video | F.video_note,
)
async def media_to_note(message: Message) -> None:
    """Надіслане фото/голос/файл поза діалогом — зберігаємо як нотатку."""
    await db.ensure_user(message.from_user.id, message.from_user.username)
    mt, fid = extract_media(message)
    if not fid:
        return
    text = message.caption or ""
    nid = await db.add_note(message.from_user.id, text, mt, fid)
    note = await db.get_note(message.from_user.id, nid)
    kind = {"voice": "🎤 Голосову", "photo": "🖼 Фото", "document": "📎 Файл"}.get(mt, "Вкладення")
    await message.answer(f"{kind} збережено в нотатки 👇")
    await send_note(message, note, reply_markup=note_actions(nid, False))
