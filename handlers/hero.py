"""Создание персонажа по правилам гл. 1 и лист персонажа.

Шаги: раса → (подраса) → класс → предыстория → характеристики → навыки → (компетентность
плута / боевой стиль воина) → имя и образ (варианты от Claude). Черновик хранится в базе,
а не в памяти, поэтому создание переживает перезапуск бота; в кнопки зашит id владельца.
"""

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

import ai
import creation
import db
import engine
import rules
import srd
from handlers.common import conditions_text, edit_long, esc, generate, hp_line, require_world
from srd import CLASSES

router = Router()

RACE_NAMES = list(srd.RACES)
CLASS_NAMES = list(CLASSES)
BACKGROUND_NAMES = list(srd.BACKGROUNDS)

CLASS_BLURB = {
    "Жрец": "d8 · божественная магия, лечение, доспехи (в т. ч. тяжёлые — домен Жизни), мастерство: МДР и ХАР",
    "Воин": "d10 · лучший в бою: любое оружие и доспехи, боевой стиль, до 4 атак, Второе дыхание",
    "Плут": "d8 · скрытая атака, компетентность в навыках, Хитрое действие, лёгкие доспехи",
    "Волшебник": "d6 · книга заклинаний, самые сильные заклинания; хрупкий, без доспехов",
}


def _b(text: str, data: str) -> InlineKeyboardButton:
    return InlineKeyboardButton(text=text[:60], callback_data=data)


def _bonus_text(race: str, subrace: str = "") -> str:
    return ", ".join(f"{srd.ABILITY_SHORT[a]} +{v}" for a, v in rules.racial_bonuses(race, subrace).items()
                     if len(rules.racial_bonuses(race, subrace)) < 6) or "+1 ко всем"


# ---------------------------------------------------------------- отображение шагов

def stage_view(chat_id: int, uid: int, data: dict, stage: str, options: list) -> tuple[str, InlineKeyboardMarkup | None]:
    """Текст и кнопки текущего шага создания."""
    if stage == "race":
        lines = ["⚔️ <b>Шаг 1. Раса</b> (гл. 2)"]
        for name, info in srd.RACES.items():
            lines.append(f"• <b>{name}</b> — {_bonus_text(name)}, скорость {info['speed']} фт.")
        rows = [[_b(n, f"hc:{uid}:r:{i}") for i, n in enumerate(RACE_NAMES[:2])],
                [_b(n, f"hc:{uid}:r:{i + 2}") for i, n in enumerate(RACE_NAMES[2:])]]
        return "\n".join(lines), InlineKeyboardMarkup(inline_keyboard=rows)
    if stage == "subrace":
        race = data["race"]
        subs = list(srd.RACES[race]["subraces"])
        lines = [f"⚔️ <b>Подраса: {race}</b>"]
        for name in subs:
            sub = srd.RACES[race]["subraces"][name]
            extras = "; ".join(sub.get("traits", []))
            lines.append(f"• <b>{name}</b> — {_bonus_text(race, name)}. {extras}")
        rows = [[_b(n, f"hc:{uid}:s:{i}") for i, n in enumerate(subs)]]
        return "\n".join(lines), InlineKeyboardMarkup(inline_keyboard=rows)
    if stage == "class":
        lines = ["⚔️ <b>Шаг 2. Класс</b> (гл. 3)"] + [f"• <b>{n}</b> — {CLASS_BLURB[n]}" for n in CLASS_NAMES]
        rows = [[_b(n, f"hc:{uid}:c:{i}") for i, n in enumerate(CLASS_NAMES[:2])],
                [_b(n, f"hc:{uid}:c:{i + 2}") for i, n in enumerate(CLASS_NAMES[2:])]]
        return "\n".join(lines), InlineKeyboardMarkup(inline_keyboard=rows)
    if stage == "bg":
        lines = ["⚔️ <b>Шаг 3. Предыстория</b> (гл. 4) — даёт два навыка"]
        for name, info in srd.BACKGROUNDS.items():
            lines.append(f"• <b>{name}</b> — {', '.join(info['skills'])}")
        rows = [[_b(n, f"hc:{uid}:b:{i}") for i, n in enumerate(BACKGROUND_NAMES[j:j + 2], start=j)]
                for j in range(0, len(BACKGROUND_NAMES), 2)]
        return "\n".join(lines), InlineKeyboardMarkup(inline_keyboard=rows)
    if stage == "method":
        text = ("⚔️ <b>Шаг 4. Характеристики</b> (с. 9)\n"
                "🎲 <b>Бросить</b> — 4d6, худший кубик отбрасывается, шесть раз.\n"
                "📊 <b>Стандартный набор</b> — 15, 14, 13, 12, 10, 8.\n"
                "Лучшие значения автоматически идут в главные характеристики класса, затем добавляются бонусы расы.")
        rows = [[_b("🎲 Бросить 4d6", f"hc:{uid}:m:roll"), _b("📊 Стандартный набор", f"hc:{uid}:m:std")]]
        return text, InlineKeyboardMarkup(inline_keyboard=rows)
    if stage == "skills":
        need = CLASSES[data["cls"]]["skills_count"]
        picked = data.get("skills", [])
        mark = lambda s: "✅ " if s in picked else ""  # noqa: E731
        stats = creation.build_stats(data["cls"], data["values"], data["race"], data.get("subrace", ""))
        lines = ["⚔️ <b>Шаг 5. Навыки</b>",
                 f"Ваши характеристики: " + ", ".join(f"{srd.ABILITY_SHORT[a]} {v}" for a, v in stats.items()),
                 f"Выбери навыков класса: <b>{need}</b> (выбрано {len(picked)})."]
        rows = [[_b(f"{mark(s)}{s}", f"hc:{uid}:k:{i}") for i, s in enumerate(options)][j:j + 2]
                for j in range(0, len(options), 2)]
        if len(picked) == need:
            rows.append([_b("➡️ Готово", f"hc:{uid}:kd:0")])
        return "\n".join(lines), InlineKeyboardMarkup(inline_keyboard=rows)
    if stage == "expertise":
        picked = data.get("expertise", [])
        lines = ["⚔️ <b>Компетентность плута</b> (с. 29)",
                 "Выбери 2 навыка: бонус мастерства для них удваивается."]
        rows = [[_b(("✅ " if s in picked else "") + s, f"hc:{uid}:e:{i}") for i, s in enumerate(options)][j:j + 2]
                for j in range(0, len(options), 2)]
        if len(picked) == 2:
            rows.append([_b("➡️ Готово", f"hc:{uid}:ed:0")])
        return "\n".join(lines), InlineKeyboardMarkup(inline_keyboard=rows)
    if stage == "style":
        lines = ["⚔️ <b>Боевой стиль воина</b> (с. 27)"] + [f"• <b>{n}</b> — {d}" for n, d in srd.FIGHTING_STYLES.items()]
        names = list(srd.FIGHTING_STYLES)
        rows = [[_b(n, f"hc:{uid}:f:{i}") for i, n in enumerate(names[j:j + 2], start=j)] for j in range(0, len(names), 2)]
        return "\n".join(lines), InlineKeyboardMarkup(inline_keyboard=rows)
    if stage == "pick":
        text = "🎭 <b>Выбери своего персонажа:</b>\n\n"
        for i, o in enumerate(options, 1):
            text += f"<b>{i}. {esc(o['name'])}</b> — {esc(o['archetype'])}\n{esc(o['description'])}\n\n"
        rows = [[_b(f"{i + 1}. {o['name']}", f"hc:{uid}:p:{i}") for i, o in enumerate(options)]]
        return text, InlineKeyboardMarkup(inline_keyboard=rows)
    return "Что-то пошло не так. Начни заново: /hero", None


def _stage_options(data: dict, stage: str) -> list:
    if stage == "skills":
        return creation.skill_options(data["cls"], data["race"], data.get("subrace", ""), data["bg"])
    if stage == "expertise":
        return creation.known_skills(data["race"], data.get("subrace", ""), data["bg"], data.get("skills", []))
    return []


async def _save_and_show(message: Message, chat_id: int, uid: int, data: dict, stage: str, options: list | None = None) -> None:
    opts = _stage_options(data, stage) if options is None else options
    db.set_draft(chat_id, uid, stage, data, opts if stage == "pick" else [])
    text, markup = stage_view(chat_id, uid, data, stage, opts)
    await edit_long(message, text, markup)


async def _owner(callback: CallbackQuery, uid: int) -> bool:
    if callback.from_user.id != uid:
        await callback.answer("Это не твоё меню создания персонажа 🙂")
        return False
    return True


# ---------------------------------------------------------------- лист персонажа

def sheet_text(chat_id: int, character) -> str:
    g = engine.gear(chat_id, character)
    profile = g["profile"]
    level = character["level"]
    cls, race, sub = rules.class_of(character), rules.race_of(character), rules.subrace_of(character)
    speed = rules.speed_of(character, g["penalties"])
    next_xp = rules.xp_to_next(character)
    hd = rules.hit_die_of(character)
    lines = [
        f"📜 <b>{esc(character['name'])}</b> — {race}{f' ({sub})' if sub else ''} {cls}, {level} уровень",
        esc(character["description"]),
    ]
    if character["background"]:
        lines.append(f"Предыстория: {esc(character['background'])}")
    lines += [
        "",
        hp_line(character),
        f"🛡 КД <b>{g['ac']}</b> ({', '.join(g['ac_parts'])})",
        f"🏃 Скорость {speed} фт. · ⚡ Инициатива {rules.format_modifier(rules.initiative_bonus(character))}"
        f" · 🎓 Мастерство +{rules.proficiency(level)}",
        f"🍞 Кости хитов: {rules.hit_dice_left(character)}/{level} (d{hd})"
        f" · ✨ Опыт: {character['xp']}" + (f"/{next_xp}" if next_xp else " (максимум)"),
    ]
    extra = conditions_text(character)
    if extra:
        lines.append(f"⚠️ Состояния: {esc(extra)}")
    if character["inspiration"]:
        lines.append("🌟 Есть вдохновение (/inspire)")
    if g["penalties"]["nonproficient"]:
        lines.append("⚠️ Доспех или щит без мастерства: помеха на СИЛ/ЛОВ, нельзя колдовать")
    if g["penalties"]["str_penalty"]:
        lines.append("⚠️ Не хватает Силы для доспеха: скорость −10")
    lines += ["", f"<pre>{rules.format_stats(character)}</pre>"]
    weapon = profile["weapon"]
    dmg_bonus = rules.format_modifier(profile["damage_bonus"]) if profile["damage_bonus"] else ""
    attacks = rules.attacks_per_action(character)
    lines.append(
        f"⚔️ {esc(weapon['name'])}: атака {rules.format_modifier(profile['attack'])}, "
        f"урон {profile['damage_dice']}{dmg_bonus} {esc(profile['dtype'])}"
        + (f" · {attacks} атаки за действие" if attacks > 1 else "")
        + (f" · скрытая атака {rules.sneak_dice(character)}d6" if rules.sneak_dice(character) else "")
    )
    if character["fighting_style"]:
        lines.append(f"🗡 Боевой стиль: {esc(character['fighting_style'])}")
    if rules.is_caster(character):
        lines.append(
            f"🔮 Заклинания: сл. спасброска {rules.spell_dc(character)}, атака {rules.format_modifier(rules.spell_attack_bonus(character))}"
            f" · ячейки: {__import__('spells').format_slots(character)} · /spells"
        )
    pending = []
    if character["asi_pending"]:
        pending.append(f"/asi ×{character['asi_pending']}")
    if character["learn_pending"]:
        pending.append(f"/learn ×{character['learn_pending']}")
    if character["cantrip_pending"]:
        pending.append(f"/cantrip ×{character['cantrip_pending']}")
    if character["expertise_pending"]:
        pending.append("/expertise")
    if pending:
        lines.append("➡️ Нужно выбрать: " + ", ".join(pending))
    features = rules.features_of(character)
    if features:
        lines += ["", "<b>Способности класса:</b>"] + [f"• {esc(f)}" for f in features]
    traits = rules.race_info(character)["traits"]
    if traits:
        lines += ["", "<b>Черты расы:</b>"] + [f"• {esc(t)}" for t in traits]
    lines.append(f"\nИгрок: {esc(character['user_name'])}. Навыки: /skills")
    return "\n".join(lines)


# ---------------------------------------------------------------- команды

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
        db.delete_character(chat_id, user.id)     # погибший герой освобождает место
    db.set_draft(chat_id, user.id, "race", {}, [])
    text, markup = stage_view(chat_id, user.id, {}, "race", [])
    await message.answer(f"{esc(user.first_name)}, создаём героя по правилам D&D.\n\n" + text, reply_markup=markup)


def _load(callback: CallbackQuery, uid: int, expected: tuple[str, ...]):
    chat_id = callback.message.chat.id
    draft = db.get_draft(chat_id, uid)
    if draft is None or draft["stage"] not in expected:
        return None
    return draft


@router.callback_query(F.data.startswith("hc:"))
async def cb_creation(callback: CallbackQuery) -> None:
    _, uid_s, step, value = callback.data.split(":")
    uid = int(uid_s)
    if not await _owner(callback, uid):
        return
    chat_id = callback.message.chat.id
    draft = db.get_draft(chat_id, uid)
    if draft is None:
        await callback.answer("Это меню устарело. Начни заново: /hero")
        return
    data = draft["selected"] if isinstance(draft["selected"], dict) else {}
    stage = draft["stage"]
    expected = {"r": "race", "s": "subrace", "c": "class", "b": "bg", "m": "method", "k": "skills", "kd": "skills",
                "e": "expertise", "ed": "expertise", "f": "style", "p": "pick"}
    if expected.get(step) != stage:
        await callback.answer("Это меню устарело.")
        return

    if step == "r":
        data["race"] = RACE_NAMES[int(value)]
        data.pop("subrace", None)
        nxt = "subrace" if srd.RACES[data["race"]]["subraces"] else "class"
        await callback.answer()
        await _save_and_show(callback.message, chat_id, uid, data, nxt)
    elif step == "s":
        data["subrace"] = list(srd.RACES[data["race"]]["subraces"])[int(value)]
        await callback.answer()
        await _save_and_show(callback.message, chat_id, uid, data, "class")
    elif step == "c":
        data["cls"] = CLASS_NAMES[int(value)]
        await callback.answer()
        await _save_and_show(callback.message, chat_id, uid, data, "bg")
    elif step == "b":
        data["bg"] = BACKGROUND_NAMES[int(value)]
        await callback.answer()
        await _save_and_show(callback.message, chat_id, uid, data, "method")
    elif step == "m":
        data["values"] = rules.roll_stats() if value == "roll" else list(srd.STANDARD_ARRAY)
        data["skills"] = []
        await callback.answer()
        stats_text = ", ".join(str(v) for v in sorted(data["values"], reverse=True))
        await callback.message.edit_text(f"{'🎲 Выпало' if value == 'roll' else '📊 Набор'}: {stats_text}")
        await _save_and_show(callback.message, chat_id, uid, data, "skills")
    elif step == "k":
        options = _stage_options(data, "skills")
        skill = options[int(value)]
        picked = data.get("skills", [])
        need = CLASSES[data["cls"]]["skills_count"]
        if skill in picked:
            picked.remove(skill)
        elif len(picked) < need:
            picked.append(skill)
        else:
            await callback.answer(f"Можно выбрать только {need}.")
            return
        data["skills"] = picked
        db.set_draft(chat_id, uid, "skills", data, [])
        text, markup = stage_view(chat_id, uid, data, "skills", options)
        await callback.message.edit_text(text, reply_markup=markup)
        await callback.answer()
    elif step == "kd":
        need = CLASSES[data["cls"]]["skills_count"]
        if len(data.get("skills", [])) != need:
            await callback.answer(f"Выбери ровно {need}.")
            return
        await callback.answer()
        data["expertise"] = []
        if data["cls"] == "Плут":
            await _save_and_show(callback.message, chat_id, uid, data, "expertise")
        elif data["cls"] == "Воин":
            await _save_and_show(callback.message, chat_id, uid, data, "style")
        else:
            await _generate_names(callback, chat_id, uid, data)
    elif step == "e":
        options = _stage_options(data, "expertise")
        skill = options[int(value)]
        picked = data.get("expertise", [])
        if skill in picked:
            picked.remove(skill)
        elif len(picked) < 2:
            picked.append(skill)
        else:
            await callback.answer("Можно выбрать только 2.")
            return
        data["expertise"] = picked
        db.set_draft(chat_id, uid, "expertise", data, [])
        text, markup = stage_view(chat_id, uid, data, "expertise", options)
        await callback.message.edit_text(text, reply_markup=markup)
        await callback.answer()
    elif step == "ed":
        if len(data.get("expertise", [])) != 2:
            await callback.answer("Выбери ровно 2.")
            return
        await callback.answer()
        await _generate_names(callback, chat_id, uid, data)
    elif step == "f":
        data["style"] = list(srd.FIGHTING_STYLES)[int(value)]
        await callback.answer()
        await _generate_names(callback, chat_id, uid, data)
    elif step == "p":
        await _finish(callback, chat_id, uid, data, draft["options"], int(value))


async def _generate_names(callback: CallbackQuery, chat_id: int, uid: int, data: dict) -> None:
    game = db.get_world(chat_id)
    if game is None:
        await callback.message.edit_text("Мир исчез. Создайте его заново: /world")
        return
    db.set_draft(chat_id, uid, "names", data, [])
    race_line = f"{data['race']}{f' ({data['subrace']})' if data.get('subrace') else ''}"
    await callback.message.edit_text(
        f"🎭 {race_line}, {data['cls']}, «{data['bg']}»\nПридумываю имя и образ…"
    )
    options = await generate(
        callback.message,
        ai.generate_character_options(
            game["theme"], game["world_desc"], data["race"], data.get("subrace", ""), data["cls"], data["bg"],
            db.taken_character_names(chat_id), game["tone"],
        ),
        "придумать персонажей",
    )
    if options is None:
        db.delete_draft(chat_id, uid)
        return
    await _save_and_show(callback.message, chat_id, uid, data, "pick", [o.model_dump() for o in options])


async def _finish(callback: CallbackQuery, chat_id: int, uid: int, data: dict, options: list, index: int) -> None:
    if index >= len(options):
        await callback.answer("Это меню устарело. Начни заново: /hero")
        return
    option = options[index]
    saved = creation.create(chat_id, uid, callback.from_user.first_name, option["name"],
                            f"{option['archetype']}. {option['description']}", data)
    db.delete_draft(chat_id, uid)
    if not saved:
        await callback.answer()
        await callback.message.edit_text(
            "⚠️ Этот персонаж уже занят другим игроком (или у тебя уже есть персонаж). Запусти /hero ещё раз."
        )
        return
    character = db.get_character(chat_id, uid)
    engine.log(chat_id, character["name"], "присоединяется к отряду")
    await callback.answer("Персонаж создан!")
    await edit_long(callback.message,
                    f"✅ <b>{esc(callback.from_user.first_name)}</b> играет за:\n\n" + sheet_text(chat_id, character))


@router.message(Command("sheet"))
async def cmd_sheet(message: Message) -> None:
    character = db.get_character(message.chat.id, message.from_user.id)
    if character is None:
        await message.answer("У тебя ещё нет персонажа. Создай: /hero")
        return
    from handlers.common import answer_long
    await answer_long(message, sheet_text(message.chat.id, character))


@router.message(Command("skills"))
async def cmd_skills(message: Message) -> None:
    character = db.get_character(message.chat.id, message.from_user.id)
    if character is None:
        await message.answer("У тебя ещё нет персонажа. Создай: /hero")
        return
    await message.answer(
        f"🎓 <b>Навыки {esc(character['name'])}</b> (★ мастерство, ◆ компетентность)\n"
        f"<pre>{rules.format_skills(character)}</pre>"
    )


@router.message(Command("delete_hero"))
async def cmd_delete_hero(message: Message) -> None:
    if db.get_character(message.chat.id, message.from_user.id) is None:
        await message.answer("У тебя нет персонажа в этой кампании.")
        return
    db.delete_character(message.chat.id, message.from_user.id)
    db.delete_draft(message.chat.id, message.from_user.id)
    await message.answer("Персонаж удалён. Создай нового: /hero")
