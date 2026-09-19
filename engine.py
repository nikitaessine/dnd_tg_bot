"""Игровая логика поверх базы: урон и лечение, спасброски, концентрация, состояния, опыт.

Ничего не знает о Telegram. Функции возвращают строки для чата (HTML) и пишут важные
события в журнал сцены (kind='event'), чтобы следующая сцена их учла.
"""

import html

import db
import dice
import rules
import srd
from srd import CON, DEX, STR, WIS


def esc(text) -> str:
    return html.escape(str(text), quote=False)


def log(chat_id: int, who: str, text: str) -> None:
    db.save_action(chat_id, who, text, kind="event")


# ---------------------------------------------------------------- снаряжение

def gear(chat_id: int, character) -> dict:
    """Надетое снаряжение и производные величины."""
    uid = character["user_id"]
    weapon = db.equipped_item(chat_id, uid, "weapon")
    armor_item = db.equipped_item(chat_id, uid, "armor")
    shield = db.equipped_item(chat_id, uid, "shield")
    armor = rules.armor_info(armor_item)
    conds = rules.conditions_of(character)
    ac, ac_parts = rules.armor_class(character, armor, shield, conds)
    penalties = rules.armor_penalties(character, armor, shield)
    return {
        "weapon": weapon, "armor_item": armor_item, "armor": armor, "shield": shield, "conds": conds,
        "ac": ac, "ac_parts": ac_parts, "penalties": penalties,
        "profile": rules.attack_profile(character, weapon, shield, conds),
    }


def refresh(chat_id: int, character):
    return db.get_character(chat_id, character["user_id"])


# ---------------------------------------------------------------- состояния персонажей и противников

def set_pc_conditions(chat_id: int, character, conds: list[dict]):
    return db.update_character(chat_id, character["user_id"], conditions=conds)


def add_pc_condition(chat_id: int, character, name: str, **kw):
    conds = rules.add_condition(rules.conditions_of(character), name, **kw)
    return set_pc_conditions(chat_id, character, conds)


def remove_pc_condition(chat_id: int, character, name: str):
    return set_pc_conditions(chat_id, character, rules.remove_condition(rules.conditions_of(character), name))


def enemy_conditions(enemy) -> list[dict]:
    return rules.jload(enemy, "conditions", [])


def add_enemy_condition(enemy, name: str, **kw):
    conds = rules.add_condition(enemy_conditions(enemy), name, **kw)
    return db.update_enemy(enemy["id"], conditions=conds)


def remove_enemy_condition(enemy, name: str):
    return db.update_enemy(enemy["id"], conditions=rules.remove_condition(enemy_conditions(enemy), name))


def consume_pc_flags(chat_id: int, character, names=("скрыт", "помощь", "вдохновлён")):
    conds = rules.conditions_of(character)
    kept = [x for x in conds if x["name"] not in names]
    if len(kept) != len(conds):
        return set_pc_conditions(chat_id, character, kept)
    return character


# ---------------------------------------------------------------- режим броска: преимущество / помеха

def pc_attack_mode(character, enemy, melee: bool, gearinfo: dict) -> tuple[int, str]:
    """Преимущество и помеха при атаке персонажа (с. 60, 76, 171–172)."""
    mine = rules.cond_names(gearinfo["conds"])
    theirs = rules.cond_names(enemy_conditions(enemy))
    advs, disadvs = [], []
    for name in sorted(theirs & srd.TARGET_ADV):
        advs.append(f"цель {name}")
    if "отмечен" in theirs:
        advs.append("цель отмечена")
    if "сбит с ног" in theirs:
        (advs if melee else disadvs).append("цель сбита с ног")
    if theirs & srd.TARGET_DISADV:
        disadvs.append("цель " + sorted(theirs & srd.TARGET_DISADV)[0])
    for name in sorted(mine & srd.ATTACKER_ADV):
        advs.append(name)
    if "помощь" in mine:
        advs.append("помощь союзника")
    if "вдохновлён" in mine:
        advs.append("вдохновение")
    for name in sorted(mine & srd.ATTACKER_DISADV):
        disadvs.append(name)
    if rules.exhaustion_of(character) >= 3:
        disadvs.append("истощение")
    if gearinfo["penalties"]["nonproficient"]:
        disadvs.append("доспех без мастерства")
    return rules.combine_mode(advs, disadvs)


def enemy_attack_mode(enemy, target, melee: bool = True) -> tuple[int, str]:
    mine = rules.cond_names(enemy_conditions(enemy))
    theirs = rules.cond_names(rules.conditions_of(target))
    advs, disadvs = [], []
    for name in sorted(theirs & srd.TARGET_ADV):
        advs.append(f"{name}")
    if "сбит с ног" in theirs:
        (advs if melee else disadvs).append("цель сбита с ног")
    if theirs & srd.TARGET_DISADV:
        disadvs.append(sorted(theirs & srd.TARGET_DISADV)[0])
    if mine & srd.ATTACKER_ADV:
        advs.append("невидим")
    for name in sorted(mine & srd.ATTACKER_DISADV):
        disadvs.append(f"противник {name}")
    return rules.combine_mode(advs, disadvs)


def describe_mode(mode: int, reason: str) -> str:
    if mode > 0:
        return f" (преимущество: {reason})"
    if mode < 0:
        return f" (помеха: {reason})"
    return ""


# ---------------------------------------------------------------- спасброски

def pc_save(chat_id: int, character, ability: str, dc: int, against: str = "",
            extra_adv: list[str] | None = None, extra_disadv: list[str] | None = None) -> dict:
    """Спасбросок персонажа (с. 65). Возвращает {success, roll, total, text}."""
    conds = rules.conditions_of(character)
    names = rules.cond_names(conds)
    info = rules.race_info(character)
    penalties = gear(chat_id, character)["penalties"]
    name = esc(character["name"])
    if ability in (STR, DEX) and names & srd.AUTO_FAIL_STR_DEX:
        return {"success": False, "roll": 0, "total": 0, "auto": True,
                "text": f"🎲 <b>{name}</b>: спасбросок {ability} автоматически провален ({sorted(names & srd.AUTO_FAIL_STR_DEX)[0]})"}
    advs, disadvs = list(extra_adv or []), list(extra_disadv or [])
    if against and against in info["save_adv"]:
        advs.append("расовая черта")
    if ability == DEX and "уклоняется" in names:
        advs.append("уклонение")
    if ability == DEX and "ускорен" in names:
        advs.append("ускорение")
    if ability == WIS and "маяк надежды" in names:
        advs.append("маяк надежды")
    if ability == DEX and "опутан" in names:
        disadvs.append("опутан")
    if rules.exhaustion_of(character) >= 3:
        disadvs.append("истощение")
    if ability in (STR, DEX) and penalties["nonproficient"]:
        disadvs.append("доспех без мастерства")
    mode, reason = rules.combine_mode(advs, disadvs)
    bonus, proficient = rules.save_bonus(character, ability)
    value, total, all_dice = dice.d20_check(bonus, mode, lucky=info["lucky"])
    extra = ""
    if "благословлён" in names:
        roll = dice.roll(1, 4)[0]
        total += roll
        extra += f" +{roll} (Благословение)"
    if "сопротивление" in names:
        roll = dice.roll(1, 4)[0]
        total += roll
        extra += f" +{roll} (Сопротивление)"
        set_pc_conditions(chat_id, character, rules.remove_condition(conds, "сопротивление"))
    success = total >= dc
    rolls = f"[{'/'.join(map(str, all_dice))}] " if len(all_dice) > 1 else ""
    text = (
        f"🎲 <b>{name}</b>: спасбросок {ability} (сл. {dc}): d20 {rolls}{value} {rules.format_modifier(bonus)}"
        f"{extra} = <b>{total}</b>{describe_mode(mode, reason)} — {'✅ успех' if success else '❌ провал'}"
    )
    return {"success": success, "roll": value, "total": total, "auto": False, "text": text}


def enemy_save(enemy, ability: str, dc: int) -> dict:
    """Спасбросок противника: d20 + бонус, автоматический провал СИЛ/ЛОВ при обездвиживании."""
    names = rules.cond_names(enemy_conditions(enemy))
    name = esc(enemy["name"])
    if ability in (STR, DEX) and names & srd.AUTO_FAIL_STR_DEX:
        return {"success": False, "total": 0, "auto": True,
                "text": f"👹 {name}: спасбросок {ability} автоматически провален"}
    advs, disadvs = [], []
    if ability == DEX and "опутан" in names:
        disadvs.append("опутан")
    mode, reason = rules.combine_mode(advs, disadvs)
    value, total, _ = dice.d20_check(enemy["save_bonus"], mode)
    success = total >= dc
    return {"success": success, "total": total, "auto": False,
            "text": f"👹 {name}: спасбросок {ability}: d20 {value} {rules.format_modifier(enemy['save_bonus'])} = "
                    f"<b>{total}</b> против {dc} — {'✅ успех' if success else '❌ провал'}"}


# ---------------------------------------------------------------- проверки характеристик и навыков (гл. 7)

def check_roll(chat_id: int, character, name: str, dc: int | None = None, forced_mode: int = 0,
               secret: bool = False) -> dict:
    """Проверка навыка или характеристики: бонус, мастерство/компетентность, преимущество и помеха,
    Надёжный талант, Везучий. Возвращает {lines, event, success, total}."""
    conds = rules.conditions_of(character)
    names = rules.cond_names(conds)
    bonus, prof_level, ability = rules.check_bonus(character, name)
    penalties = gear(chat_id, character)["penalties"]
    advs, disadvs = [], []
    if names & srd.CHECK_DISADV:
        disadvs.append(sorted(names & srd.CHECK_DISADV)[0])
    if rules.exhaustion_of(character) >= 1:
        disadvs.append("истощение")
    if ability in (STR, DEX) and penalties["nonproficient"]:
        disadvs.append("доспех без мастерства")
    if name == "Скрытность" and penalties["stealth"]:
        disadvs.append("доспех")
    if "вдохновлён" in names:
        advs.append("вдохновение")
    if "помощь" in names:
        advs.append("помощь союзника")
    if forced_mode > 0:
        advs.append("решение мастера")
    elif forced_mode < 0:
        disadvs.append("решение мастера")
    mode, reason = rules.combine_mode(advs, disadvs)
    floor = rules.reliable_talent_floor(character, prof_level)
    value, total, all_dice = dice.d20_check(bonus, mode, lucky=rules.race_info(character)["lucky"], floor=floor)
    extra = ""
    if "указание" in names:
        guide = dice.roll(1, 4)[0]
        total += guide
        extra = f" +{guide} (Указание)"
    consumed = [x for x in ("вдохновлён", "помощь", "указание") if x in names]
    if consumed:
        set_pc_conditions(chat_id, character, [x for x in conds if x["name"] not in consumed])
    mark = " (компетентность)" if prof_level == 2 else " (мастерство)" if prof_level == 1 else ""
    rolls = f"[{'/'.join(map(str, all_dice))}] " if len(all_dice) > 1 else ""
    label = f"{name}" + (f" ({ability})" if name in srd.SKILLS else "")
    lines = [
        f"🎲 <b>{esc(character['name'])}</b> — проверка: {esc(label)}",
        f"d20 {rolls}{value} {rules.format_modifier(bonus)}{mark}{extra} = <b>{total}</b>"
        f"{describe_mode(mode, reason)}" + (" — Надёжный талант" if floor and value == floor and all_dice[0] < floor else ""),
    ]
    if value == 20:
        lines.append("💥 Натуральная 20!")
    elif value == 1:
        lines.append("💀 Натуральная 1!")
    success = None
    event = f"проверка {name}: {total}"
    if dc is not None:
        success = total >= dc  # у проверок нет автоуспеха на 20 (с. 61), только у атак
        lines.append(("✅ Успех" if success else "❌ Провал") + f" (сложность {dc})")
        event = f"проверка {name} (сложность {dc}): {total} — {'успех' if success else 'провал'}"
    return {"lines": lines, "event": event, "success": success, "total": total, "secret": secret}


# ---------------------------------------------------------------- концентрация

def end_concentration(chat_id: int, character, reason: str = "") -> list[str]:
    """Прерывает концентрацию: убирает эффекты заклинания со всех, на кого оно наложено."""
    spell = character["concentration"]
    if not spell:
        return []
    uid = character["user_id"]
    for c in db.list_characters(chat_id):
        conds = rules.conditions_of(c)
        kept = rules.remove_by_spell(conds, spell, uid)
        if len(kept) != len(conds):
            db.update_character(chat_id, c["user_id"], conditions=kept)
    for e in db.list_enemies(chat_id):
        conds = enemy_conditions(e)
        kept = rules.remove_by_spell(conds, spell, uid)
        if len(kept) != len(conds):
            db.update_enemy(e["id"], conditions=kept)
    db.update_character(chat_id, uid, concentration="")
    return [f"🌀 <b>{esc(character['name'])}</b> теряет концентрацию на «{esc(spell)}»{(' — ' + reason) if reason else ''}"]


# ---------------------------------------------------------------- урон и лечение персонажей

def pc_damage(chat_id: int, character, amount: int, dtype: str = "", crit: bool = False,
              source: str = "") -> tuple[list[str], object]:
    """Урон персонажу с учётом сопротивления, временных хитов, падения без сознания,
    спасбросков от смерти при 0 хитов, мгновенной смерти и концентрации (с. 77–79, 83)."""
    lines: list[str] = []
    name = esc(character["name"])
    info = rules.race_info(character)
    if dtype and dtype in info["resist"]:
        amount = amount // 2
        lines.append(f"🛡 {name} сопротивляется урону ({esc(dtype)}): {amount}")
    out = rules.damage_outcome(character["hp"], character["max_hp"], character["temp_hp"], amount, crit)
    fields: dict = {"temp_hp": out["temp_hp"], "hp": out["hp"]}
    if out["absorbed"]:
        lines.append(f"✨ Временные хиты поглотили {out['absorbed']}")
    was_zero = character["hp"] <= 0
    if out["instant_death"]:
        fields.update(hp=0, alive=0, died_scene=db.current_situation_number(chat_id))
        db.update_character(chat_id, character["user_id"], **fields)
        character = refresh(chat_id, character)
        lines.append(f"⚰️ <b>{name}</b> погибает мгновенно (урон ≥ максимума хитов)!")
        lines += end_concentration(chat_id, character, "смерть")
        log(chat_id, character["name"], "ПОГИБАЕТ мгновенно")
        return lines, refresh(chat_id, character)
    if out["dropped"]:
        conds = rules.add_condition(rules.conditions_of(character), "без сознания")
        conds = rules.add_condition(conds, "сбит с ног")
        fields.update(conditions=conds, death_successes=0, death_failures=0)
        db.update_character(chat_id, character["user_id"], **fields)
        character = refresh(chat_id, character)
        lines.append(f"💀 <b>{name}</b> падает без сознания (0 хитов)")
        lines += end_concentration(chat_id, character, "потеря сознания")
        log(chat_id, character["name"], "падает без сознания" + (f" ({source})" if source else ""))
        return lines, refresh(chat_id, character)
    if was_zero and out["death_failures"]:
        failures = character["death_failures"] + out["death_failures"]
        fields["death_failures"] = failures
        if out["instant_death"] or failures >= 3:
            fields.update(alive=0, died_scene=db.current_situation_number(chat_id))
            db.update_character(chat_id, character["user_id"], **fields)
            character = refresh(chat_id, character)
            lines.append(f"⚰️ <b>{name}</b> получает урон без сознания — провал спасброска от смерти. <b>Погибает.</b>")
            log(chat_id, character["name"], "ПОГИБАЕТ")
            return lines, refresh(chat_id, character)
        fields["death_successes"] = 0 if character["death_successes"] >= 3 else character["death_successes"]
        db.update_character(chat_id, character["user_id"], **fields)
        character = refresh(chat_id, character)
        lines.append(f"💢 {name} без сознания получает урон: провалов спасброска от смерти {failures}/3"
                     + (" (критический удар — два провала)" if crit else ""))
        return lines, character
    db.update_character(chat_id, character["user_id"], **fields)
    character = refresh(chat_id, character)
    # Концентрация: спасбросок ТЕЛ, сл. 10 или половина урона (с. 84)
    if out["dealt"] > 0 and character["concentration"] and character["hp"] > 0:
        dc = rules.concentration_dc(out["dealt"])
        result = pc_save(chat_id, character, CON, dc)
        lines.append(result["text"] + " — концентрация")
        if not result["success"]:
            lines += end_concentration(chat_id, character, "урон")
            character = refresh(chat_id, character)
    return lines, character


def pc_heal(chat_id: int, character, amount: int) -> tuple[int, object]:
    """Лечение (с. 79): не выше максимума; с 0 хитов возвращает в сознание и сбрасывает спасброски."""
    if not character["alive"] or amount <= 0:
        return 0, character
    new_hp = min(character["max_hp"], character["hp"] + amount)
    gained = new_hp - character["hp"]
    fields: dict = {"hp": new_hp}
    if character["hp"] == 0 and new_hp > 0:
        conds = rules.remove_condition(rules.conditions_of(character), "без сознания")
        fields.update(conditions=conds, death_successes=0, death_failures=0)
    return gained, db.update_character(chat_id, character["user_id"], **fields)


def enemy_damage(chat_id: int, enemy, amount: int) -> tuple[list[str], object, bool]:
    """Урон противнику. Сон прерывается уроном. Возвращает (строки, противник, повержен)."""
    new_hp = max(0, enemy["hp"] - amount)
    conds = enemy_conditions(enemy)
    fields = {"hp": new_hp, "alive": int(new_hp > 0)}
    if find_sleep(conds):
        fields["conditions"] = rules.remove_condition(conds, "без сознания")
    updated = db.update_enemy(enemy["id"], **fields)
    lines = []
    if new_hp == 0:
        lines.append(f"☠️ <b>{esc(enemy['name'])}</b> повержен!")
    return lines, updated, new_hp == 0


def find_sleep(conds: list[dict]) -> bool:
    entry = rules.find_condition(conds, "без сознания")
    return bool(entry and entry.get("spell") == "Усыпление")


# ---------------------------------------------------------------- опыт и уровни (с. 12)

def grant_xp(chat_id: int, character, amount: int) -> tuple[list[str], object]:
    """Начисляет опыт одному персонажу, обрабатывает повышение уровня."""
    result = rules.apply_xp(character, amount)
    fields = {"xp": result["xp"], "level": result["level"], "max_hp": result["max_hp"], "hp": result["hp"]}
    if result["asi"]:
        fields["asi_pending"] = character["asi_pending"] + result["asi"]
    if result["learn"]:
        fields["learn_pending"] = character["learn_pending"] + result["learn"]
    if result["cantrips"]:
        fields["cantrip_pending"] = character["cantrip_pending"] + result["cantrips"]
    if result["expertise"]:
        fields["expertise_pending"] = character["expertise_pending"] + result["expertise"]
    updated = db.update_character(chat_id, character["user_id"], **fields)
    lines: list[str] = []
    if result["gained"]:
        lines.append(
            f"🎉 <b>{esc(character['name'])}</b> достигает {result['level']} уровня! "
            f"Хиты: +{result['hp_gain']} (максимум {result['max_hp']}). "
            f"Бонус мастерства +{rules.proficiency(result['level'])}"
        )
        lines += [f"   ✨ {esc(f)}" for f in result["features"]]
        todo = []
        if result["asi"]:
            todo.append("/asi — повысить характеристики")
        if result["learn"]:
            todo.append("/learn — записать заклинания в книгу")
        if result["cantrips"]:
            todo.append("/cantrip — выбрать новый заговор")
        if result["expertise"]:
            todo.append("/expertise — выбрать компетентность")
        if todo:
            lines.append("   ➡️ " + "; ".join(todo))
        log(chat_id, character["name"], f"достигает {result['level']} уровня")
    return lines, updated


def split_xp(chat_id: int, total: int, label: str = "") -> list[str]:
    """Делит опыт поровну между живыми персонажами отряда (принцип DMG; пороги сложности
    боя в правилах рассчитаны на общую сумму опыта)."""
    party = db.list_characters(chat_id, alive_only=True)
    if not party or total <= 0:
        return []
    share = total // len(party)
    if share <= 0:
        share = 1 if total > 0 else 0
    lines = [f"✨ Опыт{(' за ' + label) if label else ''}: {total} на отряд из {len(party)} — по {share}"]
    for c in party:
        more, _ = grant_xp(chat_id, c, share)
        lines += more
    return lines


# ---------------------------------------------------------------- сложность встречи (гл. 13)

def encounter_difficulty(chat_id: int, extra_enemies=()) -> dict | None:
    """Оценка встречи по правилам (с. 165–166). None — если нет ни отряда, ни противников."""
    party = [c for c in db.list_characters(chat_id, alive_only=True)]
    enemies = list(db.list_enemies(chat_id)) + list(extra_enemies)
    if not party or not enemies:
        return None
    thresholds = [0, 0, 0, 0]
    for c in party:
        row = srd.XP_THRESHOLDS[max(1, min(c["level"], srd.MAX_LEVEL))]
        thresholds = [t + r for t, r in zip(thresholds, row)]
    raw = sum(e["xp"] for e in enemies)
    multiplier = srd.encounter_multiplier(len(enemies), len(party))
    adjusted = raw * multiplier
    label = "тривиальный"
    for name, threshold in zip(srd.ENCOUNTER_NAMES, thresholds):
        if adjusted >= threshold:
            label = name
    return {"label": label, "raw": raw, "multiplier": multiplier, "adjusted": adjusted, "thresholds": thresholds}


def format_difficulty(info: dict | None) -> str:
    if info is None:
        return ""
    return (f"⚖️ Сложность встречи: <b>{info['label']}</b> "
            f"(опыт {info['raw']} × {info['multiplier']:g} = {info['adjusted']:g}; "
            f"пороги: лёгкая {info['thresholds'][0]}, средняя {info['thresholds'][1]}, "
            f"сложная {info['thresholds'][2]}, смертельная {info['thresholds'][3]})")
