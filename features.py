"""Способности классов, отдых, действия боя и развитие персонажа.

Работает поверх db, rules, engine и combat; ничего не знает о Telegram. Функции возвращают
(успех, строки).
"""

import db
import dice
import engine
import combat
import rules
import srd
from engine import esc, log
from spelldata import SPELLS, SPELL_LISTS, is_class_spell
from srd import CON, DEX, INT, STR, WIS


def _fail(text: str) -> tuple[bool, list[str]]:
    return False, [text]


def _uses(character) -> dict:
    return rules.jload(character, "uses", {})


def _spend(chat_id: int, character, key: str) -> None:
    uses = _uses(character)
    uses[key] = uses.get(key, 0) + 1
    db.update_character(chat_id, character["user_id"], uses=uses)


def _incapacitated(character) -> bool:
    return bool(rules.cond_names(rules.conditions_of(character)) & srd.INCAPACITATED) or character["hp"] <= 0


# ---------------------------------------------------------------- способности воина

def second_wind(chat_id: int, character) -> tuple[bool, list[str]]:
    """Второе дыхание (с. 27): бонусное действие, 1d10 + уровень воина хитов, раз за отдых."""
    if character["char_class"] != "Воин":
        return _fail("Это способность воина.")
    if _incapacitated(character):
        return _fail("Персонаж не может действовать.")
    if _uses(character).get("second_wind", 0) >= 1:
        return _fail("Второе дыхание уже использовано — восстановится после отдыха.")
    problem = combat.use_bonus(chat_id, character["user_id"])
    if problem:
        return _fail(problem)
    total, detail = _roll_str("1d10", character["level"])
    _spend(chat_id, character, "second_wind")
    gained, updated = engine.pc_heal(chat_id, engine.refresh(chat_id, character), total)
    log(chat_id, character["name"], f"использует Второе дыхание (+{gained} хитов)")
    return True, [f"💨 <b>{esc(character['name'])}</b> — Второе дыхание: {detail} = {total}, "
                  f"+{gained} → {updated['hp']}/{updated['max_hp']}"]


def _roll_str(notation: str, bonus: int = 0) -> tuple[int, str]:
    total, results, _ = dice.roll_notation(notation)
    total += bonus
    return total, f"{notation}{rules.format_modifier(bonus) if bonus else ''} ({'+'.join(map(str, results))})"


def action_surge(chat_id: int, character) -> tuple[bool, list[str]]:
    """Всплеск действий (с. 27): одно дополнительное действие в этот ход."""
    if character["char_class"] != "Воин" or character["level"] < 2:
        return _fail("Всплеск действий — способность воина со 2 уровня.")
    if not combat.in_combat(chat_id):
        return _fail("Всплеск действий нужен в бою — в свой ход.")
    error = combat.turn_error(chat_id, character["user_id"])
    if error:
        return _fail(error)
    uses = _uses(character)
    if uses.get("action_surge", 0) >= srd.action_surge_uses(character["level"]):
        return _fail("Всплеск действий уже использован — восстановится после отдыха.")
    turn = combat.turn_state(chat_id)
    if turn.get("surge"):
        return _fail("В один ход можно использовать Всплеск действий только раз.")
    turn["surge"], turn["action"] = 1, 0
    combat._save_turn(chat_id, turn)
    _spend(chat_id, character, "action_surge")
    log(chat_id, character["name"], "использует Всплеск действий")
    return True, [f"⚡ <b>{esc(character['name'])}</b> — Всплеск действий! Ещё одно действие в этом ходу."]


# ---------------------------------------------------------------- способности плута и действия боя

def _hide_check(chat_id: int, character) -> tuple[bool, str]:
    g = engine.gear(chat_id, character)
    bonus, level, _ = rules.check_bonus(character, "Скрытность")
    advs, disadvs = [], []
    if g["penalties"]["stealth"]:
        disadvs.append("доспех")
    if g["penalties"]["nonproficient"]:
        disadvs.append("доспех без мастерства")
    if rules.exhaustion_of(character) >= 1:
        disadvs.append("истощение")
    mode, reason = rules.combine_mode(advs, disadvs)
    floor = rules.reliable_talent_floor(character, level)
    value, total, _ = dice.d20_check(bonus, mode, lucky=rules.race_info(character)["lucky"], floor=floor)
    enemies = db.list_enemies(chat_id)
    dc = max((10 + e["save_bonus"] for e in enemies), default=10)
    success = total >= dc
    text = (f"🫥 <b>{esc(character['name'])}</b> пытается скрыться: Скрытность d20 {value} "
            f"{rules.format_modifier(bonus)} = <b>{total}</b> против пассивного Восприятия {dc}"
            f"{engine.describe_mode(mode, reason)} — {'✅ скрыт' if success else '❌ замечен'}")
    return success, text


def hide(chat_id: int, character, bonus_action: bool = False) -> tuple[bool, list[str]]:
    if _incapacitated(character):
        return _fail("Персонаж не может действовать.")
    if bonus_action:
        if character["char_class"] != "Плут" or character["level"] < 2:
            return _fail("Скрыться бонусным действием может плут со 2 уровня (Хитрое действие).")
        problem = combat.use_bonus(chat_id, character["user_id"])
    else:
        problem = combat.use_action(chat_id, character["user_id"])
    if problem:
        return _fail(problem)
    success, text = _hide_check(chat_id, character)
    if success:
        engine.add_pc_condition(chat_id, character, "скрыт", rounds=None)
    log(chat_id, character["name"], "пытается скрыться — " + ("успешно" if success else "безуспешно"))
    return True, [text]


def cunning_action(chat_id: int, character, mode: str) -> tuple[bool, list[str]]:
    """Хитрое действие плута (с. 30): бонусное действие — Рывок, Отход или Скрыться."""
    if character["char_class"] != "Плут" or character["level"] < 2:
        return _fail("Хитрое действие — способность плута со 2 уровня.")
    mode = mode.strip().casefold()
    if mode.startswith("скры"):
        return hide(chat_id, character, bonus_action=True)
    if mode.startswith("рыв") or mode.startswith("отх"):
        problem = combat.use_bonus(chat_id, character["user_id"])
        if problem:
            return _fail(problem)
        label = "Рывок" if mode.startswith("рыв") else "Отход"
        log(chat_id, character["name"], f"Хитрое действие: {label}")
        return True, [f"🏃 <b>{esc(character['name'])}</b> — Хитрое действие: {label}"]
    return _fail("Хитрое действие: /cunning рывок | отход | скрыться")


def dodge(chat_id: int, character) -> tuple[bool, list[str]]:
    """Уклонение (с. 75): до начала следующего хода атаки по вам с помехой, преимущество на ЛОВ-спасброски."""
    if _incapacitated(character):
        return _fail("Персонаж не может действовать.")
    problem = combat.use_action(chat_id, character["user_id"])
    if problem:
        return _fail(problem)
    engine.add_pc_condition(chat_id, character, "уклоняется", rounds=1)
    log(chat_id, character["name"], "уклоняется")
    return True, [f"🛡 <b>{esc(character['name'])}</b> уклоняется: атаки по нему с помехой до его следующего хода"]


def assist(chat_id: int, character, target_name: str) -> tuple[bool, list[str]]:
    """Помощь (с. 75): союзник получает преимущество на следующую проверку или атаку."""
    if _incapacitated(character):
        return _fail("Персонаж не может действовать.")
    target = db.find_character(chat_id, target_name) if target_name else None
    if target is None or target["user_id"] == character["user_id"]:
        return _fail("Кому помочь? /assist Имя")
    problem = combat.use_action(chat_id, character["user_id"])
    if problem:
        return _fail(problem)
    engine.add_pc_condition(chat_id, target, "помощь", rounds=2)
    log(chat_id, character["name"], f"помогает {target['name']}")
    return True, [f"🤝 <b>{esc(character['name'])}</b> помогает <b>{esc(target['name'])}</b>: "
                  "преимущество на следующую атаку или проверку"]


def shove(chat_id: int, character, enemy_name: str) -> tuple[bool, list[str]]:
    """Толчок (с. 77): состязание Атлетики против Атлетики/Акробатики цели; успех — сбит с ног."""
    if _incapacitated(character):
        return _fail("Персонаж не может действовать.")
    enemies = db.list_enemies(chat_id)
    enemy = db.find_enemy(chat_id, enemy_name) if enemy_name else (enemies[0] if len(enemies) == 1 else None)
    if enemy is None:
        return _fail("Кого толкнуть? /shove Имя врага")
    problem = combat.use_action(chat_id, character["user_id"])
    if problem:
        return _fail(problem)
    bonus, level, _ = rules.check_bonus(character, "Атлетика")
    floor = rules.reliable_talent_floor(character, level)
    mine, my_total, _ = dice.d20_check(bonus, lucky=rules.race_info(character)["lucky"], floor=floor)
    names = rules.cond_names(engine.enemy_conditions(enemy))
    auto = bool(names & srd.INCAPACITATED)
    theirs, their_total, _ = dice.d20_check(enemy["save_bonus"])
    success = auto or my_total > their_total  # при ничьей всё остаётся как было (с. 61)
    text = (f"💪 <b>{esc(character['name'])}</b> толкает <b>{esc(enemy['name'])}</b>: Атлетика {my_total} "
            f"против {their_total}" + (" (цель недееспособна — успех автоматически)" if auto else ""))
    if success:
        engine.add_enemy_condition(enemy, "сбит с ног", rounds=3)
        text += f" — ✅ сбит с ног"
    else:
        text += " — ❌ устоял"
    log(chat_id, character["name"], f"толкает {enemy['name']}: " + ("сбивает с ног" if success else "не удаётся"))
    return True, [text]


def stabilize(chat_id: int, character, target_name: str) -> tuple[bool, list[str]]:
    """Стабилизация (с. 79): действие, проверка Мудрости (Медицина) сл. 10."""
    if _incapacitated(character):
        return _fail("Персонаж не может действовать.")
    target = db.find_character(chat_id, target_name) if target_name else None
    if target is None or not target["alive"] or target["hp"] > 0:
        return _fail("Кого стабилизировать? Нужен персонаж с 0 хитов: /stabilize Имя")
    problem = combat.use_action(chat_id, character["user_id"])
    if problem:
        return _fail(problem)
    bonus, level, _ = rules.check_bonus(character, "Медицина")
    d, total, _ = dice.d20_check(bonus, lucky=rules.race_info(character)["lucky"],
                                 floor=rules.reliable_talent_floor(character, level))
    text = (f"🩹 <b>{esc(character['name'])}</b> оказывает первую помощь <b>{esc(target['name'])}</b>: "
            f"Медицина d20 {d} {rules.format_modifier(bonus)} = <b>{total}</b> против 10")
    if total >= 10:
        db.update_character(chat_id, target["user_id"], death_successes=3, death_failures=0)
        text += " — ✅ стабилен"
        log(chat_id, character["name"], f"стабилизирует {target['name']}")
    else:
        text += " — ❌ не получилось"
    return True, [text]


# ---------------------------------------------------------------- Божественный канал жреца

def channel(chat_id: int, character, mode: str) -> tuple[bool, list[str]]:
    """Божественный канал (с. 24–25): Изгнание нежити или Сохранение жизни."""
    if character["char_class"] != "Жрец" or character["level"] < 2:
        return _fail("Божественный канал — способность жреца со 2 уровня.")
    if _incapacitated(character):
        return _fail("Персонаж не может действовать.")
    if _uses(character).get("channel", 0) >= srd.channel_divinity_uses(character["level"]):
        return _fail("Божественный канал исчерпан — восстановится после отдыха.")
    m = mode.strip().casefold()
    if m.startswith("сохр") or m.startswith("исц") or m.startswith("preserve"):
        problem = combat.use_action(chat_id, character["user_id"])
        if problem:
            return _fail(problem)
        _spend(chat_id, character, "channel")
        return True, _preserve_life(chat_id, character)
    if m.startswith("изг") or m.startswith("неж") or m.startswith("turn"):
        problem = combat.use_action(chat_id, character["user_id"])
        if problem:
            return _fail(problem)
        _spend(chat_id, character, "channel")
        return True, _turn_undead(chat_id, character)
    return _fail("Божественный канал: /channel сохранение | изгнание")


def _preserve_life(chat_id: int, character) -> list[str]:
    pool = 5 * character["level"]
    lines = [f"🌟 <b>{esc(character['name'])}</b> — Сохранение жизни: запас лечения {pool} "
             "(не выше половины максимума хитов каждого)"]
    wounded = [c for c in db.list_characters(chat_id, alive_only=True) if c["hp"] < c["max_hp"] // 2]
    wounded.sort(key=lambda c: c["hp"])
    for target in wounded:
        if pool <= 0:
            break
        room = target["max_hp"] // 2 - target["hp"]
        amount = min(room, pool)
        gained, updated = engine.pc_heal(chat_id, target, amount)
        pool -= gained
        lines.append(f"   💚 {esc(target['name'])}: +{gained} → {updated['hp']}/{updated['max_hp']}")
    if len(lines) == 1:
        lines.append("   Никто не ранен настолько, чтобы лечение сработало (действует до половины хитов).")
    log(chat_id, character["name"], "использует Божественный канал: Сохранение жизни")
    return lines


def _turn_undead(chat_id: int, character) -> list[str]:
    dc = rules.spell_dc(character)
    undead = [e for e in db.list_enemies(chat_id) if "нежить" in e["etype"].casefold()]
    lines = [f"☀️ <b>{esc(character['name'])}</b> — Изгнание нежити (спасбросок МДР сл. {dc})"]
    destroy_cr = {5: 0.5, 8: 1, 11: 2, 14: 3, 17: 4}
    threshold = max((cr for lvl, cr in destroy_cr.items() if character["level"] >= lvl), default=-1)
    if not undead:
        lines.append("   Нежити рядом нет.")
    for enemy in undead:
        result = engine.enemy_save(enemy, WIS, dc)
        lines.append(result["text"])
        if result["success"]:
            continue
        if enemy["cr"] <= threshold:
            _, updated, defeated = engine.enemy_damage(chat_id, enemy, enemy["hp"])
            lines.append(f"   💥 {esc(enemy['name'])} уничтожен!")
            lines += combat.record_defeat(chat_id, enemy)
        else:
            engine.add_enemy_condition(enemy, "испуган", rounds=11, src=character["user_id"], spell="Изгнание нежити")
            lines.append(f"   😱 {esc(enemy['name'])} изгнан на минуту")
    log(chat_id, character["name"], "использует Божественный канал: Изгнание нежити")
    return lines


# ---------------------------------------------------------------- отдых (с. 70)

def short_rest(chat_id: int) -> list[str]:
    """Короткий отдых (не меньше часа): способности «за отдых» восстанавливаются,
    игроки могут потратить кости хитов (/hitdice)."""
    lines = ["⏳ <b>Короткий отдых</b> (не меньше часа): восстановлены Второе дыхание, Всплеск действий "
             "и Божественный канал. Потратить кости хитов: /hitdice [сколько]"]
    for c in db.list_characters(chat_id, alive_only=True):
        uses = _uses(c)
        for key in ("second_wind", "action_surge", "channel"):
            uses.pop(key, None)
        uses["short_rest"] = 1
        # Спасброски от смерти сбрасываются, когда персонаж приходит в себя; стабильный отдыхает
        db.update_character(chat_id, c["user_id"], uses=uses)
    log(chat_id, "Мастер", "отряд отдохнул: короткий отдых")
    return lines


def long_rest(chat_id: int) -> list[str]:
    """Долгий отдых (не меньше 8 часов, с. 70): хиты, ячейки, способности, кости хитов (половина),
    истощение −1."""
    lines = ["🌙 <b>Долгий отдых</b> (8 часов):"]
    for c in db.list_characters(chat_id, alive_only=True):
        conds = rules.conditions_of(c)
        max_hp = c["max_hp"]
        aid = rules.find_condition(conds, "подкрепление")
        if aid:
            max_hp = max(1, max_hp - aid["data"].get("amount", 0))
        regained_dice = max(1, c["level"] // 2)
        used = max(0, c["hit_dice_used"] - regained_dice)
        exhaustion = max(0, rules.exhaustion_of(c) - 1)
        db.update_character(
            chat_id, c["user_id"], hp=max_hp, max_hp=max_hp, temp_hp=0, hit_dice_used=used,
            slots_used={}, uses={}, exhaustion=exhaustion, death_successes=0, death_failures=0,
            conditions=[], concentration="",
        )
        lines.append(f"   • {esc(c['name'])}: {max_hp}/{max_hp} HP, кости хитов {c['level'] - used}/{c['level']}"
                     + (f", истощение {exhaustion}" if exhaustion or rules.exhaustion_of(c) else ""))
    log(chat_id, "Мастер", "отряд отдохнул: долгий отдых")
    return lines


def spend_hit_dice(chat_id: int, character, count: int) -> tuple[bool, list[str]]:
    """Кости хитов на коротком отдыхе (с. 70): кубик хитов + мод. ТЕЛ (минимум 0) за кость."""
    if combat.in_combat(chat_id):
        return _fail("В бою кости хитов не тратятся — только на коротком отдыхе.")
    if not character["alive"]:
        return _fail("Персонаж погиб.")
    if not _uses(character).get("short_rest"):
        return _fail("Кости хитов тратятся на коротком отдыхе. Мастер начинает его: /rest short")
    left = rules.hit_dice_left(character)
    count = max(1, count)
    if left <= 0:
        return _fail("Кости хитов закончились — восстановятся частично после долгого отдыха.")
    count = min(count, left)
    die = rules.hit_die_of(character)
    con = rules.mod_of(character, CON)
    total, parts = 0, []
    for _ in range(count):
        roll = dice.roll(1, die)[0]
        gain = max(0, roll + con)
        total += gain
        parts.append(f"d{die}={roll}{rules.format_modifier(con)}")
    gained, updated = engine.pc_heal(chat_id, character, total)
    db.update_character(chat_id, character["user_id"], hit_dice_used=character["hit_dice_used"] + count)
    log(chat_id, character["name"], f"тратит кости хитов (+{gained})")
    return True, [f"🍞 <b>{esc(character['name'])}</b> тратит {count} кост(ь) хитов ({', '.join(parts)}): "
                  f"+{gained} → {updated['hp']}/{updated['max_hp']} (осталось костей {left - count})"]


def arcane_recovery(chat_id: int, character, levels: list[int]) -> tuple[bool, list[str]]:
    """Магическое восстановление (с. 33): раз в день на коротком отдыхе, суммарный уровень
    ячеек не больше половины уровня волшебника (вверх), ни одной ячейки 6 уровня и выше."""
    if character["char_class"] != "Волшебник":
        return _fail("Магическое восстановление — способность волшебника.")
    if combat.in_combat(chat_id):
        return _fail("Только на коротком отдыхе.")
    uses = _uses(character)
    if not uses.get("short_rest"):
        return _fail("Магическое восстановление — на коротком отдыхе (/rest short).")
    if uses.get("arcane_recovery"):
        return _fail("Сегодня уже использовано — снова после долгого отдыха.")
    budget = rules.arcane_recovery_budget(character["level"])
    if not levels or sum(levels) > budget or any(l >= 6 or l < 1 for l in levels):
        return _fail(f"Можно вернуть ячейки суммарным уровнем до {budget} (без 6 ур. и выше). "
                     f"Например: /recover {min(budget, 2)}")
    used = rules.slots_used(character)
    for lvl in levels:
        if used.get(lvl, 0) <= 0:
            return _fail(f"Нет потраченной ячейки {lvl} уровня.")
        used[lvl] -= 1
    uses["arcane_recovery"] = 1
    db.update_character(chat_id, character["user_id"], slots_used={str(k): v for k, v in used.items()}, uses=uses)
    return True, [f"🔮 <b>{esc(character['name'])}</b> возвращает ячейки: {', '.join(f'{l} ур.' for l in levels)}"]


# ---------------------------------------------------------------- вдохновение (с. 37)

def inspire(chat_id: int, character) -> tuple[bool, list[str]]:
    if not character["inspiration"]:
        return _fail("У вас нет вдохновения. Его выдаёт мастер за хорошую игру.")
    db.update_character(chat_id, character["user_id"], inspiration=0)
    engine.add_pc_condition(chat_id, character, "вдохновлён", rounds=None)
    log(chat_id, character["name"], "использует вдохновение")
    return True, [f"🌟 <b>{esc(character['name'])}</b> использует вдохновение: преимущество на следующий бросок"]


# ---------------------------------------------------------------- развитие персонажа

def asi(chat_id: int, character, first: str, second: str) -> tuple[bool, list[str]]:
    """Повышение характеристик (с. 12): одну на 2 или две на 1; не выше 20."""
    if character["asi_pending"] <= 0:
        return _fail("Нет доступных повышений характеристик.")
    a = dice.match_name(first, srd.ABILITIES)
    b = dice.match_name(second, srd.ABILITIES) if second else a
    if a is None or b is None:
        return _fail("Укажите характеристики: /asi Сила Сила (+2) или /asi Сила Ловкость (по +1)")
    stats = rules.stats_of(character)
    before = dict(stats)
    if a == b:
        stats[a] += 2
    else:
        stats[a] += 1
        stats[b] += 1
    if any(stats[x] > 20 for x in (a, b)):
        return _fail("Характеристика не может превышать 20.")
    fields = {"stats": stats, "asi_pending": character["asi_pending"] - 1}
    hp_delta = rules.con_change_hp(character["level"], before[CON], stats[CON])
    if hp_delta:
        fields["max_hp"] = character["max_hp"] + hp_delta
        fields["hp"] = character["hp"] + hp_delta if character["hp"] > 0 else character["hp"]
    db.update_character(chat_id, character["user_id"], **fields)
    change = f"{a} +2" if a == b else f"{a} +1, {b} +1"
    log(chat_id, character["name"], f"повышает характеристики: {change}")
    extra = f" Максимум хитов {'+' if hp_delta > 0 else ''}{hp_delta}." if hp_delta else ""
    return True, [f"📈 <b>{esc(character['name'])}</b>: {change}.{extra}"]


def expertise(chat_id: int, character, names: list[str]) -> tuple[bool, list[str]]:
    """Компетентность плута (с. 29): бонус мастерства удваивается для выбранных навыков."""
    if character["expertise_pending"] <= 0:
        return _fail("Нет доступной компетентности.")
    known = rules.skills_of(character)
    have = rules.expertise_of(character)
    picked: list[str] = []
    for n in names:
        skill = dice.match_name(n, sorted(known))
        if skill is None or skill in have or skill in picked:
            return _fail(f"«{esc(n)}» — нужен навык, которым вы владеете и который ещё без компетентности. "
                         f"Ваши навыки: {', '.join(sorted(known - have))}")
        picked.append(skill)
    if len(picked) != min(2, character["expertise_pending"]):
        return _fail(f"Выберите {min(2, character['expertise_pending'])} навыка: /expertise Скрытность Восприятие")
    db.update_character(chat_id, character["user_id"], expertise=sorted(have | set(picked)),
                        expertise_pending=character["expertise_pending"] - len(picked))
    return True, [f"🎓 <b>{esc(character['name'])}</b>: компетентность в навыках {', '.join(picked)}"]


def learn_spell(chat_id: int, character, name: str) -> tuple[bool, list[str]]:
    """Волшебник записывает заклинание в книгу (с. 33): два новых за уровень."""
    if character["char_class"] != "Волшебник":
        return _fail("Книга заклинаний — у волшебника.")
    if character["learn_pending"] <= 0:
        return _fail("Новых заклинаний для книги нет — они даются при повышении уровня.")
    known = rules.spellbook_of(character)
    options = [s for lvl in range(1, rules.max_slot_level(character) + 1)
               for s in SPELL_LISTS["Волшебник"].get(lvl, []) if s not in known]
    spell = dice.match_name(name, options)
    if spell is None:
        return _fail(f"Такого заклинания нет среди доступных вам. Примеры: {', '.join(options[:8])}…")
    db.update_character(chat_id, character["user_id"], spellbook=known + [spell],
                        learn_pending=character["learn_pending"] - 1)
    return True, [f"📖 <b>{esc(character['name'])}</b> записывает в книгу: {esc(spell)}"]


def learn_cantrip(chat_id: int, character, name: str) -> tuple[bool, list[str]]:
    if not rules.is_caster(character):
        return _fail("Заговоры — у заклинателей.")
    if character["cantrip_pending"] <= 0:
        return _fail("Новых заговоров нет — они даются на 4 и 10 уровнях.")
    known = rules.cantrips_of(character)
    options = [s for s in SPELL_LISTS[srd.CLASSES[rules.class_of(character)]["spell_class"]][0] if s not in known]
    spell = dice.match_name(name, options)
    if spell is None:
        return _fail(f"Доступные заговоры: {', '.join(options)}")
    db.update_character(chat_id, character["user_id"], cantrips=known + [spell],
                        cantrip_pending=character["cantrip_pending"] - 1)
    return True, [f"✨ <b>{esc(character['name'])}</b> выучивает заговор: {esc(spell)}"]


def prepare(chat_id: int, character, names: list[str]) -> tuple[bool, list[str]]:
    """Подготовка заклинаний (с. 23, 32): мод. характеристики + уровень штук; после долгого отдыха."""
    if not rules.is_caster(character):
        return _fail("Подготовка заклинаний — у жреца и волшебника.")
    if combat.in_combat(chat_id):
        return _fail("В бою список заклинаний не меняется.")
    class_name = rules.class_of(character)
    limit = rules.prepared_limit(character)
    domain = set(rules.domain_spells(character))
    max_level = rules.max_slot_level(character)
    chosen: list[str] = []
    for n in names:
        if class_name == "Волшебник":
            pool = [s for s in rules.spellbook_of(character) if 1 <= SPELLS[s]["level"] <= max_level]
        else:
            pool = [s for lvl in range(1, max_level + 1) for s in SPELL_LISTS["Жрец"].get(lvl, [])]
        spell = dice.match_name(n, pool)
        if spell is None:
            hint = "из вашей книги заклинаний" if class_name == "Волшебник" else "из списка жреца"
            return _fail(f"«{esc(n)}» нельзя подготовить ({hint}, уровня не выше {max_level}).")
        if spell not in chosen and spell not in domain:
            chosen.append(spell)
    if len(chosen) > limit:
        return _fail(f"Можно подготовить {limit} заклинаний (мод. + уровень), а выбрано {len(chosen)}. "
                     "Доменные заклинания жреца не считаются.")
    db.update_character(chat_id, character["user_id"], prepared=chosen)
    return True, [f"📕 <b>{esc(character['name'])}</b> подготовил ({len(chosen)}/{limit}): "
                  + (", ".join(chosen) if chosen else "ничего")]
