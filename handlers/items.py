"""Предметы: /take, /drop, /equip, /unequip, /inventory, /loot."""

from aiogram import Router
from aiogram.filters import Command, CommandObject
from aiogram.types import Message

import ai
import db
import engine
import items
import rules
from handlers.common import (
    answer_long,
    edit_long,
    esc,
    generate,
    require_character,
    require_gm,
    require_world,
)

router = Router()

SLOT_NAMES = {"weapon": "оружие", "armor": "доспех", "shield": "щит"}


@router.message(Command("take"))
async def cmd_take(message: Message, command: CommandObject) -> None:
    character = await require_character(message)
    if character is None:
        return
    parsed = items.parse_take(command.args or "")
    if parsed is None:
        await message.answer(
            "Примеры:\n/take Длинный меч\n/take Кольчуга +1\n/take Меч пламени | Длинный меч +1\n"
            "/take Нож 1d4\n/take Верёвка\nОружие и доспехи берутся из таблиц правил."
        )
        return
    name, kind, value = parsed
    if len(db.list_items(message.chat.id, character["user_id"])) >= 40:
        await message.answer("Инвентарь переполнен (40 предметов). Выбрось что-нибудь: /drop")
        return
    item = db.add_item(message.chat.id, character["user_id"], name, kind, value)
    desc = items.describe_item(item)
    engine.log(message.chat.id, character["name"], f"берёт: {name}")
    await message.answer(
        f"🎒 {esc(character['name'])} берёт: <b>{esc(name)}</b>" + (f" — {esc(desc)}" if desc else "")
        + ("\nНадеть/взять в руки: /equip " + esc(name) if kind in SLOT_NAMES else "")
    )


@router.message(Command("drop"))
async def cmd_drop(message: Message, command: CommandObject) -> None:
    character = await require_character(message)
    if character is None:
        return
    item = db.find_item(message.chat.id, character["user_id"], command.args or "")
    if item is None:
        await message.answer("Такого предмета нет. Список: /inventory")
        return
    db.delete_item(item["id"])
    await message.answer(f"🗑 {esc(character['name'])} выбрасывает: {esc(item['name'])}")


@router.message(Command("equip"))
async def cmd_equip(message: Message, command: CommandObject) -> None:
    character = await require_character(message, need_conscious=True)
    if character is None:
        return
    chat_id, uid = message.chat.id, character["user_id"]
    item = db.find_item(chat_id, uid, command.args or "")
    if item is None or item["kind"] not in SLOT_NAMES:
        await message.answer("Укажи оружие, доспех или щит из инвентаря: /equip Кольчуга")
        return
    from combat import in_combat
    if in_combat(chat_id) and item["kind"] in ("armor",):
        await message.answer("Доспех нельзя надеть посреди боя — это занимает минуты (с. 144).")
        return
    db.equip_item(chat_id, uid, item["id"], item["kind"])
    character = db.get_character(chat_id, uid)
    g = engine.gear(chat_id, character)
    warn = ""
    if g["penalties"]["nonproficient"]:
        warn = "\n⚠️ Вы не владеете этим снаряжением: помеха на СИЛ/ЛОВ, колдовать нельзя (с. 144)."
    if g["penalties"]["str_penalty"]:
        warn += "\n⚠️ Не хватает Силы: скорость −10 фт."
    await message.answer(f"🛡 {esc(character['name'])} экипирует: {esc(item['name'])}. КД теперь <b>{g['ac']}</b>.{warn}")


@router.message(Command("unequip"))
async def cmd_unequip(message: Message, command: CommandObject) -> None:
    character = await require_character(message, need_conscious=True)
    if character is None:
        return
    item = db.find_item(message.chat.id, character["user_id"], command.args or "")
    if item is None or not item["equipped"]:
        await message.answer("Такого надетого предмета нет. Список: /inventory")
        return
    db.unequip_item(item["id"])
    await message.answer(f"🎒 {esc(character['name'])} убирает: {esc(item['name'])}")


@router.message(Command("inventory"))
async def cmd_inventory(message: Message) -> None:
    character = await require_character(message)
    if character is None:
        return
    chat_id = message.chat.id
    listed = db.list_items(chat_id, character["user_id"])
    if not listed:
        await message.answer("Инвентарь пуст. Взять предмет: /take Верёвка")
        return
    lines = [f"🎒 <b>Инвентарь {esc(character['name'])}</b>"]
    for i in listed:
        mark = "✅ " if i["equipped"] else "• "
        desc = items.describe_item(i)
        lines.append(f"{mark}{esc(i['name'])}" + (f" — {esc(desc)}" if desc else ""))
    await answer_long(message, "\n".join(lines))


@router.message(Command("loot"))
async def cmd_loot(message: Message, command: CommandObject) -> None:
    game = await require_world(message)
    if game is None or not await require_gm(message, game):
        return
    chat_id = message.chat.id
    context = (command.args or "").strip() or "отряд обыскивает победённых противников"
    note = await message.answer("💰 Подбираю добычу…")
    loot = await generate(note, ai.generate_loot(game["theme"], game["world_desc"], context, game["tone"]),
                          "придумать добычу")
    if loot is None:
        return
    party = db.list_characters(chat_id, alive_only=True)
    if not party:
        await note.edit_text("В отряде нет живых героев.")
        return
    lines = ["💰 <b>Добыча</b>"]
    for n, loot_item in enumerate(loot):
        holder = party[n % len(party)]
        if loot_item.kind == "item":
            value = ""
        else:
            found = rules.srd_item(loot_item.base)
            if found is None:
                loot_item.kind, value = "item", ""
            else:
                _, value = found
                items.set_magic_bonus(loot_item.kind, value, loot_item.bonus)
        db.add_item(chat_id, holder["user_id"], loot_item.name, loot_item.kind, value)
        lines.append(f"• <b>{esc(loot_item.name)}</b> → {esc(holder['name'])}: {esc(loot_item.description)}")
    lines.append("\nПосмотреть: /inventory")
    await edit_long(note, "\n".join(lines))
