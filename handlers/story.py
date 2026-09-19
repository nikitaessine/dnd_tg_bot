"""Сюжет: сцены, действия игроков, проверки по запросу мастера, NPC, пересказ, журнал."""

import time

from aiogram import F, Router
from aiogram.filters import Command, CommandObject
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

import ai
import db
import dice
import engine
import rules
import srd
from config import RECENT_SCENES, SCENE_COOLDOWN, SUMMARY_BATCH
from handlers.common import (
    answer_long,
    chat_lock,
    edit_long,
    conditions_text,
    esc,
    generate,
    require_character,
    require_world,
    try_delete,
    try_react,
)

router = Router()

_last_scene_at: dict[int, float] = {}

QUOTE_PREFIXES = ('"', "«", "“")


def party_card(chat_id: int) -> str | None:
    """Кто есть кто: показывается в начале игры, чтобы дальше хватало имени персонажа."""
    characters = db.list_characters(chat_id, alive_only=True)
    if not characters:
        return None
    lines = ["👥 <b>Отряд</b>", ""]
    for c in characters:
        lines.append(f"🧝 <b>{esc(c['name'])}</b> — {esc(c['description'])}")
        lines.append(f"<i>играет {esc(c['user_name'])}</i>")
        lines.append("")
    return "\n".join(lines).rstrip()


async def _post_in_character(message: Message, text: str) -> None:
    """Убирает сообщение игрока и публикует текст от лица персонажа.
    Без права на удаление — оставляет сообщение и подтверждает реакцией."""
    if await try_delete(message):
        await answer_long(message, text)
        return
    if not await try_react(message):
        await answer_long(message, text)


def _character_summaries(chat_id: int) -> list[str]:
    result = []
    for c in db.list_characters(chat_id):
        if not c["alive"]:
            state = "ПОГИБ"
        else:
            g = engine.gear(chat_id, c)
            state = f"{c['level']} ур., {c['hp']}/{c['max_hp']} HP, КД {g['ac']}"
            if c["hp"] == 0:
                state += ", без сознания"
            extra = conditions_text(c)
            if extra:
                state += f", {extra}"
        sub = rules.subrace_of(c)
        kind = f"{sub or rules.race_of(c)} {rules.class_of(c)}".strip()
        result.append(f"{c['name']} ({kind}; {c['description']}) — {state}; играет {c['user_name']}")
    return result


async def _maybe_summarize(note: Message, game) -> None:
    """Сжимает сцены, выпавшие из окна последних RECENT_SCENES, в короткий пересказ."""
    chat_id = note.chat.id
    current = db.current_situation_number(chat_id)
    window_start = max(1, current - RECENT_SCENES + 1)
    unsummarized_end = window_start - 1
    if unsummarized_end - game["summary_upto"] < SUMMARY_BATCH:
        return
    scenes = db.situations_between(chat_id, game["summary_upto"] + 1, unsummarized_end)
    if not scenes:
        return
    summary = await generate(
        note, ai.summarize(game["summary"], [s["text"] for s in scenes], game["tone"]),
        "сжать историю",
    )
    if summary is not None:
        db.update_game(chat_id, summary=summary, summary_upto=unsummarized_end)


CHECK_NAMES = list(srd.SKILLS) + list(srd.ABILITIES)


def _check_buttons(chat_id: int, checks) -> tuple[list[str], InlineKeyboardMarkup | None]:
    """Кнопки для проверок и спасбросков, запрошенных мастером. Пропускает несуществующих персонажей."""
    lines, rows = [], []
    for check in checks[:3]:
        character = db.find_character(chat_id, check.character)
        is_save = check.kind.strip().casefold().startswith(("save", "спас"))
        pool = srd.ABILITIES if is_save else CHECK_NAMES
        name = dice.match_name(check.attribute, pool)
        if character is None or name is None or not character["alive"] or character["hp"] == 0:
            continue
        difficulty = max(5, min(30, check.difficulty))
        label = f"спасбросок {name}" if is_save else name
        lines.append(f"• <b>{esc(character['name'])}</b> — {label} (сложность {difficulty}): {esc(check.reason)}")
        code = f"{'s' if is_save else 'c'}{pool.index(name)}"
        rows.append([
            InlineKeyboardButton(
                text=f"🎲 {character['name']}: {label} (сл. {difficulty})"[:60],
                callback_data=f"check:{character['user_id']}:{code}:{difficulty}",
            )
        ])
    if not rows:
        return [], None
    return ["", "🎯 <b>Мастер просит проверки:</b>", *lines], InlineKeyboardMarkup(inline_keyboard=rows)


@router.message(Command("scene"))
async def cmd_scene(message: Message) -> None:
    game = await require_world(message)
    if game is None:
        return
    chat_id = message.chat.id
    lock = chat_lock(chat_id)
    if lock.locked():
        await message.answer("⏳ Сцена уже генерируется, подожди.")
        return
    wait = SCENE_COOLDOWN - (time.monotonic() - _last_scene_at.get(chat_id, 0))
    if wait > 0:
        await message.answer(f"⏳ Следующую сцену можно запросить через {int(wait) + 1} с.")
        return
    if db.get_combat(chat_id) is not None:
        await message.answer("⚔️ Идёт бой. Закончите его (/endfight или победа), потом /scene.")
        return

    async with lock:
        _last_scene_at[chat_id] = time.monotonic()
        note = await message.answer("📜 Генерирую следующую сцену…")
        await _maybe_summarize(note, game)
        game = db.get_world(chat_id)

        recent = db.list_situations(chat_id, RECENT_SCENES)
        pending = db.pending_actions(chat_id)
        ctx = ai.SceneContext(
            theme=game["theme"],
            world_desc=game["world_desc"],
            tone=game["tone"],
            difficulty=game["difficulty"],
            location=game["location"],
            summary=game["summary"],
            recent_scenes=[s["text"] for s in recent],
            first_recent_number=recent[0]["number"] if recent else 1,
            characters=_character_summaries(chat_id),
            npcs=[n["description"] for n in db.list_npcs(chat_id)],
            facts=[f["text"] for f in db.list_facts(chat_id)],
            actions=[f"{a['character_name']}: {a['text']}" for a in pending if a["kind"] == "action"],
            events=[f"{a['character_name']}: {a['text']}" for a in pending if a["kind"] != "action"],
        )
        result = await generate(note, ai.generate_scene(ctx), "сгенерировать сцену")
        if result is None:
            return

        number = db.save_situation(chat_id, result.text)
        if result.location.strip():
            db.update_game(chat_id, location=result.location.strip()[:200])
        for fact in result.new_facts[:3]:
            if fact.strip():
                db.add_fact(chat_id, number, fact.strip()[:300])

        text = f"📜 <b>Сцена {number}</b>\n\n{esc(result.text)}"
        check_lines, keyboard = _check_buttons(chat_id, result.checks)
        if check_lines:
            text += "\n" + "\n".join(check_lines)
        if number == 1:
            card = party_card(chat_id)
            if card:
                await note.edit_text(card)
                note = await note.answer("📜 …")
        await edit_long(note, text, keyboard)


def _without_button(markup: InlineKeyboardMarkup | None, data: str) -> InlineKeyboardMarkup | None:
    if markup is None:
        return None
    rows = [[b for b in row if b.callback_data != data] for row in markup.inline_keyboard]
    rows = [r for r in rows if r]
    return InlineKeyboardMarkup(inline_keyboard=rows) if rows else None


@router.callback_query(F.data.startswith("check:"))
async def cb_check(callback: CallbackQuery) -> None:
    _, uid, code, dc = callback.data.split(":")
    user_id, difficulty = int(uid), int(dc)
    if callback.from_user.id != user_id:
        await callback.answer("Эту проверку делает другой игрок 🙂")
        return
    chat_id = callback.message.chat.id
    character = db.get_character(chat_id, user_id)
    if character is None or not character["alive"] or character["hp"] == 0:
        await callback.answer("Твой персонаж сейчас не может действовать.")
        return
    if code[0] == "s":
        ability = srd.ABILITIES[int(code[1:])]
        result = engine.pc_save(chat_id, character, ability, difficulty)
        text = f"🎲 <b>{esc(character['name'])}</b> — спасбросок {ability}\n{result['text']}"
        outcome = "успех" if result["success"] else "провал"
        event = f"спасбросок {ability} по запросу мастера (сложность {difficulty}): {outcome}"
    else:
        result = engine.check_roll(chat_id, character, CHECK_NAMES[int(code[1:])], difficulty)
        text, event = "\n".join(result["lines"]), result["event"]
    db.save_action(chat_id, character["name"], event, kind="event")
    await callback.answer()
    await callback.message.edit_reply_markup(
        reply_markup=_without_button(callback.message.reply_markup, callback.data)
    )
    await callback.message.answer(text)


@router.message(Command("do"))
async def cmd_do(message: Message, command: CommandObject) -> None:
    text = (command.args or "").strip()
    if not text:
        await message.answer(
            "Опиши, что делает твой герой. Например:\n"
            "/do крадусь вдоль стены к двери и слушаю, что за ней"
        )
        return
    if await require_world(message) is None:
        return
    character = await require_character(message, need_conscious=True)
    if character is None:
        return
    if db.current_situation_number(message.chat.id) == 0:
        await message.answer("Сначала начните приключение: /scene")
        return
    text = text[:1000]
    db.save_action(message.chat.id, character["name"], text)
    await _post_in_character(message, f"🗣 <b>{esc(character['name'])}</b>: {esc(text)}")


async def _say(message: Message, text: str) -> None:
    text = text.strip().strip('"«»“”').strip()
    if not text:
        await message.answer("Что говорит твой герой? /say Опустите оружие, мы пришли с миром")
        return
    if await require_world(message) is None:
        return
    character = await require_character(message, need_conscious=True)
    if character is None:
        return
    text = text[:1000]
    if db.current_situation_number(message.chat.id) > 0:
        db.save_action(message.chat.id, character["name"], f"говорит: «{text}»")
    await _post_in_character(message, f"💬 <b>{esc(character['name'])}</b>: «{esc(text)}»")


@router.message(Command("say"))
async def cmd_say(message: Message, command: CommandObject) -> None:
    await _say(message, command.args or "")


@router.message(F.text.startswith(QUOTE_PREFIXES))
async def quoted_speech(message: Message) -> None:
    """Сообщение, начинающееся с кавычки, — реплика персонажа без команды."""
    if db.get_character(message.chat.id, message.from_user.id) is None:
        return
    await _say(message, message.text)


@router.message(Command("party"))
async def cmd_party(message: Message) -> None:
    if await require_world(message) is None:
        return
    card = party_card(message.chat.id)
    await message.answer(card or "В отряде пока никого. Создать персонажа: /hero")


@router.message(Command("actions"))
async def cmd_actions(message: Message) -> None:
    pending = db.pending_actions(message.chat.id)
    actions = [a for a in pending if a["kind"] == "action"]
    events = [a for a in pending if a["kind"] == "event"]
    if not actions and not events:
        await message.answer("После последней сцены ничего не заявлено. Используй /do <действие>")
        return
    lines = []
    if actions:
        lines += ["🗣 <b>Заявленные действия:</b>"]
        lines += [f"• <b>{esc(a['character_name'])}</b>: {esc(a['text'])}" for a in actions]
    if events:
        lines += ["", "📋 <b>События (учтутся в сцене):</b>"]
        lines += [f"• {esc(e['character_name'])}: {esc(e['text'])}" for e in events[-10:]]
    lines += ["", "Когда все готовы — /scene"]
    await answer_long(message, "\n".join(lines))


@router.message(Command("npc"))
async def cmd_npc(message: Message) -> None:
    game = await require_world(message)
    if game is None:
        return
    note = await message.answer("🧙 Придумываю NPC…")
    existing = [n["name"] for n in db.list_npcs(message.chat.id)]
    text = await generate(
        note, ai.generate_npc(game["theme"], game["world_desc"], existing, game["tone"]),
        "придумать NPC",
    )
    if text is None:
        return
    name = text.split("\n", 1)[0].strip("*# ").strip()[:100]
    db.save_npc(message.chat.id, name, text)
    db.add_fact(message.chat.id, db.current_situation_number(message.chat.id), f"В мире появился NPC: {name}")
    await edit_long(note, f"🧙 <b>Новый NPC</b>\n\n{esc(text)}")


@router.message(Command("recap"))
async def cmd_recap(message: Message) -> None:
    game = await require_world(message)
    if game is None:
        return
    if db.current_situation_number(message.chat.id) == 0:
        await message.answer("Приключение ещё не началось — пересказывать нечего. Начните: /scene")
        return
    note = await message.answer("📖 Вспоминаю, что было…")
    recent = [s["text"] for s in db.list_situations(message.chat.id, 3)]
    facts = [f["text"] for f in db.list_facts(message.chat.id)]
    text = await generate(
        note,
        ai.generate_recap(game["theme"], game["summary"], recent, facts, game["location"], game["tone"]),
        "составить пересказ",
    )
    if text is None:
        return
    await edit_long(note, f"📖 <b>В предыдущих сериях</b>\n\n{esc(text)}")


@router.message(Command("journal"))
async def cmd_journal(message: Message) -> None:
    game = await require_world(message)
    if game is None:
        return
    lines = ["📓 <b>Журнал</b>"]
    lines.append(f"📍 Местоположение: {esc(game['location']) if game['location'] else 'неизвестно'}")
    facts = db.list_facts(message.chat.id)
    if facts:
        lines += ["", "<b>Важное:</b>"]
        lines += [f"• {esc(f['text'])} <i>(сцена {f['situation']})</i>" for f in facts]
    else:
        lines += ["", "Важных фактов пока нет — они появятся по ходу сцен."]
    await answer_long(message, "\n".join(lines))
