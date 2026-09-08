"""Кубики, здоровье, опыт, предметы, противники и бой."""

import re

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.filters import Command, CommandObject
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

import ai
import combat
import db
import dice
import rules
from config import ATTRIBUTES
from handlers.common import (
    answer_long,
    esc,
    generate,
    hp_line,
    is_gm,
    require_character,
    require_gm,
    require_world,
)

router = Router()


# ---------------------------------------------------------------- проверки атрибутов

def _check(character, attribute: str, difficulty: int | None) -> tuple[list[str], str]:
    """Проверка атрибута. Возвращает (строки для чата, текст события для журнала)."""
    bonus, proficient = rules.check_bonus(character, attribute)
    value, total = dice.d20_check(bonus)
    lines = [
        f"🎲 <b>{esc(character['name'])}</b> — проверка: {attribute}",
        f"d20: {value} {rules.format_modifier(bonus)}"
        + (" (мастерство)" if proficient else "") + f" = <b>{total}</b>",
    ]
    if value == 20:
        lines.append("💥 Критический успех!")
    elif value == 1:
        lines.append("💀 Критический провал!")
    event = f"проверка {attribute}: {total}"
    if difficulty is not None:
        success = value == 20 or (value != 1 and total >= difficulty)
        lines.append(("✅ Успех" if success else "❌ Провал") + f" (сложность {difficulty})")
        event = f"проверка {attribute} (сложность {difficulty}): {total} — {'успех' if success else 'провал'}"
    return lines, event


async def _parse_check_args(message: Message, args: list[str]) -> tuple[str, int | None] | None:
    attribute = dice.match_attribute(args[0], ATTRIBUTES)
    if attribute is None:
        await message.answer("Не знаю такого атрибута. Доступные: " + ", ".join(ATTRIBUTES))
        return None
    difficulty = None
    if len(args) > 1:
        try:
            difficulty = int(args[1])
        except ValueError:
            await message.answer("Сложность должна быть числом, например: /roll Сила 15")
            return None
    return attribute, difficulty


@router.message(Command("roll"))
async def cmd_roll(message: Message, command: CommandObject) -> None:
    args = (command.args or "").split()
    own = db.get_character(message.chat.id, message.from_user.id)
    who = esc(own["name"] if own else message.from_user.first_name)
    if not args:
        await message.answer(f"🎲 {who} бросает d20: <b>{dice.d20()}</b>")
        return
    rolled = dice.roll_notation(args[0])
    if rolled is not None:
        total, results, modifier = rolled
        detail = " + ".join(map(str, results))
        if modifier:
            detail += f" {rules.format_modifier(modifier)}"
        await message.answer(f"🎲 {who} бросает {esc(args[0])}: <b>{total}</b> ({detail})")
        return
    character = await require_character(message)
    if character is None:
        return
    parsed = await _parse_check_args(message, args)
    if parsed is None:
        return
    lines, event = _check(character, *parsed)
    db.save_action(message.chat.id, character["name"], event, kind="event")
    await message.answer("\n".join(lines))


@router.message(Command("sroll"))
async def cmd_secret_roll(message: Message, command: CommandObject) -> None:
    args = (command.args or "").split()
    if not args:
        await message.answer("Тайная проверка: /sroll Мудрость 15")
        return
    game = await require_world(message)
    if game is None:
        return
    character = await require_character(message)
    if character is None:
        return
    parsed = await _parse_check_args(message, args)
    if parsed is None:
        return
    lines, event = _check(character, *parsed)
    db.save_action(message.chat.id, character["name"], event, kind="secret")
    if message.chat.type == "private":
        await message.answer("\n".join(lines))
        return
    text = "🤫 <b>Тайная проверка</b>\n" + "\n".join(lines)
    recipients = {message.from_user.id}
    if game["gm_user_id"] is not None:
        recipients.add(game["gm_user_id"])
    failed = []
    for user_id in recipients:
        try:
            await message.bot.send_message(user_id, text)
        except (TelegramForbiddenError, TelegramBadRequest):
            failed.append(user_id)
    note = f"🤫 <b>{esc(character['name'])}</b> делает тайную проверку: {parsed[0]}"
    if message.from_user.id in failed:
        note += "\n⚠️ Не могу написать тебе в личку — открой чат с ботом и нажми /start."
    elif failed:
        note += "\n⚠️ Мастеру не доставлено: ему нужно открыть личный чат с ботом."
    await message.answer(note)


# ---------------------------------------------------------------- здоровье и опыт

@router.message(Command("hp"))
async def cmd_hp(message: Message) -> None:
    characters = db.list_characters(message.chat.id)
    if not characters:
        await message.answer("В этой кампании ещё нет персонажей. Создай своего: /hero")
        return
    lines = ["❤️ <b>Состояние отряда:</b>", ""]
    lines += [f"• {hp_line(c)} — {c['level']} ур." for c in characters]
    await message.answer("\n".join(lines))


async def _change_hp(message: Message, command: CommandObject, sign: int) -> None:
    args = (command.args or "").split()
    cmd = "damage" if sign < 0 else "heal"
    if not args:
        await message.answer(f"Укажи количество: /{cmd} 5 — или для другого героя: /{cmd} 5 Гарен")
        return
    try:
        amount = int(args[0])
    except ValueError:
        await message.answer("Количество должно быть числом.")
        return
    if amount <= 0:
        await message.answer("Число должно быть больше нуля.")
        return
    chat_id = message.chat.id
    if len(args) > 1:
        target = db.find_character(chat_id, " ".join(args[1:]))
        if target is None:
            await message.answer("Не нашёл такого персонажа. Список — /hp")
            return
        if target["user_id"] != message.from_user.id and not is_gm(message, db.get_world(chat_id)):
            await message.answer("⛔ Менять здоровье другим может только мастер игры.")
            return
    else:
        target = await require_character(message)
        if target is None:
            return
    if not target["alive"]:
        await message.answer(f"⚰️ {esc(target['name'])} погиб.")
        return
    before = target["hp"]
    updated = db.adjust_hp(chat_id, target["user_id"], sign * amount)
    actual = abs(updated["hp"] - before)
    if sign < 0:
        lines = [f"⚔️ <b>{esc(updated['name'])}</b> получает {actual} урона"]
        db.save_action(chat_id, updated["name"], f"получает {actual} урона (осталось {updated['hp']} HP)", kind="event")
    else:
        lines = [f"✨ <b>{esc(updated['name'])}</b> восстанавливает {actual} здоровья"]
        db.save_action(chat_id, updated["name"], f"восстанавливает {actual} здоровья ({updated['hp']} HP)", kind="event")
    lines.append(hp_line(updated))
    if updated["hp"] == 0:
        lines.append("\n💀 Персонаж без сознания и не может действовать. Нужна помощь!")
    elif before == 0 and updated["hp"] > 0:
        lines.append("\n🌅 Персонаж приходит в себя!")
    await message.answer("\n".join(lines))


@router.message(Command("damage"))
async def cmd_damage(message: Message, command: CommandObject) -> None:
    await _change_hp(message, command, -1)


@router.message(Command("heal"))
async def cmd_heal(message: Message, command: CommandObject) -> None:
    await _change_hp(message, command, 1)


@router.message(Command("xp"))
async def cmd_xp(message: Message, command: CommandObject) -> None:
    game = await require_world(message)
    if game is None or not await require_gm(message, game):
        return
    try:
        amount = int((command.args or "").split()[0])
    except (IndexError, ValueError):
        await message.answer("Сколько опыта выдать всем? Например: /xp 50")
        return
    if amount <= 0:
        await message.answer("Число должно быть больше нуля.")
        return
    lines = [f"✨ <b>Опыт: +{amount} каждому</b>"]
    for c in db.list_characters(message.chat.id, alive_only=True):
        result = rules.apply_xp(c, amount)
        db.update_character(
            message.chat.id, c["user_id"],
            level=result["level"], xp=result["xp"], max_hp=result["max_hp"], hp=result["hp"],
        )
        line = f"• {esc(c['name'])}: {result['xp']}/{rules.xp_needed(result['level'])}"
        if result["gained"]:
            line += f" — 🎉 <b>{result['level']} уровень!</b> ({result['max_hp']} HP)"
            db.save_action(message.chat.id, c["name"], f"достигает {result['level']} уровня", kind="event")
        lines.append(line)
    await message.answer("\n".join(lines))


# ---------------------------------------------------------------- предметы

@router.message(Command("take"))
async def cmd_take(message: Message, command: CommandObject) -> None:
    args = (command.args or "").split()
    if not args:
        await message.answer("Что взять? /take Меч 1d8 · /take Кольчуга +2 · /take Верёвка")
        return
    character = await require_character(message)
    if character is None:
        return
    kind, value, name = "item", "", " ".join(args)
    if len(args) >= 2:
        last = args[-1]
        if dice.parse_notation(last) is not None:
            kind, value, name = "weapon", last.lower(), " ".join(args[:-1])
        elif re.fullmatch(r"\+\d+", last):
            kind, value, name = "armor", str(min(10, int(last[1:]))), " ".join(args[:-1])
    name = name[:60]
    item = db.add_item(message.chat.id, character["user_id"], name, kind, value)
    label = {"weapon": f"оружие, урон {value}", "armor": f"доспех, +{value} к КД", "item": "предмет"}[kind]
    hint = ""
    if kind in ("weapon", "armor") and db.equipped_item(message.chat.id, character["user_id"], kind) is None:
        db.equip_item(message.chat.id, character["user_id"], item["id"], kind)
        hint = " и сразу экипирует"
    db.save_action(message.chat.id, character["name"], f"берёт {name}", kind="event")
    await message.answer(f"🎒 <b>{esc(character['name'])}</b> берёт {esc(name)} ({label}){hint}.")


@router.message(Command("drop"))
async def cmd_drop(message: Message, command: CommandObject) -> None:
    query = (command.args or "").strip()
    character = await require_character(message)
    if character is None:
        return
    item = db.find_item(message.chat.id, character["user_id"], query) if query else None
    if item is None:
        await message.answer("Не нашёл такого предмета. Список — /inventory")
        return
    db.delete_item(item["id"])
    await message.answer(f"🗑 <b>{esc(character['name'])}</b> избавляется от: {esc(item['name'])}")


@router.message(Command("equip"))
async def cmd_equip(message: Message, command: CommandObject) -> None:
    query = (command.args or "").strip()
    character = await require_character(message)
    if character is None:
        return
    item = db.find_item(message.chat.id, character["user_id"], query) if query else None
    if item is None:
        await message.answer("Не нашёл такого предмета. Список — /inventory")
        return
    if item["kind"] not in ("weapon", "armor"):
        await message.answer("Экипировать можно только оружие и доспехи.")
        return
    db.equip_item(message.chat.id, character["user_id"], item["id"], item["kind"])
    await message.answer(f"🛡 <b>{esc(character['name'])}</b> экипирует: {esc(item['name'])}")


@router.message(Command("inventory"))
async def cmd_inventory(message: Message) -> None:
    character = await require_character(message)
    if character is None:
        return
    items = db.list_items(message.chat.id, character["user_id"])
    if not items:
        await message.answer(f"🎒 У {esc(character['name'])} пусто. Взять предмет: /take Меч 1d8")
        return
    lines = [f"🎒 <b>Инвентарь {esc(character['name'])}:</b>"]
    for it in items:
        detail = {"weapon": f" — урон {it['value']}", "armor": f" — +{it['value']} к КД"}.get(it["kind"], "")
        mark = " ✅" if it["equipped"] else ""
        lines.append(f"• {esc(it['name'])}{detail}{mark}")
    await message.answer("\n".join(lines))


@router.message(Command("loot"))
async def cmd_loot(message: Message, command: CommandObject) -> None:
    game = await require_world(message)
    if game is None or not await require_gm(message, game):
        return
    context = (command.args or "").strip() or "отряд только что победил в бою"
    note = await message.answer("💰 Смотрю, что осталось…")
    items = await generate(
        note, ai.generate_loot(game["theme"], game["world_desc"], context, game["tone"]),
        "придумать добычу",
    )
    if items is None:
        return
    lines = ["💰 <b>Добыча:</b>", ""]
    for it in items:
        suffix = f" {it.value}" if it.kind == "weapon" else (f" +{it.value}" if it.kind == "armor" else "")
        lines.append(f"• <b>{esc(it.name)}</b> — {esc(it.description)}")
        lines.append(f"  взять: <code>/take {esc(it.name)}{suffix}</code>")
    db.add_fact(message.chat.id, db.current_situation_number(message.chat.id),
                "Найдена добыча: " + ", ".join(it.name for it in items))
    await note.edit_text("\n".join(lines))


# ---------------------------------------------------------------- противники

def _enemy_card(e) -> str:
    return (
        f"👹 <b>{esc(e['name'])}</b> — {e['hp']}/{e['max_hp']} HP, КД {e['armor_class']}, "
        f"атака {rules.format_modifier(e['attack_bonus'])}, урон {esc(e['damage_dice'])}"
    )


@router.message(Command("enemy"))
async def cmd_enemy(message: Message, command: CommandObject) -> None:
    game = await require_world(message)
    if game is None or not await require_gm(message, game):
        return
    args = (command.args or "").split()
    if not args:
        await message.answer(
            "Опиши противника: /enemy старый гоблин-шаман\n"
            "Или задай вручную: /enemy Гоблин 7 13 +3 1d6  (имя, HP, КД, атака, урон)"
        )
        return
    chat_id = message.chat.id
    first_number = next((i for i, a in enumerate(args) if a.lstrip("-").isdigit()), None)
    if first_number and first_number + 1 < len(args) and args[first_number + 1].isdigit():
        name = " ".join(args[:first_number])[:60]
        hp, ac = int(args[first_number]), int(args[first_number + 1])
        rest = args[first_number + 2:]
        attack = int(rest[0]) if rest and re.fullmatch(r"[+-]?\d+", rest[0]) else 2
        damage = rest[1] if len(rest) > 1 and dice.parse_notation(rest[1]) else "1d6"
        enemy = db.save_enemy(
            chat_id, name=name, hp=max(1, hp), armor_class=ac, attack_bonus=attack,
            damage_dice=damage.lower(), xp=max(10, hp * 3),
        )
        db.save_action(chat_id, "Мастер", f"появляется противник: {enemy['name']}", kind="event")
        await message.answer(_enemy_card(enemy) + "\n\nНачать бой: /fight")
        return

    note = await message.answer("👹 Придумываю противника…")
    party = db.list_characters(chat_id, alive_only=True)
    level = round(sum(c["level"] for c in party) / len(party)) if party else 1
    block = await generate(
        note,
        ai.generate_enemy(
            game["theme"], game["world_desc"], " ".join(args), level, max(1, len(party)),
            game["difficulty"], game["tone"],
        ),
        "придумать противника",
    )
    if block is None:
        return
    enemy = db.save_enemy(chat_id, **block.model_dump())
    db.save_action(chat_id, "Мастер", f"появляется противник: {enemy['name']}", kind="event")
    await note.edit_text(
        _enemy_card(enemy) + f"\n{esc(enemy['description'])}\n\nНачать бой: /fight"
    )


@router.message(Command("enemies"))
async def cmd_enemies(message: Message) -> None:
    enemies = db.list_enemies(message.chat.id)
    if not enemies:
        await message.answer("Противников нет. Мастер добавляет их командой /enemy <описание>")
        return
    await message.answer("\n".join(_enemy_card(e) for e in enemies))


# ---------------------------------------------------------------- бой

def turn_keyboard(chat_id: int, user_id: int) -> InlineKeyboardMarkup | None:
    rows = [
        [InlineKeyboardButton(text=f"⚔️ {e['name']}"[:60], callback_data=f"atk:{user_id}:{e['id']}")]
        for e in db.list_enemies(chat_id)
    ]
    rows.append([InlineKeyboardButton(text="⏭ Пропустить ход", callback_data=f"pass:{user_id}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _turn_error(chat_id: int, user_id: int) -> str | None:
    """None, если бой не идёт или сейчас ход этого игрока; иначе текст отказа."""
    if db.get_combat(chat_id) is None:
        return None
    actor = combat.current_actor(chat_id)
    if actor and actor["type"] == "pc" and actor["user_id"] == user_id:
        return None
    return f"⏳ Сейчас ход: {esc(actor['name']) if actor else '…'}"


async def _finish_player_turn(message: Message, chat_id: int, lines: list[str]) -> None:
    combat.advance(chat_id)
    more, over = combat.run_until_player(chat_id)
    lines += more
    markup = None
    if not over:
        actor = combat.current_actor(chat_id)
        if actor and actor["type"] == "pc":
            markup = turn_keyboard(chat_id, actor["user_id"])
    await answer_long(message, "\n".join(lines), markup)


async def _do_attack(message: Message, chat_id: int, character, enemy) -> None:
    lines, defeated = combat.player_attack(chat_id, character, enemy)
    if defeated:
        lines += combat.award_xp(chat_id, enemy)
    if db.get_combat(chat_id) is not None:
        await _finish_player_turn(message, chat_id, lines)
    else:
        await answer_long(message, "\n".join(lines))


@router.message(Command("fight"))
async def cmd_fight(message: Message) -> None:
    game = await require_world(message)
    if game is None or not await require_gm(message, game):
        return
    chat_id = message.chat.id
    if db.get_combat(chat_id) is not None:
        await message.answer("Бой уже идёт.\n" + combat.format_order(chat_id))
        return
    if not db.list_enemies(chat_id):
        await message.answer("Нет противников. Сначала /enemy <описание>")
        return
    if not [c for c in db.list_characters(chat_id, alive_only=True) if c["hp"] > 0]:
        await message.answer("Некому сражаться: нет живых персонажей в сознании.")
        return
    combat.start(chat_id)
    lines = [combat.format_order(chat_id), ""]
    await _finish_first_turns(message, chat_id, lines)


async def _finish_first_turns(message: Message, chat_id: int, lines: list[str]) -> None:
    more, over = combat.run_until_player(chat_id)
    lines += more
    markup = None
    if not over:
        actor = combat.current_actor(chat_id)
        if actor and actor["type"] == "pc":
            markup = turn_keyboard(chat_id, actor["user_id"])
    await answer_long(message, "\n".join(lines), markup)


@router.message(Command("attack"))
async def cmd_attack(message: Message, command: CommandObject) -> None:
    query = (command.args or "").strip()
    character = await require_character(message, need_conscious=True)
    if character is None:
        return
    chat_id = message.chat.id
    enemies = db.list_enemies(chat_id)
    if not enemies:
        await message.answer("Сражаться не с кем. Мастер добавляет противников: /enemy")
        return
    enemy = db.find_enemy(chat_id, query) if query else (enemies[0] if len(enemies) == 1 else None)
    if enemy is None:
        await message.answer("Кого атаковать? " + ", ".join(esc(e["name"]) for e in enemies))
        return
    error = _turn_error(chat_id, message.from_user.id)
    if error:
        await message.answer(error)
        return
    await _do_attack(message, chat_id, character, enemy)


@router.message(Command("pass"))
async def cmd_pass(message: Message) -> None:
    chat_id = message.chat.id
    if db.get_combat(chat_id) is None:
        await message.answer("Сейчас нет боя.")
        return
    character = await require_character(message)
    if character is None:
        return
    error = _turn_error(chat_id, message.from_user.id)
    if error:
        await message.answer(error)
        return
    combat.log(chat_id, character["name"], "пропускает ход")
    await _finish_player_turn(message, chat_id, [f"⏭ <b>{esc(character['name'])}</b> пропускает ход"])


@router.message(Command("endfight"))
async def cmd_endfight(message: Message) -> None:
    game = await require_world(message)
    if game is None or not await require_gm(message, game):
        return
    if db.get_combat(message.chat.id) is None:
        await message.answer("Сейчас нет боя.")
        return
    combat.end(message.chat.id, "прерван мастером")
    await message.answer("🏳 Бой завершён мастером. Оставшиеся противники сохранены (/enemies).")


@router.callback_query(F.data.startswith("atk:"))
async def cb_attack(callback: CallbackQuery) -> None:
    _, uid, eid = callback.data.split(":")
    user_id, enemy_id = int(uid), int(eid)
    if callback.from_user.id != user_id:
        await callback.answer("Сейчас не твой ход 🙂")
        return
    chat_id = callback.message.chat.id
    character = db.get_character(chat_id, user_id)
    enemy = db.get_enemy(enemy_id)
    if character is None or not character["alive"] or character["hp"] == 0:
        await callback.answer("Твой персонаж не может действовать.")
        return
    if enemy is None or not enemy["alive"]:
        await callback.answer("Этот противник уже повержен.")
        return
    error = _turn_error(chat_id, user_id)
    if error:
        await callback.answer(error)
        return
    await callback.answer()
    await callback.message.edit_reply_markup(reply_markup=None)
    await _do_attack(callback.message, chat_id, character, enemy)


@router.callback_query(F.data.startswith("pass:"))
async def cb_pass(callback: CallbackQuery) -> None:
    user_id = int(callback.data.split(":")[1])
    if callback.from_user.id != user_id:
        await callback.answer("Сейчас не твой ход 🙂")
        return
    chat_id = callback.message.chat.id
    if db.get_combat(chat_id) is None:
        await callback.answer("Бой уже окончен.")
        await callback.message.edit_reply_markup(reply_markup=None)
        return
    character = db.get_character(chat_id, user_id)
    if character is None:
        await callback.answer("Персонаж не найден.")
        return
    error = _turn_error(chat_id, user_id)
    if error:
        await callback.answer(error)
        return
    await callback.answer()
    await callback.message.edit_reply_markup(reply_markup=None)
    combat.log(chat_id, character["name"], "пропускает ход")
    await _finish_player_turn(
        callback.message, chat_id, [f"⏭ <b>{esc(character['name'])}</b> пропускает ход"]
    )
