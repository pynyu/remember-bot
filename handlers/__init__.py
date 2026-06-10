"""Збір усіх роутерів в один."""
from aiogram import Router

from . import (
    checklists,
    common,
    deadline,
    media,
    notes,
    reminders,
    settings,
    smart,
    templates,
)


def setup_routers() -> Router:
    root = Router()
    # порядок важливий: smart-роутер ловить вільний текст останнім
    root.include_router(common.router)
    root.include_router(settings.router)
    root.include_router(reminders.router)
    root.include_router(checklists.router)
    root.include_router(templates.router)
    root.include_router(deadline.router)
    root.include_router(notes.router)
    root.include_router(media.router)
    root.include_router(smart.router)
    return root
