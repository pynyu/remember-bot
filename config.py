"""Конфігурація бота — читається зі змінних оточення (.env)."""
import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class Config:
    bot_token: str
    default_tz: str
    db_path: str


def load_config() -> Config:
    token = os.getenv("BOT_TOKEN", "").strip()
    if not token:
        raise RuntimeError(
            "BOT_TOKEN не задано. Створи файл .env (див. .env.example) і встав туди токен."
        )
    return Config(
        bot_token=token,
        default_tz=os.getenv("DEFAULT_TZ", "Europe/Kyiv").strip(),
        db_path=os.getenv("DB_PATH", "data/bot.db").strip(),
    )


config = load_config()
