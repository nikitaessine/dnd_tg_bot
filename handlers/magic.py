"""Заклинания, способности классов, отдых и развитие персонажа."""

from aiogram import Router
from aiogram.filters import Command, CommandObject
from aiogram.types import Message

import db
import dice
import features
import rules
import spells
from handlers.common import answer_long, esc, require_character, require_gm, require_world
from handlers.turns import present
from spelldata import SPELLS

router = Router()


async def _run(message: Message, character, result: tuple[bool, list[str]]) -> None:
    """Публикует результат способности; в бою ведёт ход дальше."""
    ok, lines = result
    if not ok:
        await message.answer("\n".join(lines))
        return
    await present(message, message.chat.id, character["user_id"], lines)


def parse_cast(text: str, known: list[str]) -> tuple[str | None, int | None, list[str]]:
    """«Огненный шар 3 Гоблин, Орк» → (название, ячейка, цели)."""
    tokens = text.split()
    match = dice.match_prefix(tokens, known) or dice.match_prefix(tokens, SPELLS)
    if match is None:
        return None, None, []
    name, used = match
    rest = tokens[used:]
    slot = None
    if rest and rest[0].isdigit() and 1 <= int(rest[0]) <= 9:
        slot = int(rest[0])
        rest = rest[1:]
    targets = [t.strip() for t in " ".join(rest).split(",") if t.strip()]
    return name, slot, targets


@router.message(Command("cast"))
async def cmd_cast(message: Message, command: CommandObject) -> None:
    character = await require_character(message, need_conscious=True)
    if character is None:
        return
    if not rules.is_caster(character):
        await message.answer("Твой класс не колдует.")
        return
    name, slot, targets = parse_cast(command.args or "", rules.castable_spells(character))
    if name is None:
        await message.answer("Пример: /cast Волшебная стрела · /cast Огненный шар 4 Гоблин, Орк · "
                             "/cast Лечение ран 2 Имя\nСписок: /spells")
        return
    await _run(message, character, spells.cast(message.chat.id, character, name, slot, targets))


def spells_lines(character) -> list[str]:
    def label(n: str) -> str:
        s = SPELLS.get(n)
        tag = ""
        if s:
            tag = f" ({s['level']} ур." + (", бонусное" if s.get("time") == "bonus" else "") + (
                ", концентрация" if s.get("conc") else "") + ")"
        return esc(n) + tag

    lines = [f"🔮 <b>Заклинания {esc(character['name'])}</b>",
             f"Ячейки: {spells.format_slots(character)} · сл. спасброска {rules.spell_dc(character)}, "
             f"атака {rules.format_modifier(rules.spell_attack_bonus(character))}", ""]
    cantrips = rules.cantrips_of(character)
    lines.append("<b>Заговоры:</b> " + (", ".join(esc(c) for c in cantrips) or "нет"))
    domain = rules.domain_spells(character)
    if domain:
        lines.append("<b>Доменные (всегда подготовлены):</b> " + ", ".join(label(n) for n in domain))
    prepared = rules.prepared_of(character)
    lines.append(f"<b>Подготовлены ({len(prepared)}/{rules.prepared_limit(character)}):</b> "
                 + (", ".join(label(n) for n in prepared) or "нет"))
    if character["char_class"] == "Волшебник":
        lines.append("<b>Книга заклинаний:</b> " + ", ".join(esc(n) for n in rules.spellbook_of(character)))
    return lines


@router.message(Command("spells"))
async def cmd_spells(message: Message) -> None:
    character = await require_character(message)
    if character is None:
        return
    if not rules.is_caster(character):
        await message.answer("Твой класс не колдует.")
        return
    await answer_long(message, "\n".join(spells_lines(character) + ["", "Колдовать: /cast · Подготовить: /prepare"]))


@router.message(Command("prepare"))
async def cmd_prepare(message: Message, command: CommandObject) -> None:
    character = await require_character(message)
    if character is None:
        return
    names = [n.strip() for n in (command.args or "").split(",") if n.strip()]
    if not names:
        await message.answer("Пример: /prepare Лечение ран, Благословение, Щит веры\n"
                             "Жрец готовит из всего списка, волшебник — из книги заклинаний. Только на отдыхе.")
        return
    _, lines = features.prepare(message.chat.id, character, names)
    await message.answer("\n".join(lines))


@router.message(Command("learn"))
async def cmd_learn(message: Message, command: CommandObject) -> None:
    character = await require_character(message)
    if character is None:
        return
    _, lines = features.learn_spell(message.chat.id, character, (command.args or "").strip())
    await message.answer("\n".join(lines))


@router.message(Command("cantrip"))
async def cmd_cantrip(message: Message, command: CommandObject) -> None:
    character = await require_character(message)
    if character is None:
        return
    _, lines = features.learn_cantrip(message.chat.id, character, (command.args or "").strip())
    await message.answer("\n".join(lines))


@router.message(Command("recover"))
async def cmd_recover(message: Message, command: CommandObject) -> None:
    character = await require_character(message)
    if character is None:
        return
    levels = [int(t) for t in (command.args or "").replace(",", " ").split() if t.isdigit()]
    _, lines = features.arcane_recovery(message.chat.id, character, levels)
    await message.answer("\n".join(lines))


# ---------------------------------------------------------------- способности

@router.message(Command("secondwind"))
async def cmd_secondwind(message: Message) -> None:
    character = await require_character(message, need_conscious=True)
    if character:
        await _run(message, character, features.second_wind(message.chat.id, character))


@router.message(Command("surge"))
async def cmd_surge(message: Message) -> None:
    character = await require_character(message, need_conscious=True)
    if character:
        await _run(message, character, features.action_surge(message.chat.id, character))


@router.message(Command("cunning"))
async def cmd_cunning(message: Message, command: CommandObject) -> None:
    character = await require_character(message, need_conscious=True)
    if character:
        await _run(message, character, features.cunning_action(message.chat.id, character, command.args or ""))


@router.message(Command("hide"))
async def cmd_hide(message: Message) -> None:
    character = await require_character(message, need_conscious=True)
    if character:
        await _run(message, character, features.hide(message.chat.id, character))


@router.message(Command("dodge"))
async def cmd_dodge(message: Message) -> None:
    character = await require_character(message, need_conscious=True)
    if character:
        await _run(message, character, features.dodge(message.chat.id, character))


@router.message(Command("assist"))
async def cmd_assist(message: Message, command: CommandObject) -> None:
    character = await require_character(message, need_conscious=True)
    if character:
        await _run(message, character, features.assist(message.chat.id, character, command.args or ""))


@router.message(Command("shove"))
async def cmd_shove(message: Message, command: CommandObject) -> None:
    character = await require_character(message, need_conscious=True)
    if character:
        await _run(message, character, features.shove(message.chat.id, character, command.args or ""))


@router.message(Command("stabilize"))
async def cmd_stabilize(message: Message, command: CommandObject) -> None:
    character = await require_character(message, need_conscious=True)
    if character:
        await _run(message, character, features.stabilize(message.chat.id, character, command.args or ""))


@router.message(Command("channel"))
async def cmd_channel(message: Message, command: CommandObject) -> None:
    character = await require_character(message, need_conscious=True)
    if character:
        await _run(message, character, features.channel(message.chat.id, character, command.args or ""))


@router.message(Command("inspire"))
async def cmd_inspire(message: Message) -> None:
    character = await require_character(message, need_conscious=True)
    if character:
        _, lines = features.inspire(message.chat.id, character)
        await message.answer("\n".join(lines))


@router.message(Command("hitdice"))
async def cmd_hitdice(message: Message, command: CommandObject) -> None:
    character = await require_character(message)
    if character is None:
        return
    arg = (command.args or "1").strip()
    count = int(arg) if arg.isdigit() else 1
    _, lines = features.spend_hit_dice(message.chat.id, character, count)
    await message.answer("\n".join(lines))


@router.message(Command("asi"))
async def cmd_asi(message: Message, command: CommandObject) -> None:
    character = await require_character(message)
    if character is None:
        return
    tokens = (command.args or "").split()
    _, lines = features.asi(message.chat.id, character, tokens[0] if tokens else "",
                            tokens[1] if len(tokens) > 1 else "")
    await message.answer("\n".join(lines))


@router.message(Command("expertise"))
async def cmd_expertise(message: Message, command: CommandObject) -> None:
    character = await require_character(message)
    if character is None:
        return
    names = [n.strip() for n in (command.args or "").split(",") if n.strip()]
    _, lines = features.expertise(message.chat.id, character, names)
    await message.answer("\n".join(lines))


@router.message(Command("rest"))
async def cmd_rest(message: Message, command: CommandObject) -> None:
    game = await require_world(message)
    if game is None or not await require_gm(message, game):
        return
    from combat import in_combat
    if in_combat(message.chat.id):
        await message.answer("В бою отдыхать нельзя.")
        return
    kind = (command.args or "").strip().casefold()
    if kind.startswith(("корот", "short")):
        lines = features.short_rest(message.chat.id)
    elif kind.startswith(("долг", "long")):
        lines = features.long_rest(message.chat.id)
    else:
        await message.answer("Пример: /rest короткий · /rest долгий (мастер)")
        return
    await answer_long(message, "\n".join(lines))
