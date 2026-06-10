"""Inline- та reply-клавіатури."""
from __future__ import annotations

from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder

from utils.format import PRIORITY_LABEL

# Допустимі значення для кнопок-перемикачів
COUNT_OPTIONS = [1, 2, 3, 5, 10]
INTERVAL_OPTIONS = [1, 2, 3, 5, 10, 15, 30, 60]
PRIORITY_OPTIONS = [0, 1, 2]
REMIND_DAYS_OPTIONS = [1, 2, 3, 5, 7, 14]
PAGE_SIZE = 8


def paginated_kb(
    rows: list[tuple[int, str]], page: int, open_prefix: str, page_prefix: str,
    clear_cb: str | None = None, clear_label: str | None = None,
    footer: list[tuple[str, str]] | None = None,
) -> InlineKeyboardMarkup:
    """Загальний список з пагінацією. rows = [(id, підпис), ...]."""
    pages = max(1, (len(rows) + PAGE_SIZE - 1) // PAGE_SIZE)
    page = max(0, min(page, pages - 1))
    chunk = rows[page * PAGE_SIZE:(page + 1) * PAGE_SIZE]
    kb_rows: list[list[InlineKeyboardButton]] = [
        [InlineKeyboardButton(text=label, callback_data=f"{open_prefix}{iid}")]
        for iid, label in chunk
    ]
    nav: list[InlineKeyboardButton] = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="◀️", callback_data=f"{page_prefix}{page - 1}"))
    if pages > 1:
        nav.append(InlineKeyboardButton(text=f"{page + 1}/{pages}", callback_data="noop"))
    if page < pages - 1:
        nav.append(InlineKeyboardButton(text="▶️", callback_data=f"{page_prefix}{page + 1}"))
    if nav:
        kb_rows.append(nav)
    for text, cb in (footer or []):
        kb_rows.append([InlineKeyboardButton(text=text, callback_data=cb)])
    if clear_cb:
        kb_rows.append([InlineKeyboardButton(text=clear_label, callback_data=clear_cb)])
    return InlineKeyboardMarkup(inline_keyboard=kb_rows)


def cycle(options: list[int], current: int) -> int:
    """Наступне значення у списку (по колу)."""
    try:
        i = options.index(current)
    except ValueError:
        return options[0]
    return options[(i + 1) % len(options)]


def fmt_interval(minutes: int) -> str:
    if minutes >= 60 and minutes % 60 == 0:
        return f"{minutes // 60} год"
    return f"{minutes} хв"


def main_menu() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="➕ Нагадування"), KeyboardButton(text="📝 Нотатка")],
            [KeyboardButton(text="⏰ Мої нагадування"), KeyboardButton(text="📒 Мої нотатки")],
            [KeyboardButton(text="💳 Підписки"), KeyboardButton(text="✅ Чеклісти")],
            [KeyboardButton(text="🎯 Дедлайн"), KeyboardButton(text="⭐ Шаблони")],
            [KeyboardButton(text="📅 На сьогодні"), KeyboardButton(text="🔍 Пошук")],
            [KeyboardButton(text="📊 Статистика"), KeyboardButton(text="⚙️ Налаштування")],
            [KeyboardButton(text="❓ Допомога")],
        ],
        resize_keyboard=True,
        input_field_placeholder="Напиши нагадування, нотатку або надішли фото/голос…",
    )


def reminder_card(reminder) -> InlineKeyboardMarkup:
    """Кнопки під карткою нагадування: налаштування повторів/звуку + видалення."""
    rid = reminder["id"]
    kb = InlineKeyboardBuilder()
    kb.button(
        text=f"🔁 Повторів: {reminder['notify_count']}",
        callback_data=f"rcfg_count:{rid}",
    )
    kb.button(
        text=f"⏱ Інтервал: {fmt_interval(reminder['notify_interval'])}",
        callback_data=f"rcfg_int:{rid}",
    )
    kb.button(
        text=PRIORITY_LABEL[reminder["priority"]],
        callback_data=f"rcfg_prio:{rid}",
    )
    kb.button(text="🗑 Видалити", callback_data=f"rem_del:{rid}")
    kb.adjust(2, 2)
    return kb.as_markup()


def fired_actions(reminder_id: int) -> InlineKeyboardMarkup:
    """Кнопки під сповіщенням, що спрацювало."""
    kb = InlineKeyboardBuilder()
    kb.button(text="✅ Готово", callback_data=f"rem_done:{reminder_id}")
    kb.button(text="😴 +10 хв", callback_data=f"snooze:{reminder_id}:10")
    kb.button(text="😴 +1 год", callback_data=f"snooze:{reminder_id}:60")
    kb.button(text="😴 Завтра", callback_data=f"snooze:{reminder_id}:1440")
    kb.adjust(1, 3)
    return kb.as_markup()


def note_actions(note_id: int, pinned: bool) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="✏️ Редагувати", callback_data=f"note_edit:{note_id}")
    kb.button(
        text="📌 Відкріпити" if pinned else "📌 Закріпити",
        callback_data=f"note_pin:{note_id}",
    )
    kb.button(text="🗑 Видалити", callback_data=f"note_del:{note_id}")
    kb.adjust(2, 1)
    return kb.as_markup()


def confirm_delete(kind: str, item_id: int) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="✅ Так, видалити", callback_data=f"{kind}_delyes:{item_id}")
    kb.button(text="↩️ Скасувати", callback_data=f"{kind}_delno:{item_id}")
    return kb.as_markup()


def settings_kb(user) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(
        text=f"🔁 Повторів за замовч.: {user['def_count']}",
        callback_data="scfg_count",
    )
    kb.button(
        text=f"⏱ Інтервал за замовч.: {fmt_interval(user['def_interval'])}",
        callback_data="scfg_int",
    )
    kb.button(
        text=f"Звук за замовч.: {PRIORITY_LABEL[user['def_priority']]}",
        callback_data="scfg_prio",
    )
    digest = user["digest_time"] if user["digest_time"] else "вимк."
    kb.button(text=f"🌅 Ранковий дайджест: {digest}", callback_data="scfg_digest")
    kb.button(text="🌍 Часовий пояс", callback_data="scfg_tz")
    kb.adjust(1, 1, 1, 1, 1)
    return kb.as_markup()


def checklist_kb(checklist_id: int, items) -> InlineKeyboardMarkup:
    """Кожен пункт — кнопка-перемикач ✅/⬜, плюс керування."""
    kb = InlineKeyboardBuilder()
    for it in items:
        mark = "✅" if it["done"] else "⬜"
        kb.button(text=f"{mark} {it['text']}", callback_data=f"chk_tog:{it['id']}")
    kb.button(text="➕ Пункт", callback_data=f"chk_add:{checklist_id}")
    kb.button(text="🗑 Видалити список", callback_data=f"chk_del:{checklist_id}")
    kb.adjust(1)
    return kb.as_markup()


def checklists_list_kb(checklists) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for c in checklists:
        kb.button(text=f"📋 {c['title']}", callback_data=f"chk_open:{c['id']}")
    kb.button(text="➕ Новий чекліст", callback_data="chk_new")
    kb.adjust(1)
    return kb.as_markup()


def template_kb(template_id: int) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="▶️ Створити нагадування", callback_data=f"tpl_use:{template_id}")
    kb.button(text="🗑 Видалити", callback_data=f"tpl_del:{template_id}")
    return kb.as_markup()


def digest_kb(times: list[str]) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for t in times:
        kb.button(text=t, callback_data=f"digest_set:{t}")
    kb.button(text="🚫 Вимкнути", callback_data="digest_set:off")
    kb.adjust(3)
    return kb.as_markup()


def done_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="✔️ Готово"), KeyboardButton(text="↩️ Скасувати")]],
        resize_keyboard=True,
    )


def sub_cycle_kb() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="📅 Щомісяця", callback_data="sub_cycle:monthly")
    kb.button(text="🗓 Щороку", callback_data="sub_cycle:yearly")
    kb.button(text="🔁 Щотижня", callback_data="sub_cycle:weekly")
    kb.adjust(3)
    return kb.as_markup()


def sub_card_kb(sub) -> InlineKeyboardMarkup:
    sid = sub["id"]
    kb = InlineKeyboardBuilder()
    kb.button(text="✅ Оплачено (наступний період)", callback_data=f"sub_paid:{sid}")
    kb.button(text=f"🔔 Нагадати за {sub['remind_days']} дн", callback_data=f"sub_remind:{sid}")
    trial = "🎁 Прибрати пробний" if sub["trial_end"] else "🎁 Додати пробний період"
    kb.button(text=trial, callback_data=f"sub_trial:{sid}")
    kb.button(text="✏️ Назва", callback_data=f"sub_edit:{sid}:name")
    kb.button(text="✏️ Сума", callback_data=f"sub_edit:{sid}:amount")
    kb.button(text="🗑 Видалити", callback_data=f"sub_del:{sid}")
    kb.button(text="← Список", callback_data="subs_pg:0")
    kb.adjust(1, 1, 1, 2, 1, 1)
    return kb.as_markup()


def tz_kb(zones: list[str]) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for z in zones:
        kb.button(text=z, callback_data=f"tz:{z}")
    kb.adjust(2)
    return kb.as_markup()


def cancel_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="↩️ Скасувати")]],
        resize_keyboard=True,
    )
