"""Ход в бою: кнопки действий и автоматическое продолжение боя после действия игрока."""

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message

import combat
import db
import rules
from engine import esc
from handlers.common import answer_long


def _btn(text: str, data: str) -> InlineKeyboardButton:
    return InlineKeyboardButton(text=text[:60], callback_data=data)


def turn_keyboard(chat_id: int, character) -> InlineKeyboardMarkup:
    """Кнопки хода: цели атаки, действия, бонусные действия и «Завершить ход»."""
    uid = character["user_id"]
    turn = combat.turn_state(chat_id)
    rows: list[list[InlineKeyboardButton]] = []
    action_free = not turn.get("action") or turn.get("haste_action")
    if action_free:
        for e in db.list_enemies(chat_id):
            rows.append([_btn(f"⚔️ {e['name']} ({e['hp']}/{e['max_hp']} HP, КД {e['armor_class']})", f"atk:{uid}:{e['id']}")])
    if not turn.get("action"):
        rows.append([_btn("🛡 Уклонение", f"act:{uid}:dodge"), _btn("🫥 Скрыться", f"act:{uid}:hide")])
    if rules.is_caster(character):
        rows.append([_btn("✨ Заклинания", f"act:{uid}:spells")])
    options = combat.bonus_options(chat_id, character)
    row: list[InlineKeyboardButton] = []
    if "secondwind" in options:
        row.append(_btn("💨 Второе дыхание", f"act:{uid}:sw"))
    if "surge" in options:
        row.append(_btn("⚡ Всплеск действий", f"act:{uid}:surge"))
    if row:
        rows.append(row)
    if "cunning" in options:
        rows.append([_btn("🏃 Рывок", f"act:{uid}:cun_dash"), _btn("🚪 Отход", f"act:{uid}:cun_dis"),
                     _btn("🫥 Скрыться", f"act:{uid}:cun_hide")])
    rows.append([_btn("⏭ Завершить ход", f"act:{uid}:end")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _hint(chat_id: int, character) -> str:
    turn = combat.turn_state(chat_id)
    options = combat.bonus_options(chat_id, character)
    parts = []
    parts.append("действие потрачено" if turn.get("action") else "действие свободно")
    parts.append("бонусное потрачено" if turn.get("bonus") else "бонусное свободно")
    if turn.get("haste_action"):
        parts.append("+действие от Ускорения (одна атака)")
    return f"▶️ <b>{esc(character['name'])}</b>: " + ", ".join(parts) + ". Что дальше?"


def next_markup(chat_id: int) -> InlineKeyboardMarkup | None:
    """Кнопки для персонажа, чей ход наступил (или None, если бой окончен / ходит противник)."""
    actor = combat.current_actor(chat_id)
    if actor and actor["type"] == "pc":
        character = db.get_character(chat_id, actor["user_id"])
        if character is not None:
            return turn_keyboard(chat_id, character)
    return None


async def present(message: Message, chat_id: int, uid: int, lines: list[str]) -> None:
    """Публикует результат действия и ведёт бой дальше: если у игрока не осталось что делать —
    завершает ход, играет противников и показывает кнопки следующему игроку."""
    lines = list(lines)
    if not combat.in_combat(chat_id):
        await answer_long(message, "\n".join(lines))
        return
    if not db.list_enemies(chat_id):
        more, _ = combat.run_until_player(chat_id)
        await answer_long(message, "\n".join(lines + more))
        return
    actor = combat.current_actor(chat_id)
    if actor and actor["type"] == "pc" and actor["user_id"] == uid:
        character = db.get_character(chat_id, uid)
        turn = combat.turn_state(chat_id)
        options = combat.bonus_options(chat_id, character) if character else []
        if character is not None and (not turn.get("action") or options):
            lines.append(_hint(chat_id, character))
            await answer_long(message, "\n".join(lines), turn_keyboard(chat_id, character))
            return
        more, over = combat.end_turn(chat_id)
        lines += more
        await answer_long(message, "\n".join(lines), None if over else next_markup(chat_id))
        return
    await answer_long(message, "\n".join(lines))


async def finish_turn(message: Message, chat_id: int, lines: list[str]) -> None:
    """Игрок явно завершает ход."""
    more, over = combat.end_turn(chat_id)
    await answer_long(message, "\n".join(list(lines) + more), None if over else next_markup(chat_id))
