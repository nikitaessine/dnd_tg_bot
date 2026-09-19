"""Кампания: мир, мастер игры, тон, сложность, обзор, сброс, резервная копия, расход."""

import os
import tempfile

from aiogram import Router
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.types import FSInputFile, Message

import ai
import db
import rules
from config import DIFFICULTIES, PRICE_INPUT_PER_M, PRICE_OUTPUT_PER_M
from handlers.common import (
    answer_long,
    edit_long,
    esc,
    generate,
    hp_line,
    require_gm,
    require_world,
)

router = Router()

HELP = (
    "🎲 <b>D&D-бот</b> — правила D&D 5e (Basic Rules)\n\n"
    "<b>Начало игры</b>\n"
    "/world &lt;тема&gt; — создать мир (создавший становится мастером)\n"
    "/hero — создать персонажа: раса, класс, предыстория, характеристики, навыки\n"
    "/sheet — лист персонажа · /skills — навыки · /inventory — инвентарь\n"
    "/status — обзор кампании · /recap — «в предыдущих сериях» · /journal — журнал\n\n"
    "<b>Ход игры</b>\n"
    "/scene — следующая сцена · /do &lt;действие&gt; · /say &lt;реплика&gt; или «кавычки»\n"
    "/actions · /party · /npc\n\n"
    "<b>Кубики и проверки</b>\n"
    "/roll · /roll 2d6+1 · /roll Ловкость · /roll Скрытность 15 помеха · /sroll Восприятие 15 (тайно)\n"
    "/save Ловкость 14 — спасбросок\n\n"
    "<b>Бой</b>\n"
    "Ход: кнопки под сообщением или /attack &lt;враг&gt; · /endturn · /order · /enemies\n"
    "Действия: /dodge · /hide · /assist &lt;имя&gt; · /shove &lt;враг&gt; · /stabilize &lt;имя&gt;\n"
    "Воин: /secondwind · /surge · Плут: /cunning рывок|отход|скрыться\n"
    "Жрец: /channel сохранение|изгнание\n\n"
    "<b>Магия</b>\n"
    "/spells · /cast &lt;заклинание&gt; [ячейка] [цель, цель] · /prepare · /learn · /cantrip · /recover\n\n"
    "<b>Здоровье, предметы, развитие</b>\n"
    "/hp · /damage 5 [имя] · /heal 3 [имя] · /temp 5 [имя] · /hitdice [сколько]\n"
    "/take Длинный меч · /take Кольчуга +1 · /equip · /unequip · /drop\n"
    "/asi Сила Ловкость · /expertise Навык, Навык · /inspire\n\n"
    "<b>Мастер игры</b>\n"
    "/gm · /enemy &lt;описание | Имя HP КД +атака кубик&gt; (можно «3x …») · /fight · /endfight\n"
    "/loot · /xp 300 [имя] · /rest короткий|долгий · /condition · /exhaustion · /inspiration\n"
    "/tone · /difficulty · /backup · /usage · /reset · /delete_hero"
)


@router.message(CommandStart())
@router.message(Command("help"))
async def cmd_start(message: Message) -> None:
    await answer_long(message, HELP)


@router.message(Command("world"))
async def cmd_world(message: Message, command: CommandObject) -> None:
    theme = (command.args or "").strip()
    if not theme:
        await message.answer("Укажи тему мира: /world мрачное тёмное фэнтези")
        return
    game = db.get_world(message.chat.id)
    if game is not None:
        await message.answer(
            f"Мир уже создан: «{esc(game['theme'])}». Чтобы начать другую кампанию, "
            "мастер сначала делает /reset, затем /world."
        )
        return
    note = await message.answer("🌍 Создаю мир, подожди немного…")
    world_desc = await generate(note, ai.generate_world(theme), "создать мир")
    if world_desc is None:
        return
    db.set_world(message.chat.id, theme, world_desc, message.from_user.id)
    gm_note = ""
    if message.chat.type != "private":
        gm_note = f"\n\n👑 Мастер игры: {esc(message.from_user.first_name)}"
    await edit_long(note, f"🌍 <b>Мир кампании: {esc(theme)}</b>\n\n{esc(world_desc)}{gm_note}")


async def _gm_name(message: Message, gm_user_id: int) -> str:
    try:
        member = await message.bot.get_chat_member(message.chat.id, gm_user_id)
        return member.user.first_name
    except (TelegramBadRequest, TelegramForbiddenError):
        return "неизвестно"


@router.message(Command("gm"))
async def cmd_gm(message: Message) -> None:
    game = await require_world(message)
    if game is None:
        return
    reply = message.reply_to_message
    if reply is not None and reply.from_user is not None and not reply.from_user.is_bot:
        if not await require_gm(message, game):
            return
        db.update_game(message.chat.id, gm_user_id=reply.from_user.id)
        await message.answer(f"👑 Мастер игры теперь: {esc(reply.from_user.first_name)}")
        return
    if game["gm_user_id"] is None:
        db.update_game(message.chat.id, gm_user_id=message.from_user.id)
        await message.answer(f"👑 Мастер игры: {esc(message.from_user.first_name)}")
        return
    name = await _gm_name(message, game["gm_user_id"])
    await message.answer(
        f"👑 Мастер игры: {esc(name)}\n"
        "Чтобы передать роль, мастер отвечает на сообщение игрока командой /gm."
    )


@router.message(Command("tone"))
async def cmd_tone(message: Message, command: CommandObject) -> None:
    game = await require_world(message)
    if game is None:
        return
    tone = (command.args or "").strip()
    if not tone:
        current = game["tone"] or "не задан"
        await message.answer(
            f"🎭 Тон кампании: {esc(current)}\n"
            "Задать: /tone мрачный хоррор с чёрным юмором"
        )
        return
    if not await require_gm(message, game):
        return
    db.update_game(message.chat.id, tone=tone[:500])
    await message.answer(f"🎭 Тон кампании задан: {esc(tone[:500])}")


@router.message(Command("difficulty"))
async def cmd_difficulty(message: Message, command: CommandObject) -> None:
    game = await require_world(message)
    if game is None:
        return
    raw = (command.args or "").strip().casefold()
    if not raw:
        await message.answer(
            f"🎚 Сложность: {esc(game['difficulty'])}\n"
            f"Изменить: /difficulty {' | '.join(DIFFICULTIES)}"
        )
        return
    if not await require_gm(message, game):
        return
    chosen = next((d for d in DIFFICULTIES if d.startswith(raw)), None)
    if chosen is None:
        await message.answer(f"Варианты: {', '.join(DIFFICULTIES)}")
        return
    db.update_game(message.chat.id, difficulty=chosen)
    await message.answer(f"🎚 Сложность: {chosen}")


@router.message(Command("reset"))
async def cmd_reset(message: Message) -> None:
    game = db.get_world(message.chat.id)
    if game is not None and not await require_gm(message, game):
        return
    db.reset_game(message.chat.id)
    await message.answer("♻️ Кампания сброшена. Начните заново: /world &lt;тема&gt;")


@router.message(Command("status"))
async def cmd_status(message: Message) -> None:
    game = db.get_world(message.chat.id)
    if game is None:
        await message.answer("Кампания ещё не начата. Создайте мир: /world &lt;тема&gt;")
        return
    chat_id = message.chat.id
    lines = [f"🌍 <b>Мир:</b> {esc(game['theme'])}"]
    if game["location"]:
        lines.append(f"📍 {esc(game['location'])}")
    if game["gm_user_id"] is not None and message.chat.type != "private":
        lines.append(f"👑 Мастер: {esc(await _gm_name(message, game['gm_user_id']))}")
    lines.append(f"🎚 Сложность: {esc(game['difficulty'])}")
    if game["tone"]:
        lines.append(f"🎭 Тон: {esc(game['tone'])}")

    lines += ["", "⚔️ <b>Персонажи:</b>"]
    characters = db.list_characters(chat_id)
    if characters:
        for c in characters:
            lines.append(f"• {hp_line(c)} — {rules.race_of(c)} {rules.class_of(c)} {c['level']} ур. — {esc(c['user_name'])}")
    else:
        lines.append("• пока нет")

    npcs = db.list_npcs(chat_id)
    lines += ["", "🧙 <b>NPC:</b> " + (", ".join(esc(n["name"]) for n in npcs) if npcs else "пока нет")]

    enemies = db.list_enemies(chat_id)
    if enemies:
        lines += ["", "👹 <b>Противники:</b>"]
        lines += [f"• {esc(e['name'])}: {e['hp']}/{e['max_hp']} HP, КД {e['armor_class']}" for e in enemies]

    combat_state = db.get_combat(chat_id)
    if combat_state is not None:
        lines += ["", f"⚔️ Идёт бой, раунд {combat_state['round']}"]

    scene_number = db.current_situation_number(chat_id)
    if scene_number:
        lines += ["", f"📜 Сыграно сцен: {scene_number}"]
    pending = db.pending_actions(chat_id, kind="action")
    if pending:
        lines.append(f"🗣 Заявлено действий к следующей сцене: {len(pending)}")
    await answer_long(message, "\n".join(lines))


@router.message(Command("backup"))
async def cmd_backup(message: Message) -> None:
    game = await require_world(message)
    if game is None or not await require_gm(message, game):
        return
    fd, path = tempfile.mkstemp(prefix="dnd-backup-", suffix=".db")
    os.close(fd)
    try:
        db.backup_to(path)
        document = FSInputFile(path, filename="game-backup.db")
        caption = "💾 Резервная копия базы. Чтобы восстановить — положи файл как game.db на сервер."
        try:
            await message.bot.send_document(message.from_user.id, document, caption=caption)
            if message.chat.type != "private":
                await message.answer("💾 Копия базы отправлена тебе в личные сообщения.")
        except (TelegramForbiddenError, TelegramBadRequest):
            await message.answer_document(document, caption=caption)
    finally:
        os.remove(path)


@router.message(Command("usage"))
async def cmd_usage(message: Message) -> None:
    game = await require_world(message)
    if game is None or not await require_gm(message, game):
        return
    totals = db.usage_totals(message.chat.id)
    cost = (
        totals["input_tokens"] / 1_000_000 * PRICE_INPUT_PER_M
        + totals["output_tokens"] / 1_000_000 * PRICE_OUTPUT_PER_M
    )
    tokens_in = f"{totals['input_tokens']:,}".replace(",", " ")
    tokens_out = f"{totals['output_tokens']:,}".replace(",", " ")
    await message.answer(
        "📊 <b>Расход на эту кампанию</b>\n"
        f"Запросов к модели: {totals['calls']}\n"
        f"Токены: {tokens_in} на входе, {tokens_out} на выходе\n"
        f"Примерная стоимость: ${cost:.2f}"
    )
