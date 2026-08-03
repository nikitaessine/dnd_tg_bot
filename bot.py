"""Telegram-бот для D&D-кампании: мир, персонажи, NPC и сцены генерируются Claude."""

import asyncio
import logging

from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

import ai
import db
import dice
from config import ATTRIBUTE_BONUS, ATTRIBUTES, ATTRIBUTES_TO_PICK, BOT_TOKEN

logging.basicConfig(level=logging.INFO)

dp = Dispatcher()


class HeroCreation(StatesGroup):
    choosing_attributes = State()
    choosing_character = State()


HELP = (
    "🎲 <b>D&D-бот</b>\n\n"
    "Порядок игры:\n"
    "1. /world &lt;тема&gt; — создать мир (например: /world мрачное тёмное фэнтези)\n"
    "2. /hero — создать своего персонажа (выбери 4 атрибута, получи 3 варианта)\n"
    "3. /npc — сгенерировать нового NPC\n"
    "4. /scene — сгенерировать следующую сцену приключения\n\n"
    "🗣 <b>Действия игроков:</b>\n"
    "/do &lt;что делает твой герой&gt; — заяви действие после сцены.\n"
    "Следующая /scene будет прямым следствием всех заявленных действий.\n"
    "/actions — показать, что уже заявлено\n\n"
    "❤️ <b>Здоровье:</b>\n"
    "/hp — здоровье всего отряда\n"
    "/damage 5 — получить 5 урона\n"
    "/heal 3 — восстановить 3 здоровья\n\n"
    "🎲 <b>Броски кубика:</b>\n"
    "/roll — простой d20\n"
    "/roll Сила — d20 с бонусом, если атрибут выбран у твоего персонажа\n"
    "/roll Сила 15 — то же, но со сложностью проверки (успех/провал)\n"
    "/roll 2d6 — произвольный бросок\n\n"
    "Прочее:\n"
    "/status — мир, персонажи и NPC\n"
    "/delete_hero — удалить своего персонажа\n"
    "/reset — начать кампанию заново (стирает всё в этом чате)"
)


def attr_keyboard(selected: list[str]) -> InlineKeyboardMarkup:
    rows = []
    for i in range(0, len(ATTRIBUTES), 2):
        row = []
        for attr in ATTRIBUTES[i : i + 2]:
            mark = "✅ " if attr in selected else ""
            row.append(InlineKeyboardButton(text=f"{mark}{attr}", callback_data=f"attr:{attr}"))
        rows.append(row)
    if len(selected) == ATTRIBUTES_TO_PICK:
        rows.append([InlineKeyboardButton(text="➡️ Готово", callback_data="attr_done")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


@dp.message(CommandStart())
@dp.message(Command("help"))
async def cmd_start(message: Message) -> None:
    await message.answer(HELP)


@dp.message(Command("world"))
async def cmd_world(message: Message, command: CommandObject) -> None:
    theme = (command.args or "").strip()
    if not theme:
        await message.answer("Укажи тему мира: /world мрачное тёмное фэнтези")
        return
    note = await message.answer("🌍 Создаю мир, подожди немного…")
    world_desc = await ai.generate_world(theme)
    db.set_world(message.chat.id, theme, world_desc)
    await note.edit_text(f"🌍 <b>Мир кампании: {theme}</b>\n\n{world_desc}")


@dp.message(Command("hero"))
async def cmd_hero(message: Message, state: FSMContext) -> None:
    if db.get_world(message.chat.id) is None:
        await message.answer("Сначала создайте мир: /world <тема>")
        return
    if db.get_character(message.chat.id, message.from_user.id) is not None:
        await message.answer(
            "У тебя уже есть персонаж в этой кампании. "
            "Удалить его можно командой /delete_hero."
        )
        return
    await state.set_state(HeroCreation.choosing_attributes)
    await state.update_data(selected=[])
    await message.answer(
        f"⚔️ {message.from_user.first_name}, выбери {ATTRIBUTES_TO_PICK} главных атрибута "
        "своего персонажа:",
        reply_markup=attr_keyboard([]),
    )


@dp.callback_query(HeroCreation.choosing_attributes, F.data.startswith("attr:"))
async def cb_toggle_attr(callback: CallbackQuery, state: FSMContext) -> None:
    attr = callback.data.split(":", 1)[1]
    data = await state.get_data()
    selected: list[str] = data.get("selected", [])
    if attr in selected:
        selected.remove(attr)
    elif len(selected) < ATTRIBUTES_TO_PICK:
        selected.append(attr)
    else:
        await callback.answer(f"Можно выбрать только {ATTRIBUTES_TO_PICK} атрибута.")
        return
    await state.update_data(selected=selected)
    await callback.message.edit_reply_markup(reply_markup=attr_keyboard(selected))
    await callback.answer()


@dp.callback_query(HeroCreation.choosing_attributes, F.data == "attr_done")
async def cb_attrs_done(callback: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    selected: list[str] = data.get("selected", [])
    if len(selected) != ATTRIBUTES_TO_PICK:
        await callback.answer("Выбери ровно 4 атрибута.")
        return
    await callback.answer()
    chat_id = callback.message.chat.id
    world = db.get_world(chat_id)
    await callback.message.edit_text(
        f"🎭 Атрибуты: {', '.join(selected)}\nГенерирую варианты персонажа…"
    )
    try:
        options = await ai.generate_character_options(
            world["theme"], world["world_desc"], selected, db.taken_character_names(chat_id)
        )
    except Exception:
        logging.exception("character generation failed")
        await callback.message.edit_text("Не удалось сгенерировать персонажей. Попробуй /hero ещё раз.")
        await state.clear()
        return
    await state.set_state(HeroCreation.choosing_character)
    await state.update_data(
        options=[o.model_dump() for o in options], attributes=selected
    )
    text = "🎭 <b>Выбери своего персонажа:</b>\n\n"
    for i, o in enumerate(options, 1):
        text += f"<b>{i}. {o.name}</b> — {o.archetype}\n{o.description}\n\n"
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text=f"{i + 1}. {o.name}", callback_data=f"pick:{i}")
                for i, o in enumerate(options)
            ]
        ]
    )
    await callback.message.edit_text(text, reply_markup=keyboard)


@dp.callback_query(HeroCreation.choosing_character, F.data.startswith("pick:"))
async def cb_pick_character(callback: CallbackQuery, state: FSMContext) -> None:
    index = int(callback.data.split(":", 1)[1])
    data = await state.get_data()
    options = data.get("options", [])
    if index >= len(options):
        await callback.answer("Что-то пошло не так, попробуй /hero заново.")
        await state.clear()
        return
    option = options[index]
    chat_id = callback.message.chat.id
    user = callback.from_user
    saved = db.save_character(
        chat_id,
        user.id,
        user.first_name,
        option["name"],
        f"{option['archetype']}. {option['description']}",
        ", ".join(data.get("attributes", [])),
    )
    await state.clear()
    if not saved:
        await callback.answer()
        await callback.message.edit_text(
            "⚠️ Этот персонаж уже занят другим игроком (или у тебя уже есть персонаж). "
            "Запусти /hero ещё раз."
        )
        return
    await callback.answer("Персонаж создан!")
    await callback.message.edit_text(
        f"✅ <b>{user.first_name}</b> играет за:\n\n"
        f"<b>{option['name']}</b> — {option['archetype']}\n"
        f"{option['description']}\n\n"
        f"Атрибуты: {', '.join(data.get('attributes', []))}"
    )


@dp.callback_query(F.data.startswith(("attr:", "pick:")))
@dp.callback_query(F.data == "attr_done")
async def cb_not_yours(callback: CallbackQuery) -> None:
    # Сюда попадают нажатия без активного состояния — чужие кнопки
    await callback.answer("Это не твоё меню создания персонажа 🙂", show_alert=False)


@dp.message(Command("delete_hero"))
async def cmd_delete_hero(message: Message) -> None:
    if db.get_character(message.chat.id, message.from_user.id) is None:
        await message.answer("У тебя нет персонажа в этой кампании.")
        return
    db.delete_character(message.chat.id, message.from_user.id)
    await message.answer("Персонаж удалён. Создай нового: /hero")


@dp.message(Command("npc"))
async def cmd_npc(message: Message) -> None:
    world = db.get_world(message.chat.id)
    if world is None:
        await message.answer("Сначала создайте мир: /world <тема>")
        return
    note = await message.answer("🧙 Придумываю NPC…")
    existing = [n["name"] for n in db.list_npcs(message.chat.id)]
    text = await ai.generate_npc(world["theme"], world["world_desc"], existing)
    name = text.split("\n", 1)[0].strip("*# ").strip()
    db.save_npc(message.chat.id, name, text)
    await note.edit_text(f"🧙 <b>Новый NPC</b>\n\n{text}")


def hp_line(character) -> str:
    """'Гарен: 14/20 ❤️' — строка состояния персонажа."""
    hp, max_hp = character["hp"], character["max_hp"]
    if hp == 0:
        state = "💀 без сознания"
    elif hp <= max_hp // 3:
        state = "🩸 тяжело ранен"
    elif hp < max_hp:
        state = "🤕 ранен"
    else:
        state = "❤️ здоров"
    return f"<b>{character['name']}</b>: {hp}/{max_hp} — {state}"


@dp.message(Command("do"))
async def cmd_do(message: Message, command: CommandObject) -> None:
    text = (command.args or "").strip()
    if not text:
        await message.answer(
            "Опиши, что делает твой герой. Например:\n"
            "/do крадусь вдоль стены к двери и слушаю, что за ней"
        )
        return
    character = db.get_character(message.chat.id, message.from_user.id)
    if character is None:
        await message.answer("Сначала создай персонажа: /hero")
        return
    if db.current_situation_number(message.chat.id) == 0:
        await message.answer("Сначала начните приключение: /scene")
        return
    db.save_action(message.chat.id, character["name"], text)
    pending = db.pending_actions(message.chat.id)
    await message.answer(
        f"🗣 <b>{character['name']}</b>: {text}\n\n"
        f"Заявлено действий: {len(pending)}. Когда все готовы — /scene"
    )


@dp.message(Command("actions"))
async def cmd_actions(message: Message) -> None:
    pending = db.pending_actions(message.chat.id)
    if not pending:
        await message.answer("Пока никто не заявил действий. Используй /do <действие>")
        return
    lines = ["🗣 <b>Заявленные действия:</b>", ""]
    lines += [f"• <b>{a['character_name']}</b>: {a['text']}" for a in pending]
    lines += ["", "Когда все готовы — /scene"]
    await message.answer("\n".join(lines))


@dp.message(Command("hp"))
async def cmd_hp(message: Message) -> None:
    characters = db.list_characters(message.chat.id)
    if not characters:
        await message.answer("В этой кампании ещё нет персонажей. Создай своего: /hero")
        return
    lines = ["❤️ <b>Состояние отряда:</b>", ""]
    lines += [f"• {hp_line(c)}" for c in characters]
    await message.answer("\n".join(lines))


async def _change_hp(message: Message, command: CommandObject, sign: int) -> None:
    raw = (command.args or "").strip()
    verb = "урона" if sign < 0 else "здоровья"
    if not raw:
        await message.answer(f"Укажи количество: /{'damage' if sign < 0 else 'heal'} 5")
        return
    try:
        amount = int(raw.split()[0])
    except ValueError:
        await message.answer(f"Количество {verb} должно быть числом.")
        return
    if amount <= 0:
        await message.answer("Число должно быть больше нуля.")
        return
    character = db.get_character(message.chat.id, message.from_user.id)
    if character is None:
        await message.answer("Сначала создай персонажа: /hero")
        return
    before = character["hp"]
    updated = db.adjust_hp(message.chat.id, message.from_user.id, sign * amount)
    actual = abs(updated["hp"] - before)
    if sign < 0:
        header = f"⚔️ <b>{updated['name']}</b> получает {actual} урона"
    else:
        header = f"✨ <b>{updated['name']}</b> восстанавливает {actual} здоровья"
    lines = [header, hp_line(updated)]
    if updated["hp"] == 0:
        lines.append("\n💀 Персонаж без сознания и не может действовать. Нужна помощь!")
    elif before == 0 and updated["hp"] > 0:
        lines.append("\n🌅 Персонаж приходит в себя!")
    await message.answer("\n".join(lines))


@dp.message(Command("damage"))
async def cmd_damage(message: Message, command: CommandObject) -> None:
    await _change_hp(message, command, -1)


@dp.message(Command("heal"))
async def cmd_heal(message: Message, command: CommandObject) -> None:
    await _change_hp(message, command, 1)


@dp.message(Command("scene"))
async def cmd_scene(message: Message) -> None:
    world = db.get_world(message.chat.id)
    if world is None:
        await message.answer("Сначала создайте мир: /world <тема>")
        return
    note = await message.answer("📜 Генерирую следующую сцену…")
    chat_id = message.chat.id
    characters = [
        f"{c['name']} ({c['description']}) — играет {c['user_name']}, "
        f"здоровье {c['hp']}/{c['max_hp']}"
        for c in db.list_characters(chat_id)
    ]
    npcs = [n["description"] for n in db.list_npcs(chat_id)]
    previous = [s["text"] for s in db.list_situations(chat_id, limit=10)]
    actions = [f"{a['character_name']}: {a['text']}" for a in db.pending_actions(chat_id)]
    text = await ai.generate_situation(
        world["theme"], world["world_desc"], characters, npcs, previous, actions
    )
    number = db.save_situation(chat_id, text)
    await note.edit_text(f"📜 <b>Сцена {number}</b>\n\n{text}")


@dp.message(Command("roll"))
async def cmd_roll(message: Message, command: CommandObject) -> None:
    args = (command.args or "").split()
    who = message.from_user.first_name

    # /roll 2d6 — произвольный бросок без атрибутов
    if args:
        notation = dice.parse_notation(args[0])
        if notation is not None:
            count, sides = notation
            results = dice.roll(count, sides)
            total = sum(results)
            detail = f" ({' + '.join(map(str, results))})" if count > 1 else ""
            await message.answer(f"🎲 {who} бросает {count}d{sides}: <b>{total}</b>{detail}")
            return

    # /roll — простой d20
    if not args:
        value, _ = dice.d20_check(0)
        await message.answer(f"🎲 {who} бросает d20: <b>{value}</b>")
        return

    character = db.get_character(message.chat.id, message.from_user.id)
    if character is None:
        await message.answer(
            "У тебя ещё нет персонажа — проверки атрибутов недоступны. Создай его: /hero\n"
            "Простой бросок работает и так: /roll"
        )
        return

    attribute = dice.match_attribute(args[0], ATTRIBUTES)
    if attribute is None:
        await message.answer(
            "Не знаю такого атрибута. Доступные: " + ", ".join(ATTRIBUTES)
        )
        return

    difficulty: int | None = None
    if len(args) > 1:
        try:
            difficulty = int(args[1])
        except ValueError:
            await message.answer("Сложность должна быть числом, например: /roll Сила 15")
            return

    own_attributes = [a.strip() for a in character["attributes"].split(",")]
    has_attribute = attribute in own_attributes
    bonus = ATTRIBUTE_BONUS if has_attribute else 0
    value, total = dice.d20_check(bonus)

    bonus_text = f" + {bonus} ({attribute})" if bonus else f" (без бонуса: {attribute} не выбран)"
    lines = [
        f"🎲 <b>{character['name']}</b> — проверка: {attribute}",
        f"d20: {value}{bonus_text} = <b>{total}</b>",
    ]
    if value == 20:
        lines.append("💥 Критический успех!")
    elif value == 1:
        lines.append("💀 Критический провал!")
    if difficulty is not None:
        lines.append(
            f"✅ Успех (сложность {difficulty})"
            if total >= difficulty
            else f"❌ Провал (сложность {difficulty})"
        )
    await message.answer("\n".join(lines))


@dp.message(Command("status"))
async def cmd_status(message: Message) -> None:
    world = db.get_world(message.chat.id)
    if world is None:
        await message.answer("Кампания ещё не начата. Создайте мир: /world <тема>")
        return
    lines = [f"🌍 <b>Мир:</b> {world['theme']}", ""]
    characters = db.list_characters(message.chat.id)
    lines.append("⚔️ <b>Персонажи:</b>")
    if characters:
        for c in characters:
            lines.append(f"• {hp_line(c)} — {c['user_name']}")
            lines.append(f"  <i>{c['attributes']}</i>")
    else:
        lines.append("• пока нет")
    npcs = db.list_npcs(message.chat.id)
    lines.append("")
    lines.append("🧙 <b>NPC:</b>")
    if npcs:
        for n in npcs:
            lines.append(f"• {n['name']}")
    else:
        lines.append("• пока нет")
    scene_number = db.current_situation_number(message.chat.id)
    if scene_number:
        lines.append("")
        lines.append(f"📜 Сыграно сцен: {scene_number}")
    pending = db.pending_actions(message.chat.id)
    if pending:
        lines.append(f"🗣 Заявлено действий к следующей сцене: {len(pending)}")
    await message.answer("\n".join(lines))


@dp.message(Command("reset"))
async def cmd_reset(message: Message) -> None:
    db.reset_game(message.chat.id)
    await message.answer("♻️ Кампания сброшена. Начните заново: /world <тема>")


async def main() -> None:
    bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
