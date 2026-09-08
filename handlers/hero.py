"""Создание персонажа и лист персонажа.

Черновик выбора хранится в базе, а не в памяти: создание переживает перезапуск бота,
а в кнопки зашит id владельца, так что чужие нажатия отклоняются.
"""

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

import ai
import db
import rules
from config import ATTRIBUTES, ATTRIBUTES_TO_PICK
from handlers.common import edit_long, esc, generate, hp_line, require_world

router = Router()


def attr_keyboard(user_id: int, selected: list[str]) -> InlineKeyboardMarkup:
    rows = []
    for i in range(0, len(ATTRIBUTES), 2):
        row = []
        for idx in range(i, min(i + 2, len(ATTRIBUTES))):
            attr = ATTRIBUTES[idx]
            mark = "✅ " if attr in selected else ""
            row.append(
                InlineKeyboardButton(text=f"{mark}{attr}", callback_data=f"attr:{user_id}:{idx}")
            )
        rows.append(row)
    if len(selected) == ATTRIBUTES_TO_PICK:
        rows.append([InlineKeyboardButton(text="➡️ Готово", callback_data=f"done:{user_id}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def _owner(callback: CallbackQuery, user_id: int) -> bool:
    if callback.from_user.id != user_id:
        await callback.answer("Это не твоё меню создания персонажа 🙂")
        return False
    return True


def sheet_text(chat_id: int, character) -> str:
    weapon = db.equipped_item(chat_id, character["user_id"], "weapon")
    armor = db.equipped_item(chat_id, character["user_id"], "armor")
    armor_bonus = int(armor["value"]) if armor else 0
    attack, attack_attr = rules.attack_bonus(character)
    lines = [
        f"📜 <b>{esc(character['name'])}</b> — {character['level']} уровень",
        esc(character["description"]),
        "",
        hp_line(character),
        f"🛡 Класс доспеха: {rules.armor_class(character, armor_bonus)}"
        + (f" ({esc(armor['name'])} +{armor_bonus})" if armor else ""),
        f"⚔️ Атака: {rules.format_modifier(attack)} ({attack_attr}), "
        + (f"оружие {esc(weapon['name'])} {esc(weapon['value'])}" if weapon else "без оружия 1d4"),
        f"✨ Опыт: {character['xp']}/{rules.xp_needed(character['level'])}",
        f"🎓 Мастерство: +{rules.proficiency(character['level'])} (★ — атрибуты с мастерством)",
        "",
        f"<pre>{rules.format_stats(character)}</pre>",
        f"Игрок: {esc(character['user_name'])}",
    ]
    return "\n".join(lines)


@router.message(Command("hero"))
async def cmd_hero(message: Message) -> None:
    if await require_world(message) is None:
        return
    chat_id, user = message.chat.id, message.from_user
    existing = db.get_character(chat_id, user.id)
    if existing is not None and existing["alive"]:
        await message.answer(
            "У тебя уже есть персонаж в этой кампании. Посмотреть — /sheet, удалить — /delete_hero."
        )
        return
    if existing is not None:
        # Погибший герой освобождает место для нового
        db.delete_character(chat_id, user.id)
    db.set_draft(chat_id, user.id, "attrs", [], [])
    await message.answer(
        f"⚔️ {esc(user.first_name)}, выбери {ATTRIBUTES_TO_PICK} главных атрибута "
        "своего персонажа:",
        reply_markup=attr_keyboard(user.id, []),
    )


@router.callback_query(F.data.startswith("attr:"))
async def cb_toggle_attr(callback: CallbackQuery) -> None:
    _, uid, idx = callback.data.split(":")
    user_id, index = int(uid), int(idx)
    if not await _owner(callback, user_id):
        return
    draft = db.get_draft(callback.message.chat.id, user_id)
    if draft is None or draft["stage"] != "attrs":
        await callback.answer("Это меню устарело. Начни заново: /hero")
        return
    attr = ATTRIBUTES[index]
    selected = draft["selected"]
    if attr in selected:
        selected.remove(attr)
    elif len(selected) < ATTRIBUTES_TO_PICK:
        selected.append(attr)
    else:
        await callback.answer(f"Можно выбрать только {ATTRIBUTES_TO_PICK} атрибута.")
        return
    db.set_draft(callback.message.chat.id, user_id, "attrs", selected, [])
    await callback.message.edit_reply_markup(reply_markup=attr_keyboard(user_id, selected))
    await callback.answer()


@router.callback_query(F.data.startswith("done:"))
async def cb_attrs_done(callback: CallbackQuery) -> None:
    user_id = int(callback.data.split(":")[1])
    if not await _owner(callback, user_id):
        return
    chat_id = callback.message.chat.id
    draft = db.get_draft(chat_id, user_id)
    if draft is None or draft["stage"] != "attrs":
        await callback.answer("Это меню устарело. Начни заново: /hero")
        return
    selected = draft["selected"]
    if len(selected) != ATTRIBUTES_TO_PICK:
        await callback.answer(f"Выбери ровно {ATTRIBUTES_TO_PICK} атрибута.")
        return
    game = db.get_world(chat_id)
    if game is None:
        await callback.answer("Мир исчез. Создайте его заново: /world")
        return
    await callback.answer()
    await callback.message.edit_text(
        f"🎭 Атрибуты: {', '.join(selected)}\nГенерирую варианты персонажа…"
    )
    options = await generate(
        callback.message,
        ai.generate_character_options(
            game["theme"], game["world_desc"], selected,
            db.taken_character_names(chat_id), game["tone"],
        ),
        "придумать персонажей",
    )
    if options is None:
        db.delete_draft(chat_id, user_id)
        return
    db.set_draft(chat_id, user_id, "pick", selected, [o.model_dump() for o in options])
    text = "🎭 <b>Выбери своего персонажа:</b>\n\n"
    for i, o in enumerate(options, 1):
        text += f"<b>{i}. {esc(o.name)}</b> — {esc(o.archetype)}\n{esc(o.description)}\n\n"
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=f"{i + 1}. {o.name}"[:60], callback_data=f"pick:{user_id}:{i}"
                )
                for i, o in enumerate(options)
            ]
        ]
    )
    await edit_long(callback.message, text, keyboard)


@router.callback_query(F.data.startswith("pick:"))
async def cb_pick_character(callback: CallbackQuery) -> None:
    _, uid, idx = callback.data.split(":")
    user_id, index = int(uid), int(idx)
    if not await _owner(callback, user_id):
        return
    chat_id = callback.message.chat.id
    draft = db.get_draft(chat_id, user_id)
    if draft is None or draft["stage"] != "pick" or index >= len(draft["options"]):
        await callback.answer("Это меню устарело. Начни заново: /hero")
        return
    option = draft["options"][index]
    stats = rules.generate_stats(draft["selected"])
    saved = db.save_character(
        chat_id,
        user_id,
        callback.from_user.first_name,
        option["name"],
        f"{option['archetype']}. {option['description']}",
        ", ".join(draft["selected"]),
        stats=stats,
        max_hp=rules.initial_max_hp(stats),
    )
    db.delete_draft(chat_id, user_id)
    if not saved:
        await callback.answer()
        await callback.message.edit_text(
            "⚠️ Этот персонаж уже занят другим игроком (или у тебя уже есть персонаж). "
            "Запусти /hero ещё раз."
        )
        return
    character = db.get_character(chat_id, user_id)
    db.save_action(chat_id, character["name"], "присоединяется к отряду", kind="event")
    await callback.answer("Персонаж создан!")
    await edit_long(
        callback.message,
        f"✅ <b>{esc(callback.from_user.first_name)}</b> играет за:\n\n" + sheet_text(chat_id, character),
    )


@router.message(Command("sheet"))
async def cmd_sheet(message: Message) -> None:
    character = db.get_character(message.chat.id, message.from_user.id)
    if character is None:
        await message.answer("У тебя ещё нет персонажа. Создай: /hero")
        return
    await message.answer(sheet_text(message.chat.id, character))


@router.message(Command("delete_hero"))
async def cmd_delete_hero(message: Message) -> None:
    if db.get_character(message.chat.id, message.from_user.id) is None:
        await message.answer("У тебя нет персонажа в этой кампании.")
        return
    db.delete_character(message.chat.id, message.from_user.id)
    db.delete_draft(message.chat.id, message.from_user.id)
    await message.answer("Персонаж удалён. Создай нового: /hero")
