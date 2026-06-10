"""Стани FSM для багатокрокових діалогів."""
from aiogram.fsm.state import State, StatesGroup


class AddReminder(StatesGroup):
    waiting_text = State()


class AddNote(StatesGroup):
    waiting_text = State()


class EditNote(StatesGroup):
    waiting_text = State()


class SearchNotes(StatesGroup):
    waiting_query = State()


class SetTimezone(StatesGroup):
    waiting_tz = State()


class NewChecklist(StatesGroup):
    waiting_title = State()
    waiting_items = State()


class AddItem(StatesGroup):
    waiting_text = State()


class NewTemplate(StatesGroup):
    waiting_phrase = State()


class NewDeadline(StatesGroup):
    waiting_text = State()


class SetDigest(StatesGroup):
    waiting_time = State()


class AddSub(StatesGroup):
    name = State()
    amount = State()
    cycle = State()
    next_date = State()


class EditSub(StatesGroup):
    waiting_value = State()


class TrialSub(StatesGroup):
    waiting_date = State()
