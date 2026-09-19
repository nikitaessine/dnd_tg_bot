"""Кубики, проверки, спасброски, хиты, состояния, опыт и вдохновение."""

from aiogram import Router
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.filters import Command, CommandObject
from aiogram.types import Message

import db
import dice
import engine
import rules
import srd
from handlers.common import (
    answer_long,
    conditions_text,
    esc,
    hp_line,
    require_character,
    require_gm,
    require_world,
)
from handlers.turns import present

router = Router()

CHECKABLE = list(srd.SKILLS) + list(srd.ABILITIES)
ADV_WORDS = {"преимущество": 1, "adv": 1, "помеха": -1, "dis": -1}


def parse_check(args: str) -> tuple[str | None, int | None, int, str]:
    """«Ловкость 15 преимущество» → (название, сложность, режим, остаток). Название может быть None."""
    tokens = args.split()
    mode, dc, name_tokens = 0, None, []
    for token in tokens:
        low = token.casefold()
        if low in ADV_WORDS:
            mode = ADV_WORDS[low]
        elif token.isdigit() and dc is None:
            dc = max(1, min(40, int(token)))
        else:
            name_tokens.append(token)
    name = dice.match_name(" ".join(name_tokens), CHECKABLE) if name_tokens else None
    rest = " ".join(name_tokens) if name is None else ""
    return name, dc, mode, rest


@router.message(Command("roll"))
async def cmd_roll(message: Message, command: CommandObject) -> None:
    args = (command.args or "").strip()
    who = esc(message.from_user.first_name)
    if not args:
        value = dice.d20()
        await message.answer(f"🎲 {who}: d20 = <b>{value}</b>")
        return
    first = args.split()[0]
    if dice.parse_notation(first) is not None:
        total, rolls, mod = dice.roll_notation(first)
        detail = f"[{', '.join(map(str, rolls))}]" + (f" {mod:+d}" if mod else "")
        await message.answer(f"🎲 {who}: {esc(first)} → {detail} = <b>{total}</b>")
        return
    name, dc, mode, rest = parse_check(args)
    if name is None:
        await message.answer("Не понял. Примеры: /roll · /roll 2d6+1 · /roll Ловкость · /roll Скрытность 15 · "
                             "/roll Атлетика помеха")
        return
    character = await require_character(message, need_conscious=True)
    if character is None:
        return
    result = engine.check_roll(message.chat.id, character, name, dc, mode)
    db.save_action(message.chat.id, character["name"], result["event"], kind="event")
    await answer_long(message, "\n".join(result["lines"]))


@router.message(Command("sroll"))
async def cmd_sroll(message: Message, command: CommandObject) -> None:
    """Тайная проверка: результат получают игрок и мастер в личных сообщениях."""
    game = await require_world(message)
    if game is None:
        return
    name, dc, mode, _ = parse_check(command.args or "")
    if name is None:
        await message.answer("Пример: /sroll Восприятие 15")
        return
    character = await require_character(message, need_conscious=True)
    if character is None:
        return
    result = engine.check_roll(message.chat.id, character, name, dc, mode, secret=True)
    db.save_action(message.chat.id, character["name"], result["event"], kind="event")
    text = "🤫 Тайная проверка\n" + "\n".join(result["lines"])
    delivered = False
    for uid in {message.from_user.id, game["gm_user_id"]} - {None}:
        try:
            await message.bot.send_message(uid, text)
            delivered = True
        except (TelegramForbiddenError, TelegramBadRequest):
            pass
    if delivered:
        await message.answer(f"🤫 {esc(character['name'])} делает тайную проверку — результат отправлен в личку.")
    else:
        await message.answer("Не могу написать в личку — напиши боту /start в личных сообщениях.")


@router.message(Command("save"))
async def cmd_save(message: Message, command: CommandObject) -> None:
    tokens = (command.args or "").split()
    ability = dice.match_name(tokens[0], srd.ABILITIES) if tokens else None
    if ability is None:
        await message.answer("Пример: /save Ловкость 14")
        return
    dc = int(tokens[1]) if len(tokens) > 1 and tokens[1].isdigit() else None
    character = await require_character(message)
    if character is None:
        return
    if dc is None:
        result = engine.pc_save(message.chat.id, character, ability, 10)
        await message.answer(f"🎲 <b>{esc(character['name'])}</b> — спасбросок {ability}\n{result['text']}")
        return
    result = engine.pc_save(message.chat.id, character, ability, dc)
    db.save_action(message.chat.id, character["name"],
                   f"спасбросок {ability} (сл. {dc}): {'успех' if result['success'] else 'провал'}", kind="event")
    await message.answer(f"🎲 <b>{esc(character['name'])}</b> — спасбросок {ability}\n{result['text']}")


# ---------------------------------------------------------------- хиты

def _target(message: Message, args: list[str]):
    """Персонаж-цель: имя в последнем слове, иначе свой персонаж."""
    if args:
        found = db.find_character(message.chat.id, " ".join(args))
        if found is not None:
            return found
    return db.get_character(message.chat.id, message.from_user.id)


@router.message(Command("hp"))
async def cmd_hp(message: Message) -> None:
    characters = db.list_characters(message.chat.id)
    if not characters:
        await message.answer("Персонажей пока нет: /hero")
        return
    lines = [hp_line(c) + (f" · КД {engine.gear(message.chat.id, c)['ac']}" if c["alive"] else "") for c in characters]
    for i, c in enumerate(characters):
        extra = conditions_text(c)
        if extra:
            lines[i] += f"\n   ⚠️ {esc(extra)}"
    await answer_long(message, "\n".join(lines))


async def _apply_hp(message: Message, command: CommandObject, kind: str) -> None:
    tokens = (command.args or "").split()
    if not tokens or not tokens[0].isdigit():
        await message.answer(f"Пример: /{kind} 5 [имя] — сумма и, по желанию, имя персонажа")
        return
    amount = int(tokens[0])
    game = db.get_world(message.chat.id)
    target = _target(message, tokens[1:])
    if target is None:
        await message.answer("Персонаж не найден. Создай: /hero")
        return
    # чужой персонаж — только мастер; свой — можно
    if target["user_id"] != message.from_user.id and not await require_gm(message, game):
        return
    chat_id = message.chat.id
    if kind == "damage":
        lines, updated = engine.pc_damage(chat_id, target, amount, source="мастер")
        db.save_action(chat_id, target["name"], f"получает {amount} урона", kind="event")
        await present(message, chat_id, target["user_id"], lines + [hp_line(updated)])
    elif kind == "heal":
        if not target["alive"]:
            await message.answer("Мёртвых обычное лечение не возвращает (нужно воскрешение).")
            return
        gained, updated = engine.pc_heal(chat_id, target, amount)
        await message.answer(f"💚 {esc(target['name'])} восстанавливает {gained} хитов.\n{hp_line(updated)}")
    else:  # temp
        updated = db.update_character(chat_id, target["user_id"], temp_hp=max(target["temp_hp"], amount))
        await message.answer(f"🛡 {esc(target['name'])}: временные хиты {updated['temp_hp']} (не суммируются, с. 79).")


@router.message(Command("damage"))
async def cmd_damage(message: Message, command: CommandObject) -> None:
    await _apply_hp(message, command, "damage")


@router.message(Command("heal"))
async def cmd_heal(message: Message, command: CommandObject) -> None:
    await _apply_hp(message, command, "heal")


@router.message(Command("temp"))
async def cmd_temp(message: Message, command: CommandObject) -> None:
    await _apply_hp(message, command, "temp")


# ---------------------------------------------------------------- опыт, состояния, вдохновение (мастер)

@router.message(Command("xp"))
async def cmd_xp(message: Message, command: CommandObject) -> None:
    game = await require_world(message)
    if game is None or not await require_gm(message, game):
        return
    tokens = (command.args or "").split()
    if not tokens or not tokens[0].lstrip("-").isdigit():
        await message.answer("Пример: /xp 300 — разделить поровну на отряд; /xp 300 Имя — конкретному персонажу")
        return
    amount = int(tokens[0])
    if len(tokens) > 1:
        target = db.find_character(message.chat.id, " ".join(tokens[1:]))
        if target is None:
            await message.answer("Персонаж не найден.")
            return
        lines, _ = engine.grant_xp(message.chat.id, target, amount)
        await answer_long(message, "\n".join([f"✨ {esc(target['name'])}: +{amount} опыта"] + lines))
        return
    lines = engine.split_xp(message.chat.id, amount)
    await answer_long(message, "\n".join(lines) or "Нет живых персонажей.")


@router.message(Command("condition"))
async def cmd_condition(message: Message, command: CommandObject) -> None:
    game = await require_world(message)
    if game is None or not await require_gm(message, game):
        return
    tokens = (command.args or "").split()
    if len(tokens) < 2:
        await message.answer("Пример: /condition Имя отравлен · /condition Имя снять отравлен · "
                             "/condition Имя отравлен 10 (раундов)\nСостояния: " + ", ".join(srd.CONDITIONS))
        return
    chat_id = message.chat.id
    target = db.find_character(chat_id, tokens[0])
    if target is None:
        await message.answer("Персонаж не найден.")
        return
    remove = tokens[1].casefold() in ("снять", "убрать")
    words = tokens[2:] if remove else tokens[1:]
    rounds = None
    if words and words[-1].isdigit():
        rounds = int(words.pop())
    name = dice.match_name(" ".join(words), srd.CONDITIONS)
    if name is None:
        await message.answer("Не знаю такого состояния. Список: " + ", ".join(srd.CONDITIONS))
        return
    if remove:
        engine.remove_pc_condition(chat_id, target, name)
        await message.answer(f"✅ {esc(target['name'])}: состояние «{name}» снято.")
    else:
        engine.add_pc_condition(chat_id, target, name, rounds=rounds)
        await message.answer(f"⚠️ {esc(target['name'])}: {name} — {srd.CONDITIONS[name]}")


@router.message(Command("exhaustion"))
async def cmd_exhaustion(message: Message, command: CommandObject) -> None:
    game = await require_world(message)
    if game is None or not await require_gm(message, game):
        return
    tokens = (command.args or "").split()
    if len(tokens) < 2 or not tokens[-1].lstrip("+-").isdigit():
        await message.answer("Пример: /exhaustion Имя +1 (или -1, или 0 — снять)")
        return
    target = db.find_character(message.chat.id, " ".join(tokens[:-1]))
    if target is None:
        await message.answer("Персонаж не найден.")
        return
    raw = tokens[-1]
    level = int(raw) if not raw[0] in "+-" else target["exhaustion"] + int(raw)
    level = max(0, min(6, level))
    updated = db.update_character(message.chat.id, target["user_id"], exhaustion=level)
    text = f"😩 {esc(target['name'])}: истощение {level}" + (f" — {srd.EXHAUSTION[level - 1]}" if level else "")
    if level >= 6:
        lines, _ = engine.pc_damage(message.chat.id, updated, updated["max_hp"] + updated["temp_hp"] + 999,
                                    source="истощение")
        text += "\n💀 Шестой уровень истощения — смерть."
    await message.answer(text)


@router.message(Command("inspiration"))
async def cmd_inspiration(message: Message, command: CommandObject) -> None:
    game = await require_world(message)
    if game is None or not await require_gm(message, game):
        return
    target = db.find_character(message.chat.id, command.args or "")
    if target is None:
        await message.answer("Пример: /inspiration Имя — мастер награждает вдохновением (одно на персонажа).")
        return
    if target["inspiration"]:
        await message.answer(f"У {esc(target['name'])} уже есть вдохновение.")
        return
    db.update_character(message.chat.id, target["user_id"], inspiration=1)
    await message.answer(f"🌟 {esc(target['name'])} получает вдохновение! Потратить: /inspire — "
                         "преимущество на следующую проверку, атаку или спасбросок.")
