"""Шар роботи з SQLite через aiosqlite.

База даних — єдине джерело правди. Планувальник (scheduler.py) кожні кілька
секунд опитує цю базу й надсилає нагадування, час яких настав. Такий підхід
надійний: навіть якщо бот був вимкнений, прострочені нагадування надішлються
одразу після старту.
"""
from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Optional

import aiosqlite

from config import config

_db: Optional[aiosqlite.Connection] = None


SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    user_id      INTEGER PRIMARY KEY,
    username     TEXT,
    tz           TEXT NOT NULL,
    created_at   TEXT NOT NULL,
    def_count    INTEGER NOT NULL DEFAULT 2,   -- скільки разів нагадувати за замовч.
    def_interval INTEGER NOT NULL DEFAULT 10,  -- інтервал між повторами (хв)
    def_priority INTEGER NOT NULL DEFAULT 1,   -- 0 тихо | 1 звичайно | 2 важливо
    done_count   INTEGER NOT NULL DEFAULT 0,   -- лічильник виконаних
    digest_time  TEXT,                          -- HH:MM локального часу або NULL (вимкнено)
    digest_last  TEXT                           -- дата останнього надісланого дайджесту (YYYY-MM-DD)
);

CREATE TABLE IF NOT EXISTS notes (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    INTEGER NOT NULL,
    text       TEXT NOT NULL,
    pinned     INTEGER NOT NULL DEFAULT 0,
    media_type TEXT,                            -- NULL|photo|document|voice|audio|video
    file_id    TEXT,                            -- Telegram file_id вкладення
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS checklists (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    INTEGER NOT NULL,
    title      TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS checklist_items (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    checklist_id INTEGER NOT NULL,
    text         TEXT NOT NULL,
    done         INTEGER NOT NULL DEFAULT 0,
    position     INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS templates (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    INTEGER NOT NULL,
    phrase     TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS reminders (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id        INTEGER NOT NULL,
    text           TEXT NOT NULL,
    base_at        TEXT NOT NULL,                  -- ISO UTC «справжнього» часу нагадування
    fire_at        TEXT NOT NULL,                  -- ISO UTC наступного сповіщення (база або повтор)
    repeat         TEXT NOT NULL DEFAULT 'none',   -- none|daily|weekly|monthly|yearly|weekdays
    priority       INTEGER NOT NULL DEFAULT 1,     -- 0|1|2
    notify_count   INTEGER NOT NULL DEFAULT 2,     -- скільки сповіщень за одне спрацювання
    notify_interval INTEGER NOT NULL DEFAULT 10,   -- хвилин між сповіщеннями
    pings_left     INTEGER NOT NULL DEFAULT 2,     -- скільки сповіщень лишилось у поточному циклі
    active         INTEGER NOT NULL DEFAULT 1,
    created_at     TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_notes_user ON notes(user_id);
CREATE INDEX IF NOT EXISTS idx_reminders_user ON reminders(user_id);
CREATE INDEX IF NOT EXISTS idx_reminders_due ON reminders(active, fire_at);
CREATE INDEX IF NOT EXISTS idx_checklists_user ON checklists(user_id);
CREATE INDEX IF NOT EXISTS idx_items_checklist ON checklist_items(checklist_id);
CREATE INDEX IF NOT EXISTS idx_templates_user ON templates(user_id);
"""

# Колонки, які могли з'явитися пізніше — для оновлення старих баз на сервері.
_MIGRATIONS = {
    "users": [
        ("def_count", "INTEGER NOT NULL DEFAULT 2"),
        ("def_interval", "INTEGER NOT NULL DEFAULT 10"),
        ("def_priority", "INTEGER NOT NULL DEFAULT 1"),
        ("done_count", "INTEGER NOT NULL DEFAULT 0"),
        ("digest_time", "TEXT"),
        ("digest_last", "TEXT"),
    ],
    "reminders": [
        ("base_at", "TEXT"),
        ("priority", "INTEGER NOT NULL DEFAULT 1"),
        ("notify_count", "INTEGER NOT NULL DEFAULT 2"),
        ("notify_interval", "INTEGER NOT NULL DEFAULT 10"),
        ("pings_left", "INTEGER NOT NULL DEFAULT 1"),
    ],
    "notes": [
        ("media_type", "TEXT"),
        ("file_id", "TEXT"),
    ],
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


async def _existing_columns(table: str) -> set[str]:
    cur = await _db.execute(f"PRAGMA table_info({table})")
    return {row["name"] for row in await cur.fetchall()}


async def _migrate() -> None:
    for table, cols in _MIGRATIONS.items():
        existing = await _existing_columns(table)
        for col, ddl in cols:
            if col not in existing:
                await _db.execute(f"ALTER TABLE {table} ADD COLUMN {col} {ddl}")
    # Заповнюємо base_at для старих нагадувань (= fire_at).
    await _db.execute(
        "UPDATE reminders SET base_at = fire_at WHERE base_at IS NULL OR base_at = ''"
    )
    await _db.commit()


async def init_db() -> None:
    global _db
    os.makedirs(os.path.dirname(config.db_path) or ".", exist_ok=True)
    _db = await aiosqlite.connect(config.db_path)
    _db.row_factory = aiosqlite.Row
    await _db.executescript(SCHEMA)
    await _db.commit()
    await _migrate()


async def close_db() -> None:
    if _db is not None:
        await _db.close()


def db() -> aiosqlite.Connection:
    assert _db is not None, "init_db() ще не викликано"
    return _db


# ---------------------------------------------------------------- users

async def ensure_user(user_id: int, username: Optional[str]) -> None:
    cur = await db().execute("SELECT user_id FROM users WHERE user_id = ?", (user_id,))
    row = await cur.fetchone()
    if row is None:
        await db().execute(
            "INSERT INTO users (user_id, username, tz, created_at) VALUES (?, ?, ?, ?)",
            (user_id, username, config.default_tz, _now()),
        )
    else:
        await db().execute(
            "UPDATE users SET username = ? WHERE user_id = ?", (username, user_id)
        )
    await db().commit()


async def get_user(user_id: int) -> aiosqlite.Row:
    cur = await db().execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
    return await cur.fetchone()


async def get_tz(user_id: int) -> str:
    cur = await db().execute("SELECT tz FROM users WHERE user_id = ?", (user_id,))
    row = await cur.fetchone()
    return row["tz"] if row else config.default_tz


async def set_tz(user_id: int, tz: str) -> None:
    await db().execute("UPDATE users SET tz = ? WHERE user_id = ?", (tz, user_id))
    await db().commit()


async def set_user_default(user_id: int, field: str, value: int) -> None:
    assert field in ("def_count", "def_interval", "def_priority")
    await db().execute(
        f"UPDATE users SET {field} = ? WHERE user_id = ?", (value, user_id)
    )
    await db().commit()


async def inc_done(user_id: int) -> None:
    await db().execute(
        "UPDATE users SET done_count = done_count + 1 WHERE user_id = ?", (user_id,)
    )
    await db().commit()


async def set_digest_time(user_id: int, hhmm: Optional[str]) -> None:
    await db().execute(
        "UPDATE users SET digest_time = ? WHERE user_id = ?", (hhmm, user_id)
    )
    await db().commit()


async def set_digest_last(user_id: int, day: str) -> None:
    await db().execute(
        "UPDATE users SET digest_last = ? WHERE user_id = ?", (day, user_id)
    )
    await db().commit()


async def users_with_digest() -> list[aiosqlite.Row]:
    cur = await db().execute(
        "SELECT * FROM users WHERE digest_time IS NOT NULL AND digest_time != ''"
    )
    return await cur.fetchall()


# ---------------------------------------------------------------- notes

async def add_note(
    user_id: int, text: str, media_type: Optional[str] = None,
    file_id: Optional[str] = None,
) -> int:
    now = _now()
    cur = await db().execute(
        "INSERT INTO notes (user_id, text, media_type, file_id, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (user_id, text, media_type, file_id, now, now),
    )
    await db().commit()
    return cur.lastrowid


async def list_notes(user_id: int) -> list[aiosqlite.Row]:
    cur = await db().execute(
        "SELECT * FROM notes WHERE user_id = ? ORDER BY pinned DESC, id DESC",
        (user_id,),
    )
    return await cur.fetchall()


async def count_notes(user_id: int) -> int:
    cur = await db().execute(
        "SELECT COUNT(*) AS c FROM notes WHERE user_id = ?", (user_id,)
    )
    return (await cur.fetchone())["c"]


async def get_note(user_id: int, note_id: int) -> Optional[aiosqlite.Row]:
    cur = await db().execute(
        "SELECT * FROM notes WHERE id = ? AND user_id = ?", (note_id, user_id)
    )
    return await cur.fetchone()


async def update_note(user_id: int, note_id: int, text: str) -> None:
    await db().execute(
        "UPDATE notes SET text = ?, updated_at = ? WHERE id = ? AND user_id = ?",
        (text, _now(), note_id, user_id),
    )
    await db().commit()


async def toggle_pin(user_id: int, note_id: int) -> None:
    await db().execute(
        "UPDATE notes SET pinned = 1 - pinned WHERE id = ? AND user_id = ?",
        (note_id, user_id),
    )
    await db().commit()


async def delete_note(user_id: int, note_id: int) -> None:
    await db().execute(
        "DELETE FROM notes WHERE id = ? AND user_id = ?", (note_id, user_id)
    )
    await db().commit()


async def search_notes(user_id: int, query: str) -> list[aiosqlite.Row]:
    cur = await db().execute(
        "SELECT * FROM notes WHERE user_id = ? AND text LIKE ? "
        "ORDER BY pinned DESC, id DESC",
        (user_id, f"%{query}%"),
    )
    return await cur.fetchall()


# ------------------------------------------------------------ reminders

async def add_reminder(
    user_id: int,
    text: str,
    base_at_utc: datetime,
    repeat: str = "none",
    priority: int = 1,
    notify_count: int = 2,
    notify_interval: int = 10,
) -> int:
    iso = base_at_utc.isoformat()
    cur = await db().execute(
        "INSERT INTO reminders "
        "(user_id, text, base_at, fire_at, repeat, priority, notify_count, "
        " notify_interval, pings_left, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (user_id, text, iso, iso, repeat, priority, notify_count,
         notify_interval, notify_count, _now()),
    )
    await db().commit()
    return cur.lastrowid


async def get_reminder(reminder_id: int) -> Optional[aiosqlite.Row]:
    cur = await db().execute("SELECT * FROM reminders WHERE id = ?", (reminder_id,))
    return await cur.fetchone()


async def list_reminders(user_id: int) -> list[aiosqlite.Row]:
    cur = await db().execute(
        "SELECT * FROM reminders WHERE user_id = ? AND active = 1 ORDER BY base_at ASC",
        (user_id,),
    )
    return await cur.fetchall()


async def due_reminders(now_utc: datetime) -> list[aiosqlite.Row]:
    cur = await db().execute(
        "SELECT * FROM reminders WHERE active = 1 AND fire_at <= ? ORDER BY fire_at ASC",
        (now_utc.isoformat(),),
    )
    return await cur.fetchall()


async def set_cycle(
    reminder_id: int, base_at: datetime, fire_at: datetime, pings_left: int
) -> None:
    await db().execute(
        "UPDATE reminders SET base_at = ?, fire_at = ?, pings_left = ?, active = 1 "
        "WHERE id = ?",
        (base_at.isoformat(), fire_at.isoformat(), pings_left, reminder_id),
    )
    await db().commit()


async def set_config(
    reminder_id: int, priority: int, notify_count: int, notify_interval: int
) -> None:
    # Якщо нагадування ще не спрацювало — синхронізуємо лічильник pings_left.
    await db().execute(
        "UPDATE reminders SET priority = ?, notify_count = ?, notify_interval = ?, "
        "pings_left = ? WHERE id = ?",
        (priority, notify_count, notify_interval, notify_count, reminder_id),
    )
    await db().commit()


async def deactivate_reminder(reminder_id: int) -> None:
    await db().execute("UPDATE reminders SET active = 0 WHERE id = ?", (reminder_id,))
    await db().commit()


async def delete_reminder(user_id: int, reminder_id: int) -> bool:
    cur = await db().execute(
        "DELETE FROM reminders WHERE id = ? AND user_id = ?", (reminder_id, user_id)
    )
    await db().commit()
    return cur.rowcount > 0


async def count_active_reminders(user_id: int) -> int:
    cur = await db().execute(
        "SELECT COUNT(*) AS c FROM reminders WHERE user_id = ? AND active = 1",
        (user_id,),
    )
    return (await cur.fetchone())["c"]


# ----------------------------------------------------------- checklists

async def add_checklist(user_id: int, title: str) -> int:
    cur = await db().execute(
        "INSERT INTO checklists (user_id, title, created_at) VALUES (?, ?, ?)",
        (user_id, title, _now()),
    )
    await db().commit()
    return cur.lastrowid


async def get_checklist(user_id: int, checklist_id: int) -> Optional[aiosqlite.Row]:
    cur = await db().execute(
        "SELECT * FROM checklists WHERE id = ? AND user_id = ?", (checklist_id, user_id)
    )
    return await cur.fetchone()


async def list_checklists(user_id: int) -> list[aiosqlite.Row]:
    cur = await db().execute(
        "SELECT * FROM checklists WHERE user_id = ? ORDER BY id DESC", (user_id,)
    )
    return await cur.fetchall()


async def delete_checklist(user_id: int, checklist_id: int) -> None:
    await db().execute(
        "DELETE FROM checklist_items WHERE checklist_id = ?", (checklist_id,)
    )
    await db().execute(
        "DELETE FROM checklists WHERE id = ? AND user_id = ?", (checklist_id, user_id)
    )
    await db().commit()


async def add_item(checklist_id: int, text: str) -> int:
    cur = await db().execute(
        "SELECT COALESCE(MAX(position), 0) + 1 AS p FROM checklist_items "
        "WHERE checklist_id = ?",
        (checklist_id,),
    )
    pos = (await cur.fetchone())["p"]
    cur = await db().execute(
        "INSERT INTO checklist_items (checklist_id, text, position) VALUES (?, ?, ?)",
        (checklist_id, text, pos),
    )
    await db().commit()
    return cur.lastrowid


async def list_items(checklist_id: int) -> list[aiosqlite.Row]:
    cur = await db().execute(
        "SELECT * FROM checklist_items WHERE checklist_id = ? ORDER BY position ASC",
        (checklist_id,),
    )
    return await cur.fetchall()


async def get_item(item_id: int) -> Optional[aiosqlite.Row]:
    cur = await db().execute(
        "SELECT * FROM checklist_items WHERE id = ?", (item_id,)
    )
    return await cur.fetchone()


async def toggle_item(item_id: int) -> None:
    await db().execute(
        "UPDATE checklist_items SET done = 1 - done WHERE id = ?", (item_id,)
    )
    await db().commit()


async def delete_item(item_id: int) -> None:
    await db().execute("DELETE FROM checklist_items WHERE id = ?", (item_id,))
    await db().commit()


# ------------------------------------------------------------ templates

async def add_template(user_id: int, phrase: str) -> int:
    cur = await db().execute(
        "INSERT INTO templates (user_id, phrase, created_at) VALUES (?, ?, ?)",
        (user_id, phrase, _now()),
    )
    await db().commit()
    return cur.lastrowid


async def list_templates(user_id: int) -> list[aiosqlite.Row]:
    cur = await db().execute(
        "SELECT * FROM templates WHERE user_id = ? ORDER BY id DESC", (user_id,)
    )
    return await cur.fetchall()


async def get_template(user_id: int, template_id: int) -> Optional[aiosqlite.Row]:
    cur = await db().execute(
        "SELECT * FROM templates WHERE id = ? AND user_id = ?", (template_id, user_id)
    )
    return await cur.fetchone()


async def delete_template(user_id: int, template_id: int) -> None:
    await db().execute(
        "DELETE FROM templates WHERE id = ? AND user_id = ?", (template_id, user_id)
    )
    await db().commit()
