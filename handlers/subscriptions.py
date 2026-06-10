"""Підписки — облік платних сервісів, статистика та автонагадування."""
from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

import database as db
from keyboards import (
    REMIND_DAYS_OPTIONS,
    cancel_kb,
    cycle,
    main_menu,
    paginated_kb,
    sub_card_kb,
    sub_cycle_kb,
)
from states import AddSub, EditSub, TrialSub
from utils.subs import (
    CYCLE_LABELS,
    advance_date,
    compute_stats,
    days_until,
    fmt_amount,
    fmt_date,
    parse_amount,
    parse_date_only,
)

router = Router()

_CYCLE_SHORT = {"monthly": "/міс", "yearly": "/рік", "weekly": "/тижд"}


def _days_phrase(n: int) -> str:
    if n < 0:
        return f"прострочено на {abs(n)} дн"
    if n == 0:
        return "сьогодні"
    if n == 1:
        return "завтра"
    return f"через {n} дн"


def _sub_preview(s, tz: str) -> str:
    d = days_until(s["next_date"], tz)
    flame = "🔴 " if d <= 1 else ""
    return (
        f"{flame}{s['name']} · {fmt_amount(s['amount'], s['currency'])}"
        f"{_CYCLE_SHORT.get(s['cycle'], '')} · {_days_phrase(d)}"
    )


async def _subs_list(user_id: int, page: int):
    tz = await db.get_tz(user_id)
    subs = await db.list_subscriptions(user_id)
    items = [(s["id"], _sub_preview(s, tz)) for s in subs]
    kb = paginated_kb(
        items, page, "sub_open:", "subs_pg:",
        footer=[("➕ Додати підписку", "sub_new"), ("📊 Статистика", "subs_stats")],
    )
    if subs:
        text = (
            f"💳 <b>Твої підписки ({len(subs)})</b>\n"
            "Натисни, щоб переглянути й керувати:"
        )
    else:
        text = (
            "💳 <b>Підписки</b>\n\nТут можна вести всі платні сервіси, щоб не "
            "забувати оплачувати чи вчасно скасовувати пробний період.\n"
            "Я нагадаю заздалегідь. Додай першу 👇"
        )
    return text, kb


def _sub_card_text(s, tz: str) -> str:
    d = days_until(s["next_date"], tz)
    lines = [
        f"💳 <b>{s['name']}</b>",
        f"💵 {fmt_amount(s['amount'], s['currency'])} — {CYCLE_LABELS[s['cycle']]}",
        f"📆 Наступна оплата: {fmt_date(s['next_date'])} ({_days_phrase(d)})",
    ]
    if s["trial_end"]:
        td = days_until(s["trial_end"], tz)
        lines.append(f"🎁 Пробний до: {fmt_date(s['trial_end'])} ({_days_phrase(td)})")
    lines.append(f"🔔 Нагадаю за {s['remind_days']} дн до оплати")
    return "\n".join(lines)


# ----------------------------------------------------------------- list

@router.message(Command("subs"))
@router.message(Command("subscriptions"))
@router.message(F.text == "💳 Підписки")
async def show_subs(message: Message) -> None:
    await db.ensure_user(message.from_user.id, message.from_user.username)
    text, kb = await _subs_list(message.from_user.id, 0)
    await message.answer(text, reply_markup=kb)


@router.callback_query(F.data.startswith("subs_pg:"))
async def cb_subs_page(call: CallbackQuery) -> None:
    page = int(call.data.split(":")[1])
    text, kb = await _subs_list(call.from_user.id, page)
    try:
        await call.message.edit_text(text, reply_markup=kb)
    except Exception:
        pass
    await call.answer()


@router.callback_query(F.data.startswith("sub_open:"))
async def cb_sub_open(call: CallbackQuery) -> None:
    sid = int(call.data.split(":")[1])
    s = await db.get_subscription(call.from_user.id, sid)
    if not s:
        await call.answer("Підписку не знайдено.", show_alert=True)
        return
    tz = await db.get_tz(call.from_user.id)
    await call.message.answer(_sub_card_text(s, tz), reply_markup=sub_card_kb(s))
    await call.answer()


# --------------------------------------------------------------- stats

@router.callback_query(F.data == "subs_stats")
@router.message(Command("substats"))
async def show_stats(event) -> None:
    user_id = event.from_user.id
    answer = event.message.answer if isinstance(event, CallbackQuery) else event.answer
    tz = await db.get_tz(user_id)
    subs = await db.list_subscriptions(user_id)
    if not subs:
        await answer("💳 Підписок ще немає — нема що рахувати.")
        if isinstance(event, CallbackQuery):
            await event.answer()
        return
    stats = compute_stats(subs)
    lines = ["📊 <b>Статистика підписок</b>\n", f"Активних: <b>{len(subs)}</b>"]
    for curr, b in stats.items():
        monthly = b["monthly"]
        lines.append(
            f"\n💸 {curr}: <b>{fmt_amount(round(monthly, 2), curr)}</b>/міс  "
            f"≈ {fmt_amount(round(monthly * 12, 2), curr)}/рік"
        )
    upcoming = sorted(subs, key=lambda s: s["next_date"])[:5]
    lines.append("\n\n🔜 <b>Найближчі оплати:</b>")
    for s in upcoming:
        d = days_until(s["next_date"], tz)
        lines.append(
            f"• {s['name']} — {fmt_amount(s['amount'], s['currency'])} — "
            f"{fmt_date(s['next_date'])} ({_days_phrase(d)})"
        )
    await answer("\n".join(lines))
    if isinstance(event, CallbackQuery):
        await event.answer()


# ----------------------------------------------------------- add flow

@router.callback_query(F.data == "sub_new")
async def sub_new(call: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(AddSub.name)
    await call.message.answer(
        "💳 Як називається підписка? (напр. <i>Netflix</i>, <i>Spotify</i>, "
        "<i>ChatGPT Plus</i>)",
        reply_markup=cancel_kb(),
    )
    await call.answer()


@router.message(AddSub.name)
async def sub_name(message: Message, state: FSMContext) -> None:
    await state.update_data(name=(message.text or "Підписка").strip())
    await state.set_state(AddSub.amount)
    await message.answer(
        "Скільки коштує? Вкажи суму й валюту, напр.:\n"
        "<i>199 грн</i> · <i>9.99 USD</i> · <i>12 €</i>",
        reply_markup=cancel_kb(),
    )


@router.message(AddSub.amount)
async def sub_amount(message: Message, state: FSMContext) -> None:
    parsed = parse_amount(message.text or "")
    if parsed is None:
        await message.answer("🤔 Не зрозумів суму. Напр.: <i>199 грн</i>", reply_markup=cancel_kb())
        return
    amount, currency = parsed
    await state.update_data(amount=amount, currency=currency)
    await state.set_state(AddSub.cycle)
    await message.answer("Як часто списується?", reply_markup=sub_cycle_kb())


@router.callback_query(AddSub.cycle, F.data.startswith("sub_cycle:"))
async def sub_cycle(call: CallbackQuery, state: FSMContext) -> None:
    cyc = call.data.split(":")[1]
    await state.update_data(cycle=cyc)
    await state.set_state(AddSub.next_date)
    await call.message.answer(
        "Коли наступна оплата? Вкажи дату, напр.:\n"
        "<i>25.12</i> · <i>1.07.2026</i> · <i>через 14 днів</i> (для пробного періоду)",
        reply_markup=cancel_kb(),
    )
    await call.answer()


@router.message(AddSub.next_date)
async def sub_next_date(message: Message, state: FSMContext) -> None:
    tz = await db.get_tz(message.from_user.id)
    date_str = parse_date_only(message.text or "", tz)
    if date_str is None:
        await message.answer("🤔 Не побачив дати. Напр.: <i>25.12</i>", reply_markup=cancel_kb())
        return
    data = await state.get_data()
    await state.clear()
    sid = await db.add_subscription(
        message.from_user.id, data["name"], data["amount"], data["currency"],
        data["cycle"], date_str,
    )
    s = await db.get_subscription(message.from_user.id, sid)
    await message.answer("✅ Підписку додано!", reply_markup=main_menu())
    await message.answer(_sub_card_text(s, tz), reply_markup=sub_card_kb(s))


# --------------------------------------------------------- card actions

async def _refresh_card(call: CallbackQuery, sid: int) -> None:
    s = await db.get_subscription(call.from_user.id, sid)
    if not s:
        return
    tz = await db.get_tz(call.from_user.id)
    try:
        await call.message.edit_text(_sub_card_text(s, tz), reply_markup=sub_card_kb(s))
    except Exception:
        pass


@router.callback_query(F.data.startswith("sub_paid:"))
async def sub_paid(call: CallbackQuery) -> None:
    sid = int(call.data.split(":")[1])
    s = await db.get_subscription(call.from_user.id, sid)
    if not s:
        await call.answer("Підписку не знайдено.", show_alert=True)
        return
    new_date = advance_date(s["next_date"], s["cycle"])
    await db.update_subscription(sid, "next_date", new_date)
    await db.update_subscription(sid, "pay_reminded", "")
    await _refresh_card(call, sid)
    await call.answer(f"Оплачено ✅ Наступна: {fmt_date(new_date)}")


@router.callback_query(F.data.startswith("sub_remind:"))
async def sub_remind(call: CallbackQuery) -> None:
    sid = int(call.data.split(":")[1])
    s = await db.get_subscription(call.from_user.id, sid)
    if not s:
        await call.answer("Підписку не знайдено.", show_alert=True)
        return
    new = cycle(REMIND_DAYS_OPTIONS, s["remind_days"])
    await db.update_subscription(sid, "remind_days", new)
    await db.update_subscription(sid, "pay_reminded", "")
    await _refresh_card(call, sid)
    await call.answer(f"Нагадаю за {new} дн")


@router.callback_query(F.data.startswith("sub_del:"))
async def sub_del(call: CallbackQuery) -> None:
    sid = int(call.data.split(":")[1])
    await db.delete_subscription(call.from_user.id, sid)
    await call.message.edit_text("🗑 Підписку видалено.")
    await call.answer()


@router.callback_query(F.data.startswith("sub_trial:"))
async def sub_trial(call: CallbackQuery, state: FSMContext) -> None:
    sid = int(call.data.split(":")[1])
    s = await db.get_subscription(call.from_user.id, sid)
    if not s:
        await call.answer("Підписку не знайдено.", show_alert=True)
        return
    if s["trial_end"]:
        await db.update_subscription(sid, "trial_end", None)
        await db.update_subscription(sid, "trial_reminded", 0)
        await _refresh_card(call, sid)
        await call.answer("Пробний період прибрано")
        return
    await state.set_state(TrialSub.waiting_date)
    await state.update_data(sub_id=sid)
    await call.message.answer(
        "🎁 Коли закінчується пробний період? Вкажи дату (<i>25.12</i> або "
        "<i>через 7 днів</i>) — нагадаю за день до кінця.",
        reply_markup=cancel_kb(),
    )
    await call.answer()


@router.message(TrialSub.waiting_date)
async def sub_trial_date(message: Message, state: FSMContext) -> None:
    tz = await db.get_tz(message.from_user.id)
    date_str = parse_date_only(message.text or "", tz)
    if date_str is None:
        await message.answer("🤔 Не побачив дати. Напр.: <i>через 7 днів</i>", reply_markup=cancel_kb())
        return
    data = await state.get_data()
    sid = data["sub_id"]
    await state.clear()
    await db.update_subscription(sid, "trial_end", date_str)
    await db.update_subscription(sid, "trial_reminded", 0)
    s = await db.get_subscription(message.from_user.id, sid)
    await message.answer("🎁 Пробний період додано!", reply_markup=main_menu())
    await message.answer(_sub_card_text(s, tz), reply_markup=sub_card_kb(s))


# ------------------------------------------------------------ edit name/amount

@router.callback_query(F.data.startswith("sub_edit:"))
async def sub_edit(call: CallbackQuery, state: FSMContext) -> None:
    _, sid_s, field = call.data.split(":")
    await state.set_state(EditSub.waiting_value)
    await state.update_data(sub_id=int(sid_s), field=field)
    prompt = "Нову назву:" if field == "name" else "Нову суму (напр. <i>249 грн</i>):"
    await call.message.answer(prompt, reply_markup=cancel_kb())
    await call.answer()


@router.message(EditSub.waiting_value)
async def sub_edit_save(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    sid, field = data["sub_id"], data["field"]
    tz = await db.get_tz(message.from_user.id)
    if field == "amount":
        parsed = parse_amount(message.text or "")
        if parsed is None:
            await message.answer("🤔 Не зрозумів суму.", reply_markup=cancel_kb())
            return
        amount, currency = parsed
        await db.update_subscription(sid, "amount", amount)
        await db.update_subscription(sid, "currency", currency)
    else:
        await db.update_subscription(sid, "name", (message.text or "").strip())
    await state.clear()
    s = await db.get_subscription(message.from_user.id, sid)
    await message.answer("✅ Оновлено.", reply_markup=main_menu())
    await message.answer(_sub_card_text(s, tz), reply_markup=sub_card_kb(s))
