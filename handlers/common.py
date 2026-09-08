"""Общее для обработчиков: длинные сообщения, права мастера, обёртка вокруг генерации."""

import asyncio
import html
import logging
import sqlite3

import anthropic
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.types import InlineKeyboardMarkup, Message, ReactionTypeEmoji

import ai
import db
from config import TELEGRAM_MAX_LEN


def esc(text) -> str:
    """Экранирует текст пользователя или модели для HTML-разметки Telegram."""
    return html.escape(str(text), quote=False)


# ---------------------------------------------------------------- длинные сообщения

def split_text(text: str, limit: int = TELEGRAM_MAX_LEN) -> list[str]:
    """Режет текст на части не длиннее limit, предпочитая границы абзацев."""
    chunks: list[str] = []
    while len(text) > limit:
        cut = text.rfind("\n\n", 0, limit)
        if cut < limit // 2:
            cut = text.rfind("\n", 0, limit)
        if cut < limit // 2:
            cut = text.rfind(" ", 0, limit)
        if cut <= 0:
            cut = limit
        chunks.append(text[:cut].rstrip())
        text = text[cut:].lstrip()
    chunks.append(text)
    return chunks


async def answer_long(
    message: Message, text: str, reply_markup: InlineKeyboardMarkup | None = None
) -> None:
    chunks = split_text(text)
    for chunk in chunks[:-1]:
        await message.answer(chunk)
    await message.answer(chunks[-1], reply_markup=reply_markup)


async def edit_long(
    note: Message, text: str, reply_markup: InlineKeyboardMarkup | None = None
) -> None:
    """Первая часть заменяет сообщение-заглушку, остальные идут следом."""
    chunks = split_text(text)
    await note.edit_text(chunks[0], reply_markup=reply_markup if len(chunks) == 1 else None)
    for chunk in chunks[1:-1]:
        await note.answer(chunk)
    if len(chunks) > 1:
        await note.answer(chunks[-1], reply_markup=reply_markup)


async def try_delete(message: Message) -> bool:
    """Удаляет сообщение игрока, если у бота есть право. Иначе тихо возвращает False."""
    try:
        await message.delete()
        return True
    except (TelegramBadRequest, TelegramForbiddenError):
        return False


async def try_react(message: Message, emoji: str = "✍") -> bool:
    """Ставит реакцию вместо ответа — самый тихий способ подтвердить приём."""
    try:
        await message.react([ReactionTypeEmoji(emoji=emoji)])
        return True
    except (TelegramBadRequest, TelegramForbiddenError):
        return False


# ---------------------------------------------------------------- генерация

_locks: dict[int, asyncio.Lock] = {}


def chat_lock(chat_id: int) -> asyncio.Lock:
    return _locks.setdefault(chat_id, asyncio.Lock())


async def generate(note: Message, coro, what: str = "сгенерировать"):
    """Ждёт корутину генерации. При ошибке API заменяет заглушку понятным сообщением
    и возвращает None, чтобы обработчик мог просто выйти."""
    ai.current_chat.set(note.chat.id)
    try:
        return await coro
    except anthropic.RateLimitError:
        reason = "слишком много запросов к модели, подожди минуту"
    except anthropic.AuthenticationError:
        reason = "ключ Anthropic API не принят, проверь ANTHROPIC_API_KEY в .env"
    except anthropic.APIStatusError as e:
        reason = f"ошибка API ({e.status_code}), попробуй чуть позже"
    except anthropic.APIConnectionError:
        reason = "нет связи с API, проверь интернет на сервере"
    except Exception:
        logging.exception("generation failed")
        reason = "что-то пошло не так, попробуй ещё раз"
    await note.edit_text(f"⚠️ Не удалось {what}: {reason}.")
    return None


# ---------------------------------------------------------------- права

def is_gm(message: Message, game: sqlite3.Row | None) -> bool:
    """В личном чате мастер — всегда сам игрок. В группе — тот, кто создал мир,
    либо кто-то, кому он передал роль. Пока мастер не назначен, ограничений нет."""
    if message.chat.type == "private":
        return True
    if game is None or game["gm_user_id"] is None:
        return True
    return game["gm_user_id"] == message.from_user.id


async def require_world(message: Message) -> sqlite3.Row | None:
    game = db.get_world(message.chat.id)
    if game is None:
        await message.answer("Сначала создайте мир: /world <тема>")
    return game


async def require_gm(message: Message, game: sqlite3.Row | None) -> bool:
    if is_gm(message, game):
        return True
    await message.answer("⛔ Это может сделать только мастер игры. Кто мастер — /gm")
    return False


async def require_character(message: Message, need_conscious: bool = False) -> sqlite3.Row | None:
    character = db.get_character(message.chat.id, message.from_user.id)
    if character is None:
        await message.answer("Сначала создай персонажа: /hero")
        return None
    if not character["alive"]:
        await message.answer(
            f"⚰️ {esc(character['name'])} погиб. Создай нового героя: /hero"
        )
        return None
    if need_conscious and character["hp"] == 0:
        await message.answer(
            f"💀 {esc(character['name'])} без сознания и не может действовать. "
            "Нужна помощь союзников (/heal)."
        )
        return None
    return character


# ---------------------------------------------------------------- отображение

def hp_line(character) -> str:
    hp, max_hp = character["hp"], character["max_hp"]
    if not character["alive"]:
        state = "⚰️ погиб"
    elif hp == 0:
        state = "💀 без сознания"
    elif hp <= max_hp // 3:
        state = "🩸 тяжело ранен"
    elif hp < max_hp:
        state = "🤕 ранен"
    else:
        state = "❤️ здоров"
    return f"<b>{esc(character['name'])}</b>: {hp}/{max_hp} — {state}"
