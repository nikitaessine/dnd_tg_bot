"""Колдовство (гл. 10–11): ячейки, концентрация, атаки заклинаниями, спасброски целей,
лечение, усиления, воскрешение. Заклинания без механики тратят ячейку и попадают в журнал.

Работает поверх db, rules, engine и combat; ничего не знает о Telegram.
"""

import db
import dice
import engine
import combat
import rules
import srd
from engine import esc, log
from spelldata import SPELLS
from srd import CON, DEX, INT, STR, WIS

CURABLE = ["ослеплён", "оглох", "парализован", "отравлен"]  # Малое восстановление (с. 90)


# ---------------------------------------------------------------- вспомогательное

def _fail(text: str) -> tuple[bool, list[str]]:
    return False, [text]


def spell_dice(spell: dict, character, slot: int) -> str:
    """Кубики урона или лечения: заговор растёт с уровнем персонажа, заклинание — с уровнем ячейки."""
    base = spell["dice"]
    if spell.get("cantrip"):
        return rules.scale_dice(base, rules.cantrip_multiplier(character["level"]))
    extra = spell.get("per_slot")
    if extra and slot > spell["level"]:
        steps = (slot - spell["level"]) // spell.get("per_slot_step", 1)
        return rules.add_dice(base, extra, steps)
    return base


def _roll(notation: str, maximize: bool = False) -> tuple[int, str]:
    parsed = dice.parse_notation(notation)
    if parsed is None:
        return 0, "0"
    count, sides, mod = parsed
    if maximize:
        rolls = [sides] * count
    else:
        rolls = dice.roll(count, sides)
    total = sum(rolls) + mod
    detail = " + ".join(map(str, rolls)) + (f" {rules.format_modifier(mod)}" if mod else "")
    return total, detail


def empowered_bonus(character, spell: dict) -> int:
    """Усиленное воплощение волшебника (с. 34): + мод. ИНТ к урону заклинания воплощения."""
    if character["char_class"] == "Волшебник" and character["level"] >= 10 and spell.get("school") == "воплощение":
        return max(0, rules.mod_of(character, INT))
    return 0


def _find_enemies(chat_id: int, names: list[str], limit: int) -> tuple[list, str | None]:
    alive = db.list_enemies(chat_id)
    if not names:
        return alive[:limit], None
    found = []
    for name in names:
        enemy = db.find_enemy(chat_id, name)
        if enemy is None:
            return [], f"Не нашёл противника «{esc(name)}». Список: /enemies"
        if enemy["id"] not in [e["id"] for e in found]:
            found.append(enemy)
    return found[:limit], None


def _find_pcs(chat_id: int, names: list[str], character, default_self: bool = True) -> tuple[list, str | None]:
    if not names:
        return ([character] if default_self else []), None
    found = []
    for name in names:
        target = db.find_character(chat_id, name)
        if target is None:
            return [], f"Не нашёл персонажа «{esc(name)}». Список: /hp"
        if target["user_id"] not in [t["user_id"] for t in found]:
            found.append(target)
    return found, None


def _consume_slot(chat_id: int, character, level: int) -> None:
    used = rules.slots_used(character)
    used[level] = used.get(level, 0) + 1
    db.update_character(chat_id, character["user_id"], slots_used={str(k): v for k, v in used.items()})


def _choose_slot(character, spell: dict, requested: int | None) -> tuple[int | None, str | None]:
    base = spell["level"]
    if base == 0:
        return 0, None
    left = rules.slots_left(character)
    top = rules.max_slot_level(character)
    if requested is not None:
        if requested < base:
            return None, f"«{esc(spell['name'])}» — заклинание {base} уровня: ячейка не ниже {base}."
        if requested > top or left.get(requested, 0) <= 0:
            return None, f"Нет свободной ячейки {requested} уровня. Свободные: {format_slots(character)}"
        return requested, None
    for level in range(base, top + 1):
        if left.get(level, 0) > 0:
            return level, None
    return None, f"Нет свободных ячеек для «{esc(spell['name'])}» ({base} ур. и выше). Отдохните: /rest"


def format_slots(character) -> str:
    total = rules.slots_total(character)
    left = rules.slots_left(character)
    if not total:
        return "нет"
    return ", ".join(f"{lvl} ур.: {left[lvl]}/{count}" for lvl, count in enumerate(total, start=1))


# ---------------------------------------------------------------- вход: колдовство

def cast(chat_id: int, character, name: str, slot: int | None = None, targets: list[str] | None = None,
         ) -> tuple[bool, list[str]]:
    """Колдует заклинание. Возвращает (успех, строки). Строки при неудаче — причина отказа."""
    targets = targets or []
    spell = SPELLS.get(name)
    if spell is None or name not in rules.castable_spells(character):
        return _fail(f"«{esc(name)}» нет среди ваших подготовленных заклинаний. Список: /spells")
    g = engine.gear(chat_id, character)
    if g["penalties"]["nonproficient"]:
        return _fail("Вы не владеете надетым доспехом или щитом — колдовать нельзя (с. 46). Снимите его: /equip")
    names = rules.cond_names(g["conds"])
    if names & srd.INCAPACITATED:
        return _fail("Персонаж не может действовать и колдовать.")
    if not character["alive"]:
        return _fail("Персонаж погиб.")

    time_ = spell.get("time", "action")
    fighting = combat.in_combat(chat_id)
    uid = character["user_id"]

    # Повторное использование уже наложенного заклинания (Духовное оружие, Пылающая сфера): без ячейки
    if spell["kind"] == "persistent" and spell["effect"] in names:
        return _reuse_persistent(chat_id, character, spell, targets, g)

    if spell.get("out_of_combat") and fighting:
        return _fail(f"«{esc(name)}» колдуется 10 минут — в бою нельзя.")

    slot_level, error = _choose_slot(character, spell, slot)
    if error:
        return _fail(error)
    leveled = spell["level"] > 0

    # Экономика действий (с. 72, 83)
    if fighting:
        problem = combat.mark_spell(chat_id, uid, time_, leveled)
        if problem:
            return _fail(problem)
        if time_ == "reaction":
            if not combat.use_reaction(chat_id, uid):
                return _fail("Реакция в этом раунде уже потрачена.")
        elif time_ == "bonus":
            problem = combat.use_bonus(chat_id, uid)
            if problem:
                return _fail(problem)
        else:
            problem = combat.use_action(chat_id, uid)
            if problem:
                return _fail(problem)
        combat.note_spell(chat_id, time_, leveled)

    # Прежняя концентрация прерывается новой (с. 83)
    lines: list[str] = []
    if spell.get("conc") and character["concentration"]:
        lines += engine.end_concentration(chat_id, character, f"новое заклинание «{name}»")
        character = engine.refresh(chat_id, character)
    if leveled:
        _consume_slot(chat_id, character, slot_level)
        character = engine.refresh(chat_id, character)

    slot_note = f" (ячейка {slot_level} ур.)" if leveled else ""
    lines.insert(0, f"✨ <b>{esc(character['name'])}</b> колдует «{esc(name)}»{slot_note}")

    handler = _HANDLERS.get(spell["kind"], _narrative)
    result = handler(chat_id, character, spell, slot_level, targets, g)
    if isinstance(result, str):  # отказ уже после траты ресурса недопустим — обработчики проверяют заранее
        return _fail(result)
    lines += result["lines"]
    if spell.get("conc") and result.get("concentrate", True):
        db.update_character(chat_id, uid, concentration=name)
    log(chat_id, character["name"], result.get("event") or f"колдует «{name}»")
    return True, lines


# ---------------------------------------------------------------- виды заклинаний

def _narrative(chat_id, character, spell, slot, targets, g) -> dict:
    note = "эффект по описанию — мастер и сюжет его учтут"
    return {"lines": [f"📖 «{esc(spell['name'])}»: {note}."], "event": f"колдует «{spell['name']}» ({note})"}


def _attack(chat_id, character, spell, slot, targets, g) -> dict:
    enemies, error = _find_enemies(chat_id, targets, 1)
    if error or not enemies:
        return {"lines": [error or "Нет цели для заклинания. Противники: /enemies"], "concentrate": False,
                "event": f"колдует «{spell['name']}», но цели нет"}
    enemy = enemies[0]
    melee = bool(spell.get("melee"))
    mode, reason = engine.pc_attack_mode(character, enemy, melee, g)
    bonus = rules.spell_attack_bonus(character)
    d, total, all_dice = dice.d20_check(bonus, mode, lucky=rules.race_info(character)["lucky"])
    names = rules.cond_names(g["conds"])
    extra = ""
    if "благословлён" in names:
        bless = dice.roll(1, 4)[0]
        total += bless
        extra = f" +{bless} (Благословение)"
    engine.consume_pc_flags(chat_id, character)
    theirs = rules.cond_names(engine.enemy_conditions(enemy))
    if "отмечен" in theirs:
        engine.remove_enemy_condition(enemy, "отмечен")
    rolls = f"[{'/'.join(map(str, all_dice))}] " if len(all_dice) > 1 else ""
    lines = [f"🎯 Атака заклинанием → <b>{esc(enemy['name'])}</b>: d20 {rolls}{d} {rules.format_modifier(bonus)}"
             f"{extra} = <b>{total}</b> против КД {enemy['armor_class']}{engine.describe_mode(mode, reason)}"]
    natural_crit = d == 20
    if not (natural_crit or (d != 1 and total >= enemy["armor_class"])):
        lines.append("❌ Промах")
        return {"lines": lines, "event": f"колдует «{spell['name']}» и промахивается по {enemy['name']}"}
    crit = natural_crit or (melee and bool(theirs & srd.MELEE_AUTO_CRIT))
    notation = spell_dice(spell, character, slot)
    dmg, detail = _roll(rules.scale_dice(notation, 2) if crit else notation)
    dmg += empowered_bonus(character, spell)
    dmg = max(1, dmg)
    _, updated, defeated = engine.enemy_damage(chat_id, enemy, dmg)
    lines.append(f"{'💥 Критическое попадание!' if crit else '✅ Попадание!'} Урон {notation}{' ×2' if crit else ''} "
                 f"({detail}) = <b>{dmg}</b> {esc(spell['dtype'])}")
    if spell.get("effect") and not defeated:
        engine.add_enemy_condition(updated, spell["effect"], rounds=spell.get("effect_rounds", 2) + 1,
                                   src=character["user_id"], spell=spell["name"])
        lines.append(f"🎯 {esc(enemy['name'])}: {esc(spell['effect'])} — следующая атака по цели с преимуществом")
    if defeated:
        lines.append(f"☠️ <b>{esc(enemy['name'])}</b> повержен!")
        lines += combat.record_defeat(chat_id, enemy)
    else:
        lines.append(f"👹 {esc(enemy['name'])}: {updated['hp']}/{updated['max_hp']} HP")
    return {"lines": lines, "concentrate": False,
            "event": f"колдует «{spell['name']}» и наносит {enemy['name']} {dmg} урона"
                     + (" — противник повержен" if defeated else "")}


def _auto(chat_id, character, spell, slot, targets, g) -> dict:
    """Волшебная стрела: снаряды попадают автоматически, урон силовым полем (с. 90)."""
    enemies, error = _find_enemies(chat_id, targets, 6)
    if error or not enemies:
        return {"lines": [error or "Нет цели для заклинания."], "event": f"колдует «{spell['name']}», но цели нет"}
    darts = spell["darts"] + (slot - spell["level"])
    damage_by_enemy: dict[int, int] = {}
    details = []
    bonus = empowered_bonus(character, spell)
    for i in range(darts):
        target = enemies[i % len(enemies)]
        dmg, _ = _roll(spell["dice"])
        if i == 0:
            dmg += bonus
        damage_by_enemy[target["id"]] = damage_by_enemy.get(target["id"], 0) + dmg
        details.append(f"{dmg}")
    lines = [f"🎯 {darts} снаряда(ов) по {' + '.join(details)} — попадают автоматически"]
    events = []
    for enemy in enemies:
        dmg = damage_by_enemy.get(enemy["id"], 0)
        if not dmg:
            continue
        fresh = db.get_enemy(enemy["id"])
        _, updated, defeated = engine.enemy_damage(chat_id, fresh, dmg)
        lines.append(f"   {esc(enemy['name'])}: −{dmg} силовое поле → " + ("☠️ повержен" if defeated else f"{updated['hp']}/{updated['max_hp']} HP"))
        events.append(f"{enemy['name']} −{dmg}" + (" (повержен)" if defeated else ""))
        if defeated:
            lines += combat.record_defeat(chat_id, fresh)
    return {"lines": lines, "concentrate": False, "event": f"колдует «{spell['name']}»: " + ", ".join(events)}


def _apply_effect(chat_id: int, character, spell: dict, enemy, dc: int) -> str:
    rounds = spell.get("effect_rounds")
    save = {"ability": spell["save"], "dc": dc} if spell.get("save_repeat") else None
    if spell.get("escape_check"):
        save = {"ability": STR, "dc": dc}
    engine.add_enemy_condition(enemy, spell["effect"], rounds=(rounds + 1) if rounds is not None else None,
                               save=save, src=character["user_id"], spell=spell["name"], data={"dc": dc})
    return f"   ➜ {esc(enemy['name'])}: {esc(spell['effect'])}"


def _save_spell(chat_id, character, spell, slot, targets, g) -> dict:
    limit = spell.get("max_targets", 1) + spell.get("per_slot_targets", 0) * max(0, slot - spell["level"])
    enemies, error = _find_enemies(chat_id, targets, limit)
    if error or not enemies:
        return {"lines": [error or "Нет целей для заклинания. Противники: /enemies"], "concentrate": False,
                "event": f"колдует «{spell['name']}», но целей нет"}
    dc = rules.spell_dc(character)
    lines = [f"🎲 Сл. спасброска {dc} ({spell['save']})"]
    total, detail, extra_total = 0, "", 0
    has_damage = bool(spell.get("dice"))
    if has_damage:
        notation = spell_dice(spell, character, slot)
        total, detail = _roll(notation)
        total += empowered_bonus(character, spell)
        line = f"💥 Урон {notation} ({detail}) = {total} {esc(spell.get('dtype', ''))}"
        if spell.get("extra_dice"):
            extra_total, extra_detail = _roll(spell["extra_dice"])
            line += f" + {spell['extra_dice']} ({extra_detail}) = {extra_total} {esc(spell.get('extra_dtype', ''))}"
        lines.append(line)
    full = total + extra_total
    potent = (character["char_class"] == "Волшебник" and character["level"] >= 6
              and spell.get("cantrip") and spell.get("school") == "воплощение")
    if spell.get("cantrip") and character["char_class"] == "Волшебник" and character["level"] >= 6:
        potent = True  # Сильный заговор действует на любые заговоры, наносящие урон (с. 34)
    events = []
    for enemy in enemies:
        enemy = db.get_enemy(enemy["id"])
        result = engine.enemy_save(enemy, spell["save"], dc)
        lines.append(result["text"])
        dmg = 0
        if has_damage:
            if result["success"]:
                dmg = full // 2 if (spell.get("half") or potent) else 0
            else:
                dmg = full
        if not result["success"] and spell.get("effect"):
            lines.append(_apply_effect(chat_id, character, spell, enemy, dc))
        if dmg > 0:
            _, updated, defeated = engine.enemy_damage(chat_id, enemy, dmg)
            lines.append(f"   −{dmg} → " + ("☠️ повержен" if defeated else f"{updated['hp']}/{updated['max_hp']} HP"))
            events.append(f"{enemy['name']} −{dmg}" + (" (повержен)" if defeated else ""))
            if defeated:
                lines += combat.record_defeat(chat_id, enemy)
        elif has_damage:
            lines.append("   без урона")
        if not has_damage:
            events.append(f"{enemy['name']}: " + ("сопротивляется" if result["success"] else spell["effect"]))
    concentrate = bool(spell.get("conc")) and any(
        rules.find_condition(engine.enemy_conditions(db.get_enemy(e["id"])), spell.get("effect", "")) for e in enemies
    ) if spell.get("effect") else bool(spell.get("conc"))
    return {"lines": lines, "concentrate": concentrate,
            "event": f"колдует «{spell['name']}»: " + ", ".join(events)}


def _sleep(chat_id, character, spell, slot, targets, g) -> dict:
    pool_notation = spell_dice(spell, character, slot)
    pool, detail = _roll(pool_notation)
    lines = [f"😴 Запас хитов {pool_notation} ({detail}) = <b>{pool}</b>"]
    candidates = [e for e in db.list_enemies(chat_id)
                  if "без сознания" not in rules.cond_names(engine.enemy_conditions(e))
                  and "нежить" not in e["etype"].casefold()]
    candidates.sort(key=lambda e: e["hp"])
    put_to_sleep = []
    for enemy in candidates:
        if enemy["hp"] > pool:
            break
        pool -= enemy["hp"]
        engine.add_enemy_condition(enemy, "без сознания", rounds=11, src=character["user_id"], spell="Усыпление")
        put_to_sleep.append(enemy["name"])
        lines.append(f"   💤 {esc(enemy['name'])} засыпает (хитов {enemy['hp']})")
    if not put_to_sleep:
        lines.append("   Никто не заснул.")
    return {"lines": lines, "concentrate": False,
            "event": f"колдует «Усыпление»: " + (", ".join(put_to_sleep) + " засыпают" if put_to_sleep else "никто не заснул")}


def _heal_amount(character, target, spell: dict, slot: int) -> tuple[int, str]:
    """Лечение: кубики + мод. заклинательной характеристики; бонусы жреца Жизни (с. 25)."""
    notation = spell_dice(spell, character, slot)
    beacon = "маяк надежды" in rules.cond_names(rules.conditions_of(target))
    maximize = beacon or (character["char_class"] == "Жрец" and character["level"] >= 17)
    total, detail = _roll(notation, maximize)
    total += rules.mod_of(character, rules.caster_ability(character))
    parts = [f"{notation}: {detail}"]
    if character["char_class"] == "Жрец":
        total += 2 + slot  # Ученик жизни
        parts.append(f"ученик жизни +{2 + slot}")
    return max(1, total), "; ".join(parts) + (" (максимум)" if maximize else "")


def _heal(chat_id, character, spell, slot, targets, g) -> dict:
    if spell.get("party") or spell.get("max_targets", 1) > 1:
        limit = spell.get("max_targets", 6)
        if targets:
            found, error = _find_pcs(chat_id, targets, character, default_self=False)
            if error:
                return {"lines": [error], "concentrate": False}
            pcs = found[:limit]
        else:
            wounded = [c for c in db.list_characters(chat_id, alive_only=True) if c["hp"] < c["max_hp"]]
            wounded.sort(key=lambda c: c["hp"])
            pcs = wounded[:limit]
    else:
        pcs, error = _find_pcs(chat_id, targets, character)
        if error:
            return {"lines": [error], "concentrate": False}
        pcs = pcs[:1]
    if not pcs:
        return {"lines": ["Все и так здоровы."], "concentrate": False, "event": f"колдует «{spell['name']}», но лечить некого"}
    lines, events = [], []
    healed_others = False
    for target in pcs:
        target = engine.refresh(chat_id, target)
        if not target["alive"]:
            lines.append(f"⚰️ {esc(target['name'])} мёртв — лечение не действует (нужно воскрешение)")
            continue
        amount, detail = _heal_amount(character, target, spell, slot)
        gained, updated = engine.pc_heal(chat_id, target, amount)
        was_down = target["hp"] == 0 and updated["hp"] > 0
        lines.append(f"💚 <b>{esc(target['name'])}</b>: +{gained} ({detail}) → {updated['hp']}/{updated['max_hp']}"
                     + (" — приходит в себя!" if was_down else ""))
        events.append(f"{target['name']} +{gained}")
        if target["user_id"] != character["user_id"]:
            healed_others = True
    if healed_others and character["char_class"] == "Жрец" and character["level"] >= 6:
        bonus = 2 + slot  # Благословенный целитель (с. 25)
        gained, _ = engine.pc_heal(chat_id, engine.refresh(chat_id, character), bonus)
        if gained:
            lines.append(f"💚 Благословенный целитель: {esc(character['name'])} +{gained}")
    return {"lines": lines, "concentrate": False, "event": f"колдует «{spell['name']}»: " + ", ".join(events)}


def _heal_fixed(chat_id, character, spell, slot, targets, g) -> dict:
    pcs, error = _find_pcs(chat_id, targets, character)
    if error:
        return {"lines": [error], "concentrate": False}
    target = pcs[0]
    amount = spell["bonus"] + spell.get("per_slot_bonus", 0) * max(0, slot - spell["level"])
    gained, updated = engine.pc_heal(chat_id, engine.refresh(chat_id, target), amount)
    return {"lines": [f"💚 <b>{esc(target['name'])}</b>: +{gained} → {updated['hp']}/{updated['max_hp']}"],
            "concentrate": False, "event": f"колдует «{spell['name']}»: {target['name']} +{gained}"}


def _buff(chat_id, character, spell, slot, targets, g) -> dict:
    kind = spell.get("target", "ally")
    if kind == "self":
        pcs = [character]
    elif kind == "party":
        pcs = [c for c in db.list_characters(chat_id, alive_only=True) if c["hp"] > 0][:6]
    elif kind == "allies":
        limit = spell.get("max_targets", 3) + spell.get("per_slot_targets", 0) * max(0, slot - spell["level"])
        found, error = _find_pcs(chat_id, targets, character)
        if error:
            return {"lines": [error], "concentrate": False}
        pcs = found[:limit]
    else:
        found, error = _find_pcs(chat_id, targets, character)
        if error:
            return {"lines": [error], "concentrate": False}
        pcs = found[:1]
    lines, events = [], []
    effect = spell["effect"]
    rounds = spell.get("rounds")
    for target in pcs:
        target = engine.refresh(chat_id, target)
        if effect == "доспехи мага" and db.equipped_item(chat_id, target["user_id"], "armor"):
            lines.append(f"⚠️ {esc(target['name'])} носит доспех — «Доспехи мага» не действуют")
            continue
        engine.add_pc_condition(chat_id, target, effect, rounds=rounds, src=character["user_id"], spell=spell["name"],
                                data={"dc": rules.spell_dc(character)})
        lines.append(f"🛡 <b>{esc(target['name'])}</b>: {esc(srd.EFFECT_LABELS.get(effect, effect))}")
        events.append(target["name"])
    return {"lines": lines, "event": f"колдует «{spell['name']}» на " + ", ".join(events)}


def _aid(chat_id, character, spell, slot, targets, g) -> dict:
    amount = spell["bonus"] * (1 + max(0, slot - spell["level"]))
    found, error = _find_pcs(chat_id, targets, character, default_self=False)
    if error:
        return {"lines": [error], "concentrate": False}
    pcs = found[:3] or [c for c in db.list_characters(chat_id, alive_only=True)][:3]
    lines, events = [], []
    for target in pcs:
        target = engine.refresh(chat_id, target)
        if rules.find_condition(rules.conditions_of(target), "подкрепление"):
            lines.append(f"⚠️ {esc(target['name'])} уже под действием Помощи")
            continue
        conds = rules.add_condition(rules.conditions_of(target), "подкрепление", rounds=None,
                                    src=character["user_id"], spell=spell["name"], data={"amount": amount})
        db.update_character(chat_id, target["user_id"], max_hp=target["max_hp"] + amount,
                            hp=target["hp"] + amount if target["hp"] > 0 else target["hp"], conditions=conds)
        lines.append(f"💪 <b>{esc(target['name'])}</b>: максимум хитов +{amount} на 8 часов")
        events.append(target["name"])
    return {"lines": lines, "concentrate": False, "event": f"колдует «Помощь» на " + ", ".join(events)}


def _cure(chat_id, character, spell, slot, targets, g) -> dict:
    pcs, error = _find_pcs(chat_id, targets, character)
    if error:
        return {"lines": [error], "concentrate": False}
    target = engine.refresh(chat_id, pcs[0])
    conds = rules.conditions_of(target)
    present = [x for x in CURABLE if rules.find_condition(conds, x)]
    if not present:
        return {"lines": [f"У {esc(target['name'])} нечего снимать ({', '.join(CURABLE)})."], "concentrate": False,
                "event": f"колдует «{spell['name']}», но снимать нечего"}
    engine.remove_pc_condition(chat_id, target, present[0])
    return {"lines": [f"🌿 {esc(target['name'])}: снято состояние «{present[0]}»"], "concentrate": False,
            "event": f"колдует «{spell['name']}»: {target['name']} избавляется от «{present[0]}»"}


def _stabilize(chat_id, character, spell, slot, targets, g) -> dict:
    pcs, error = _find_pcs(chat_id, targets, character, default_self=False)
    if error or not pcs:
        return {"lines": [error or "Укажите персонажа: /cast Сохранение жизни Гарен"], "concentrate": False}
    target = engine.refresh(chat_id, pcs[0])
    if not target["alive"] or target["hp"] > 0:
        return {"lines": [f"{esc(target['name'])} не нуждается в стабилизации."], "concentrate": False}
    db.update_character(chat_id, target["user_id"], death_successes=3, death_failures=0)
    return {"lines": [f"🕊 <b>{esc(target['name'])}</b> стабилизирован (без сознания, хитов 0)"], "concentrate": False,
            "event": f"{target['name']} стабилизирован заклинанием «{spell['name']}»"}


def _revive(chat_id, character, spell, slot, targets, g) -> dict:
    found, error = _find_pcs(chat_id, targets, character, default_self=False)
    dead = [c for c in found if not c["alive"]] if found else [c for c in db.list_characters(chat_id) if not c["alive"]]
    if error or not dead:
        return {"lines": [error or "Нет погибших персонажей. Укажите имя: /cast Возвращение к жизни Гарен"],
                "concentrate": False}
    target = dead[0]
    now = db.current_situation_number(chat_id)
    window = 0 if spell.get("window") == "scene" else 10
    if now - target["died_scene"] > window:
        limit = "минуты" if window == 0 else "10 дней (около 10 сцен)"
        return {"lines": [f"⚠️ {esc(target['name'])} мёртв слишком давно — заклинание действует, если смерть "
                          f"наступила не более {limit} назад."], "concentrate": False,
                "event": f"пытается воскресить {target['name']}, но слишком поздно"}
    db.update_character(chat_id, target["user_id"], alive=1, hp=1, death_successes=0, death_failures=0, conditions=[])
    return {"lines": [f"🌅 <b>{esc(target['name'])}</b> возвращается к жизни с 1 хитом!"], "concentrate": False,
            "event": f"{target['name']} возвращён к жизни заклинанием «{spell['name']}»"}


def _aura(chat_id, character, spell, slot, targets, g) -> dict:
    notation = spell_dice(spell, character, slot)
    dc = rules.spell_dc(character)
    engine.add_pc_condition(chat_id, character, "духовные стражи", rounds=100, src=character["user_id"],
                            spell=spell["name"], data={"dice": notation, "dc": dc})
    return {"lines": [f"👼 Духовные стражи окружают героя: враги в начале своего хода получают {notation} излучения "
                      f"(спасбросок МДР сл. {dc}, при успехе — половина). Считается, что враги в радиусе 15 футов."],
            "event": f"колдует «{spell['name']}»: вокруг вспыхивают духовные стражи"}


def _persistent(chat_id, character, spell, slot, targets, g) -> dict:
    """Духовное оружие и Пылающая сфера: создание эффекта и первая атака."""
    engine.add_pc_condition(chat_id, character, spell["effect"], rounds=spell["rounds"] + 1,
                            src=character["user_id"], spell=spell["name"], data={"slot": slot})
    result = _persistent_strike(chat_id, character, spell, slot, targets, g)
    result["lines"].insert(0, f"🔮 Появляется эффект «{esc(spell['effect'])}»: дальше бонусным действием — "
                              f"/cast {esc(spell['name'])} <враг> (без ячейки)")
    return result


def _persistent_strike(chat_id, character, spell, slot, targets, g) -> dict:
    enemies, error = _find_enemies(chat_id, targets, 1)
    if error or not enemies:
        return {"lines": [error or "Нет цели."], "event": f"колдует «{spell['name']}»", "concentrate": True}
    enemy = enemies[0]
    notation = spell_dice(spell, character, slot)
    lines: list[str] = []
    if spell["name"] == "Духовное оружие":
        mode, reason = engine.pc_attack_mode(character, enemy, True, g)
        bonus = rules.spell_attack_bonus(character)
        d, total, _ = dice.d20_check(bonus, mode, lucky=rules.race_info(character)["lucky"])
        lines.append(f"🗡 Духовное оружие → {esc(enemy['name'])}: d20 {d} {rules.format_modifier(bonus)} = "
                     f"<b>{total}</b> против КД {enemy['armor_class']}{engine.describe_mode(mode, reason)}")
        crit = d == 20
        if not (crit or (d != 1 and total >= enemy["armor_class"])):
            lines.append("❌ Промах")
            return {"lines": lines, "concentrate": False, "event": "духовное оружие промахивается"}
        dmg, detail = _roll(rules.scale_dice(notation, 2) if crit else notation)
        dmg += rules.mod_of(character, rules.caster_ability(character)) + empowered_bonus(character, spell)
        dmg = max(1, dmg)
    else:  # Пылающая сфера: спасбросок ЛОВ, при успехе урона нет
        dc = rules.spell_dc(character)
        result = engine.enemy_save(enemy, DEX, dc)
        lines.append(result["text"])
        if result["success"]:
            lines.append("   Огонь не задевает цель.")
            return {"lines": lines, "concentrate": True, "event": "пылающая сфера не задевает цель"}
        dmg, detail = _roll(notation)
        dmg += empowered_bonus(character, spell)
    _, updated, defeated = engine.enemy_damage(chat_id, enemy, dmg)
    lines.append(f"✅ Урон {notation} ({detail}) = <b>{dmg}</b> {esc(spell['dtype'])} → "
                 + ("☠️ повержен" if defeated else f"{updated['hp']}/{updated['max_hp']} HP"))
    if defeated:
        lines += combat.record_defeat(chat_id, enemy)
    return {"lines": lines, "concentrate": True,
            "event": f"«{spell['name']}» наносит {enemy['name']} {dmg} урона" + (" — противник повержен" if defeated else "")}


def _reuse_persistent(chat_id, character, spell, targets, g) -> tuple[bool, list[str]]:
    uid = character["user_id"]
    problem = combat.use_bonus(chat_id, uid)
    if problem:
        return _fail(problem)
    entry = rules.find_condition(g["conds"], spell["effect"])
    slot = (entry or {}).get("data", {}).get("slot", spell["level"])
    result = _persistent_strike(chat_id, character, spell, slot, targets, g)
    lines = [f"✨ <b>{esc(character['name'])}</b> направляет «{esc(spell['name'])}» (бонусное действие)"] + result["lines"]
    log(chat_id, character["name"], result["event"])
    return True, lines


_HANDLERS = {
    "attack": _attack, "auto": _auto, "save": _save_spell, "sleep": _sleep, "heal": _heal,
    "heal_fixed": _heal_fixed, "buff": _buff, "aid": _aid, "cure": _cure, "stabilize": _stabilize,
    "revive": _revive, "aura": _aura, "persistent": _persistent, "narrative": _narrative,
}
