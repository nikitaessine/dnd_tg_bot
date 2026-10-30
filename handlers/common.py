"""Общее для обработчиков: длинные сообщения, права мастера, обёртка вокруг генерации, отображение."""

import asyncio
import logging
import sqlite3

import anthropic
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.types import Chat, InlineKeyboardMarkup, Message, ReactionTypeEmoji

import ai
import db
import rules
from config import TELEGRAM_MAX_LEN
from engine import esc  # noqa: F401  (реэкспорт: обработчики берут esc отсюда)


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


def _plain(text: str) -> str:
    """Текст без HTML-разметки — запасной вариант, если Telegram не смог её разобрать."""
    import html
    import re
    return html.unescape(re.sub(r"</?(b|i|u|s|pre|code)>", "", text))


async def _send(send, text: str, **kwargs):
    """Отправка/редактирование с запасным вариантом без разметки при ошибке разбора HTML."""
    try:
        return await send(text, **kwargs)
    except TelegramBadRequest as e:
        if "parse entities" not in str(e):
            raise
        logging.warning("HTML parse failed, sending plain text: %s", e)
        return await send(_plain(text), parse_mode=None, **kwargs)


async def answer_long(
    message: Message, text: str, reply_markup: InlineKeyboardMarkup | None = None
) -> None:
    chunks = split_text(text)
    for chunk in chunks[:-1]:
        await _send(message.answer, chunk)
    await _send(message.answer, chunks[-1], reply_markup=reply_markup)


async def edit_long(
    note: Message, text: str, reply_markup: InlineKeyboardMarkup | None = None
) -> None:
    """Первая часть заменяет сообщение-заглушку, остальные идут следом."""
    chunks = split_text(text)
    await _send(note.edit_text, chunks[0], reply_markup=reply_markup if len(chunks) == 1 else None)
    for chunk in chunks[1:-1]:
        await _send(note.answer, chunk)
    if len(chunks) > 1:
        await _send(note.answer, chunks[-1], reply_markup=reply_markup)


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


async def generate(note: Message, coro, what: str = "сгенерировать", chat_id: int | None = None):
    """Ждёт корутину генерации. При ошибке API заменяет заглушку понятным сообщением
    и возвращает None, чтобы обработчик мог просто выйти."""
    ai.current_chat.set(chat_id or note.chat.id)
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


# Команды мастера пишутся только в личку боту. Тайные (ответ остаётся в личке) обрабатывают сами;
# публичные выполняются для группы мастера, и результат видят все игроки.
GM_SECRET = {"enemy", "npc", "backup", "usage"}
GM_PUBLIC = {"fight", "endfight", "xp", "loot", "rest", "condition", "exhaustion", "inspiration",
             "tone", "difficulty"}
# Урон и лечение игроки делают и себе в группе, а мастер может и из лички
FROM_DM = GM_PUBLIC | {"damage", "heal", "temp"}


def command_name(message: Message) -> str:
    text = message.text or ""
    if not text.startswith("/"):
        return ""
    return text.split()[0][1:].split("@")[0].casefold()


async def gm_commands_middleware(handler, message: Message, data: dict):
    """В группе команды мастера убираются с подсказкой; из лички мастера выполняются для его группы."""
    name = command_name(message)
    if not name:
        return await handler(message, data)
    if message.chat.type != "private" and name in GM_SECRET | GM_PUBLIC:
        await try_delete(message)
        me = await message.bot.me()
        await message.answer(f"👑 Команды мастера пиши мне в личку: @{me.username}")
        return None
    if name in FROM_DM:
        group = secret_chat(message)
        if group is not None:
            message = message.model_copy(update={"chat": Chat(id=group, type="group")})
    return await handler(message, data)


def secret_chat(message: Message) -> int | None:
    """Команда мастера из лички: группа, для которой он тайно готовит NPC и противников."""
    if message.chat.type != "private":
        return None
    return db.gm_group_chat(message.from_user.id)


async def require_world(message: Message) -> sqlite3.Row | None:
    game = db.get_world(message.chat.id)
    if game is None:
        await message.answer("Сначала создайте мир: /world &lt;тема&gt;")
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
            "Нужна помощь союзников (/heal, /stabilize)."
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
        if character["death_successes"] >= 3:
            state += " (стабилен)"
        elif character["death_failures"] or character["death_successes"]:
            state += f" (спасброски: ✓{character['death_successes']} ✗{character['death_failures']})"
    elif hp <= max_hp // 3:
        state = "🩸 тяжело ранен"
    elif hp < max_hp:
        state = "🤕 ранен"
    else:
        state = "❤️ здоров"
    temp = f" (+{character['temp_hp']} врем.)" if character["temp_hp"] else ""
    return f"<b>{esc(character['name'])}</b>: {hp}/{max_hp}{temp} — {state}"


def conditions_text(character) -> str:
    names = sorted(rules.cond_names(rules.conditions_of(character)) - {"без сознания"})
    parts = list(names)
    if rules.exhaustion_of(character):
        parts.append(f"истощение {rules.exhaustion_of(character)}")
    return ", ".join(parts)
