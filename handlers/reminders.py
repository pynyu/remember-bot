"""Хендлери нагадувань: створення, перелік, налаштування, видалення, snooze."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

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
    fmt_interval,
    main_menu,
    paginated_kb,
    reminder_card,
)
from states import AddReminder
from utils.format import PRIORITY_LABEL, fmt_dt, human_left
from utils.timeparse import (
    REPEAT_LABELS,
    advance_until_future,
    extract_extras,
    parse_when,
)

router = Router()


async def build_reminder(user_id: int, text: str):
    """Створює нагадування з тексту. Повертає (текст_підтвердження, клавіатура)
    або None, якщо час розпізнати не вдалося. Не надсилає повідомлень сам —
    щоб логіку можна було перевикористати (вільний текст, шаблони тощо)."""
    user = await db.get_user(user_id)
    tz = user["tz"]
    parsed = parse_when(text, tz)
    if parsed is None:
        return None
    fire_at_utc, repeat, clean = parsed

    # необов'язкові «×N» та позначка важливості
    count, priority, clean = extract_extras(clean)
    notify_count = count if count is not None else user["def_count"]
    notify_interval = user["def_interval"]
    prio = priority if priority is not None else user["def_priority"]

    rid = await db.add_reminder(
        user_id, clean or "Нагадування", fire_at_utc,
        repeat, prio, notify_count, notify_interval,
    )
    r = await db.get_reminder(rid)

    repeat_note = "" if repeat == "none" else f"\n🔁 Повтор: {REPEAT_LABELS[repeat]}"
    ping_note = (
        f"\n🔔 Нагадаю {notify_count} раз(и) з інтервалом {fmt_interval(notify_interval)}"
        if notify_count > 1 else ""
    )
    confirm = (
        f"✅ Нагадаю: <b>{clean}</b>\n"
        f"🕒 {fmt_dt(fire_at_utc.isoformat(), tz)} ({human_left(fire_at_utc.isoformat(), tz)})"
        f"{repeat_note}{ping_note}\n\n"
        f"<i>Налаштуй кнопками нижче ⤵️</i>"
    )
    return confirm, reminder_card(r)


async def create_reminder_from_text(message: Message, text: str) -> bool:
    """Намагається створити нагадування з тексту. True, якщо вдалося."""
    result = await build_reminder(message.from_user.id, text)
    if result is None:
        return False
    confirm, kb = result
    await message.answer(confirm, reply_markup=kb)
    return True


@router.message(F.text == "➕ Нагадування")
async def add_reminder_start(message: Message, state: FSMContext) -> None:
    await state.set_state(AddReminder.waiting_text)
    await message.answer(
        "Напиши нагадування з часом, наприклад:\n"
        "<i>завтра о 9:00 зустріч з клієнтом</i>\n"
        "<i>через 2 години випити води ×3</i> (×3 = нагадати 3 рази)\n"
        "<i>щодня о 22:00 лягати спати</i>\n"
        "<i>о 18:00 подзвонити мамі важливо</i> (зі звуком)",
        reply_markup=cancel_kb(),
    )


@router.message(AddReminder.waiting_text)
async def add_reminder_text(message: Message, state: FSMContext) -> None:
    await db.ensure_user(message.from_user.id, message.from_user.username)
    ok = await create_reminder_from_text(message, message.text or "")
    if ok:
        await state.clear()
    else:
        await message.answer(
            "🤔 Не вдалося зрозуміти час. Спробуй ще раз, наприклад:\n"
            "<i>завтра о 15:00 …</i> або <i>через 30 хвилин …</i>",
            reply_markup=cancel_kb(),
        )


def _rem_preview(r, tz: str) -> str:
    prio = "🔴 " if r["priority"] == 2 else ("🔇 " if r["priority"] == 0 else "")
    rep = "🔁 " if r["repeat"] != "none" else ""
    text = (r["text"] or "").replace("\n", " ").strip() or "Нагадування"
    if len(text) > 24:
        text = text[:24] + "…"
    return f"{prio}{rep}{text} · {human_left(r['base_at'], tz)}"


async def _reminders_list(user_id: int, page: int):
    tz = await db.get_tz(user_id)
    rows = await db.list_reminders(user_id)
    items = [(r["id"], _rem_preview(r, tz)) for r in rows]
    kb = paginated_kb(
        items, page, "rem_open:", "rems_pg:",
        clear_cb="rems_clear" if items else None,
        clear_label="🗑 Видалити всі нагадування",
    )
    if rows:
        text = (
            f"⏰ <b>Активні нагадування ({len(rows)})</b>\n"
            "Натисни, щоб відкрити й налаштувати:"
        )
    else:
        text = ("У тебе немає активних нагадувань.\n"
                "Напиши, наприклад: <i>завтра о 9:00 зустріч</i>")
    return text, kb


@router.message(Command("reminders"))
@router.message(F.text == "⏰ Мої нагадування")
async def list_reminders(message: Message) -> None:
    await db.ensure_user(message.from_user.id, message.from_user.username)
    text, kb = await _reminders_list(message.from_user.id, 0)
    await message.answer(text, reply_markup=kb)


@router.callback_query(F.data.startswith("rems_pg:"))
async def cb_rems_page(call: CallbackQuery) -> None:
    page = int(call.data.split(":")[1])
    text, kb = await _reminders_list(call.from_user.id, page)
    try:
        await call.message.edit_text(text, reply_markup=kb)
    except Exception:
        pass
    await call.answer()


@router.callback_query(F.data.startswith("rem_open:"))
async def cb_rem_open(call: CallbackQuery) -> None:
    rid = int(call.data.split(":")[1])
    r = await db.get_reminder(rid)
    if not r or not r["active"]:
        await call.answer("Нагадування вже неактивне.", show_alert=True)
        return
    tz = await db.get_tz(call.from_user.id)
    repeat_note = "" if r["repeat"] == "none" else f" · 🔁 {REPEAT_LABELS[r['repeat']]}"
    prio = "🔴 " if r["priority"] == 2 else ("🔇 " if r["priority"] == 0 else "")
    await call.message.answer(
        f"{prio}<b>{r['text']}</b>\n"
        f"🕒 {fmt_dt(r['base_at'], tz)} ({human_left(r['base_at'], tz)}){repeat_note}",
        reply_markup=reminder_card(r),
    )
    await call.answer()


@router.callback_query(F.data == "rems_clear")
async def cb_rems_clear(call: CallbackQuery) -> None:
    from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✅ Так, видалити всі", callback_data="rems_clear_yes"),
        InlineKeyboardButton(text="↩️ Ні", callback_data="rems_pg:0"),
    ]])
    await call.message.edit_text(
        "⚠️ <b>Видалити ВСІ активні нагадування?</b>\nЦю дію не можна скасувати.",
        reply_markup=kb,
    )
    await call.answer()


@router.callback_query(F.data == "rems_clear_yes")
async def cb_rems_clear_yes(call: CallbackQuery) -> None:
    n = await db.delete_all_reminders(call.from_user.id)
    await call.message.edit_text(f"🗑 Видалено нагадувань: {n}.")
    await call.answer("Готово")


# ---------------------------------------------------- налаштування картки

async def _refresh_card(call: CallbackQuery, rid: int) -> None:
    r = await db.get_reminder(rid)
    if r:
        try:
            await call.message.edit_reply_markup(reply_markup=reminder_card(r))
        except Exception:
            pass


@router.callback_query(F.data.startswith("rcfg_count:"))
async def cb_cfg_count(call: CallbackQuery) -> None:
    rid = int(call.data.split(":")[1])
    r = await db.get_reminder(rid)
    if not r:
        await call.answer("Нагадування вже немає.", show_alert=True)
        return
    new = cycle(COUNT_OPTIONS, r["notify_count"])
    await db.set_config(rid, r["priority"], new, r["notify_interval"])
    await _refresh_card(call, rid)
    await call.answer(f"Повторів: {new}")


@router.callback_query(F.data.startswith("rcfg_int:"))
async def cb_cfg_int(call: CallbackQuery) -> None:
    rid = int(call.data.split(":")[1])
    r = await db.get_reminder(rid)
    if not r:
        await call.answer("Нагадування вже немає.", show_alert=True)
        return
    new = cycle(INTERVAL_OPTIONS, r["notify_interval"])
    await db.set_config(rid, r["priority"], r["notify_count"], new)
    await _refresh_card(call, rid)
    await call.answer(f"Інтервал: {fmt_interval(new)}")


@router.callback_query(F.data.startswith("rcfg_prio:"))
async def cb_cfg_prio(call: CallbackQuery) -> None:
    rid = int(call.data.split(":")[1])
    r = await db.get_reminder(rid)
    if not r:
        await call.answer("Нагадування вже немає.", show_alert=True)
        return
    new = cycle(PRIORITY_OPTIONS, r["priority"])
    await db.set_config(rid, new, r["notify_count"], r["notify_interval"])
    await _refresh_card(call, rid)
    await call.answer(PRIORITY_LABEL[new])


# ---------------------------------------------------- дії над нагадуванням

@router.callback_query(F.data.startswith("rem_del:"))
async def cb_delete_reminder(call: CallbackQuery) -> None:
    rid = int(call.data.split(":")[1])
    await db.delete_reminder(call.from_user.id, rid)
    await call.message.edit_text("🗑 Нагадування видалено.")
    await call.answer()


@router.callback_query(F.data.startswith("rem_done:"))
async def cb_done_reminder(call: CallbackQuery) -> None:
    rid = int(call.data.split(":")[1])
    r = await db.get_reminder(rid)
    await db.inc_done(call.from_user.id)
    first_line = (call.message.text or "Нагадування").split("\n")[0]

    if r and r["repeat"] != "none":
        # повторюване — переносимо на наступний період, зупиняємо поточні повтори
        tz = await db.get_tz(call.from_user.id)
        now = datetime.now(timezone.utc)
        base = datetime.fromisoformat(r["base_at"])
        new_base = advance_until_future(base, r["repeat"], tz, now)
        await db.set_cycle(rid, new_base, new_base, r["notify_count"])
        await call.message.edit_text(
            f"✅ Виконано! 🎉\nНаступне: {fmt_dt(new_base.isoformat(), tz)}"
        )
    else:
        await db.delete_reminder(call.from_user.id, rid)
        await call.message.edit_text(f"✅ {first_line}\n\nВиконано! 🎉")
    await call.answer("Молодець! 🎉")


@router.callback_query(F.data.startswith("snooze:"))
async def cb_snooze(call: CallbackQuery) -> None:
    _, rid_s, minutes_s = call.data.split(":")
    rid, minutes = int(rid_s), int(minutes_s)
    r = await db.get_reminder(rid)
    if r is None:
        await call.answer("Нагадування вже неактивне.", show_alert=True)
        return
    new_fire = datetime.now(timezone.utc) + timedelta(minutes=minutes)
    # перезапускаємо цикл сповіщень із новим часом
    await db.set_cycle(rid, new_fire, new_fire, r["notify_count"])
    tz = await db.get_tz(call.from_user.id)
    await call.message.edit_text(
        f"😴 Відкладено.\nНагадаю ще раз: {fmt_dt(new_fire.isoformat(), tz)}"
    )
    await call.answer("Відкладено 👌")
