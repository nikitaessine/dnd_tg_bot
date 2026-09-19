"""Противники и бой: /enemy, /fight, /attack, /endturn, /endfight и кнопки хода."""

import re

from aiogram import F, Router
from aiogram.filters import Command, CommandObject
from aiogram.types import CallbackQuery, Message

import ai
import combat
import db
import dice
import engine
import features
import rules
import srd
from handlers.common import (
    answer_long,
    edit_long,
    esc,
    generate,
    require_character,
    require_gm,
    require_world,
)
from handlers.turns import finish_turn, next_markup, present

router = Router()

COUNT = re.compile(r"^(\d{1,2})\s*[x×хХ]\s*", re.IGNORECASE)


def parse_manual_enemy(text: str) -> dict | None:
    """«Гоблин 7 13 +3 1d6» → поля противника. Уровень опасности выбирается по хитам."""
    tokens = text.split()
    if len(tokens) < 5:
        return None
    dmg, atk, ac, hp = tokens[-1], tokens[-2], tokens[-3], tokens[-4]
    name = " ".join(tokens[:-4])
    if not (hp.isdigit() and ac.isdigit() and atk.lstrip("+-").isdigit() and dice.parse_notation(dmg)):
        return None
    cr = srd.default_cr_for_hp(int(hp))
    return {"name": name[:60], "hp": max(1, min(int(hp), 999)), "armor_class": max(1, min(int(ac), 30)),
            "attack_bonus": int(atk), "damage_dice": dmg.lower(), "cr": cr, "xp": srd.CR_TABLE[cr][1]}


@router.message(Command("enemy"))
async def cmd_enemy(message: Message, command: CommandObject) -> None:
    game = await require_world(message)
    if game is None or not await require_gm(message, game):
        return
    text = (command.args or "").strip()
    if not text:
        await message.answer("Опиши противника: /enemy болотный тролль\nНесколько одинаковых: /enemy 3x гоблины-лучники\n"
                             "Вручную: /enemy Гоблин 7 13 +3 1d6 (хиты, КД, атака, урон)")
        return
    chat_id = message.chat.id
    count = 1
    m = COUNT.match(text)
    if m:
        count, text = max(1, min(int(m.group(1)), 8)), text[m.end():].strip()
    fields = parse_manual_enemy(text)
    note = None
    if fields is None:
        note = await message.answer("👹 Придумываю противника…")
        party = db.list_characters(chat_id, alive_only=True)
        level = max((c["level"] for c in party), default=1)
        fields = await generate(
            note, ai.generate_enemy(game["theme"], game["world_desc"], text, level, max(1, len(party)),
                                    game["difficulty"], game["tone"]), "придумать противника")
        if fields is None:
            return
    created = [db.save_enemy(chat_id, **fields) for _ in range(count)]
    lines = ["👹 <b>Появляется противник:</b>" if count == 1 else "👹 <b>Появляются противники:</b>"]
    for e in created:
        lines.append(f"• <b>{esc(e['name'])}</b> — {e['hp']} HP, КД {e['armor_class']}, атака "
                     f"{rules.format_modifier(e['attack_bonus'])}, урон {e['damage_dice']}"
                     + (f" ×{e['attacks']}" if e["attacks"] > 1 else "")
                     + f", уровень опасности {srd.cr_label(e['cr'])} ({e['xp']} опыта)")
    if fields.get("description"):
        lines.append(esc(fields["description"]))
    if fields.get("effect_condition"):
        lines.append(f"Эффект попадания: {fields['effect_condition']} (спасбросок {fields['effect_ability']} "
                     f"сл. {fields['effect_dc']})")
    lines.append(engine.format_difficulty(engine.encounter_difficulty(chat_id)))
    lines.append("Начать бой: /fight")
    text_out = "\n".join(l for l in lines if l)
    if note is not None:
        await edit_long(note, text_out)
    else:
        await answer_long(message, text_out)


@router.message(Command("enemies"))
async def cmd_enemies(message: Message) -> None:
    enemies = db.list_enemies(message.chat.id)
    if not enemies:
        await message.answer("Противников нет. Мастер: /enemy &lt;описание&gt;")
        return
    lines = ["👹 <b>Противники</b>"]
    for e in enemies:
        conds = ", ".join(sorted(rules.cond_names(engine.enemy_conditions(e))))
        lines.append(f"• {esc(e['name'])}: {e['hp']}/{e['max_hp']} HP, КД {e['armor_class']}"
                     + (f" · {esc(conds)}" if conds else ""))
    lines.append(engine.format_difficulty(engine.encounter_difficulty(message.chat.id)))
    await answer_long(message, "\n".join(l for l in lines if l))


@router.message(Command("fight"))
async def cmd_fight(message: Message) -> None:
    game = await require_world(message)
    if game is None or not await require_gm(message, game):
        return
    chat_id = message.chat.id
    if combat.in_combat(chat_id):
        await message.answer("Бой уже идёт. Порядок ходов: /order")
        return
    if not db.list_enemies(chat_id):
        await message.answer("Нет противников. Сначала: /enemy &lt;описание&gt;")
        return
    if not db.list_characters(chat_id, alive_only=True):
        await message.answer("В отряде нет героев: /hero")
        return
    combat.start(chat_id)
    lines = ["⚔️ <b>Бой начинается!</b>", combat.format_order(chat_id), ""]
    more, over = combat.run_until_player(chat_id)
    await answer_long(message, "\n".join(lines + more), None if over else next_markup(chat_id))


@router.message(Command("order"))
async def cmd_order(message: Message) -> None:
    if not combat.in_combat(message.chat.id):
        await message.answer("Боя нет.")
        return
    await message.answer(combat.format_order(message.chat.id))


@router.message(Command("endfight"))
async def cmd_endfight(message: Message) -> None:
    game = await require_world(message)
    if game is None or not await require_gm(message, game):
        return
    if not combat.in_combat(message.chat.id):
        await message.answer("Боя нет.")
        return
    lines = combat.end(message.chat.id, "прекращён мастером")
    await answer_long(message, "\n".join(["🏳️ Бой прекращён."] + lines))


async def do_attack(message: Message, chat_id: int, character, query: str) -> None:
    error = combat.turn_error(chat_id, character["user_id"])
    if error:
        await message.answer(error)
        return
    enemies = db.list_enemies(chat_id)
    if not enemies:
        await message.answer("Некого атаковать.")
        return
    enemy = db.find_enemy(chat_id, query) if query else (enemies[0] if len(enemies) == 1 else None)
    if enemy is None:
        await message.answer("Кого атаковать? " + ", ".join(esc(e["name"]) for e in enemies)
                             + "\nПример: /attack Гоблин")
        return
    problem = combat.use_action(chat_id, character["user_id"], haste_ok=True)
    if problem:
        await message.answer(problem)
        return
    lines, _ = combat.attack_action(chat_id, character, enemy)
    await present(message, chat_id, character["user_id"], lines)


@router.message(Command("attack"))
async def cmd_attack(message: Message, command: CommandObject) -> None:
    character = await require_character(message, need_conscious=True)
    if character is None:
        return
    await do_attack(message, message.chat.id, character, (command.args or "").strip())


@router.message(Command("endturn", "pass"))
async def cmd_endturn(message: Message) -> None:
    chat_id = message.chat.id
    if not combat.in_combat(chat_id):
        await message.answer("Боя нет.")
        return
    error = combat.turn_error(chat_id, message.from_user.id)
    if error:
        await message.answer(error)
        return
    await finish_turn(message, chat_id, [])


# ---------------------------------------------------------------- кнопки

async def _guard(callback: CallbackQuery, uid: int):
    if callback.from_user.id != uid:
        await callback.answer("Сейчас не твой ход 🙂")
        return None
    character = db.get_character(callback.message.chat.id, uid)
    if character is None or not character["alive"] or character["hp"] == 0:
        await callback.answer("Твой персонаж не может действовать.")
        return None
    if combat.turn_error(callback.message.chat.id, uid):
        await callback.answer("Сейчас не твой ход 🙂")
        return None
    return character


@router.callback_query(F.data.startswith("atk:"))
async def cb_attack(callback: CallbackQuery) -> None:
    _, uid_s, eid_s = callback.data.split(":")
    character = await _guard(callback, int(uid_s))
    if character is None:
        return
    enemy = db.get_enemy(int(eid_s))
    if enemy is None or not enemy["alive"]:
        await callback.answer("Этот противник уже повержен.")
        return
    await callback.answer()
    await callback.message.edit_reply_markup(reply_markup=None)
    await do_attack(callback.message, callback.message.chat.id, character, enemy["name"])


@router.callback_query(F.data.startswith("act:"))
async def cb_action(callback: CallbackQuery) -> None:
    _, uid_s, key = callback.data.split(":")
    character = await _guard(callback, int(uid_s))
    if character is None:
        return
    chat_id = callback.message.chat.id
    await callback.answer()
    message = callback.message
    if key == "end":
        await message.edit_reply_markup(reply_markup=None)
        await finish_turn(message, chat_id, [])
        return
    if key == "spells":
        from handlers.magic import spells_lines
        await message.answer("\n".join(spells_lines(character)) + "\n\nКолдовать: /cast &lt;название&gt; [ячейка] [цель]")
        return
    actions = {
        "dodge": lambda: features.dodge(chat_id, character),
        "hide": lambda: features.hide(chat_id, character),
        "sw": lambda: features.second_wind(chat_id, character),
        "surge": lambda: features.action_surge(chat_id, character),
        "cun_dash": lambda: features.cunning_action(chat_id, character, "рывок"),
        "cun_dis": lambda: features.cunning_action(chat_id, character, "отход"),
        "cun_hide": lambda: features.cunning_action(chat_id, character, "скрыться"),
    }
    ok, lines = actions[key]()
    if not ok:
        await message.answer("\n".join(lines))
        return
    await message.edit_reply_markup(reply_markup=None)
    await present(message, chat_id, character["user_id"], lines)
