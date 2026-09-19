"""Игровые правила D&D Basic Rules: характеристики, навыки, КД, атака, здоровье, уровни, магия.

Здесь нет ни Telegram, ни базы — только чистые вычисления над «персонажем» (строка из базы
или словарь) и списками состояний. Ссылки на страницы — печатная нумерация PDF.
"""

import copy
import json
import random
from collections.abc import Mapping

import dice
import srd
from spelldata import SPELLS
from srd import (
    ABILITIES, CLASSES, CON, DEX, INT, STR, WIS,
    RACES, SKILLS, SPELL_SLOTS,
)

# ---------------------------------------------------------------- доступ к полям


def _get(c: Mapping, key: str, default=None):
    try:
        value = c[key]
    except (KeyError, IndexError):
        return default
    return default if value is None else value


def jload(c: Mapping, key: str, default):
    """JSON-поле персонажа (список/словарь). Пусто или битое — копия значения по умолчанию."""
    raw = _get(c, key, None)
    if raw in (None, ""):
        return copy.deepcopy(default)
    if isinstance(raw, (list, dict)):
        return copy.deepcopy(raw)
    try:
        value = json.loads(raw)
    except (TypeError, ValueError):
        return copy.deepcopy(default)
    return value if isinstance(value, type(default)) else copy.deepcopy(default)


# ---------------------------------------------------------------- базовые формулы (с. 60)

def modifier(score: int) -> int:
    """(значение − 10) / 2 с округлением вниз."""
    return (score - 10) // 2


def format_modifier(value: int) -> str:
    return f"+{value}" if value >= 0 else str(value)


def proficiency(level: int) -> int:
    """Бонус мастерства (с. 12): +2 на 1–4, +3 на 5–8, +4 на 9–12, +5 на 13–16, +6 на 17–20."""
    return 2 + (max(1, level) - 1) // 4


def xp_for_level(level: int) -> int:
    return srd.XP_FOR_LEVEL[max(1, min(level, srd.MAX_LEVEL)) - 1]


def level_for_xp(xp: int) -> int:
    level = 1
    for lvl in range(1, srd.MAX_LEVEL + 1):
        if xp >= srd.XP_FOR_LEVEL[lvl - 1]:
            level = lvl
    return level


def xp_to_next(c: Mapping) -> int | None:
    level = c["level"]
    return None if level >= srd.MAX_LEVEL else xp_for_level(level + 1)


# ---------------------------------------------------------------- класс, раса, характеристики

def class_of(c: Mapping) -> str:
    name = _get(c, "char_class", "")
    return name if name in CLASSES else "Воин"  # персонажи первой версии считаются воинами


def race_of(c: Mapping) -> str:
    name = _get(c, "race", "")
    return name if name in RACES else "Человек"


def subrace_of(c: Mapping) -> str:
    return _get(c, "subrace", "") or ""


def race_info(c: Mapping) -> dict:
    """Расовые черты: раса плюс подраса, объединённые."""
    base = RACES[race_of(c)]
    sub = base.get("subraces", {}).get(subrace_of(c), {})
    info = {
        "speed": sub.get("speed", base["speed"]),
        "weapons": set(base.get("weapons", ())) | set(sub.get("weapons", ())),
        "armor": set(base.get("armor", ())) | set(sub.get("armor", ())),
        "resist": set(base.get("resist", ())) | set(sub.get("resist", ())),
        "save_adv": set(base.get("save_adv", ())) | set(sub.get("save_adv", ())),
        "skills": list(base.get("skills", ())) + list(sub.get("skills", ())),
        "traits": list(base.get("traits", ())) + list(sub.get("traits", ())),
        "lucky": bool(base.get("lucky")),
        "hp_per_level": sub.get("hp_per_level", 0),
        "bonus_cantrip": bool(sub.get("bonus_cantrip")),
    }
    return info


def racial_bonuses(race: str, subrace: str) -> dict[str, int]:
    base = RACES[race]
    bonuses = dict(base["bonuses"])
    for ability, value in base.get("subraces", {}).get(subrace, {}).get("bonuses", {}).items():
        bonuses[ability] = bonuses.get(ability, 0) + value
    return bonuses


def chosen_attributes(c: Mapping) -> list[str]:
    return [a.strip() for a in str(_get(c, "attributes", "")).split(",") if a.strip()]


def default_stats(chosen: list[str]) -> dict[str, int]:
    """Характеристики персонажа первой версии, у которого числовых значений не было."""
    return {a: (16 if a in chosen else 10) for a in ABILITIES}


def stats_of(c: Mapping) -> dict[str, int]:
    raw = _get(c, "stats", None)
    if raw:
        try:
            loaded = json.loads(raw) if isinstance(raw, str) else dict(raw)
        except (TypeError, ValueError):
            loaded = {}
        return {a: int(loaded.get(a, 10)) for a in ABILITIES}
    return default_stats(chosen_attributes(c))


def mod_of(c: Mapping, ability: str) -> int:
    return modifier(stats_of(c)[ability])


def assign_stats(class_name: str, values: list[int]) -> dict[str, int]:
    """Раскладывает шесть значений по характеристикам: лучшие — приоритетным для класса
    (быстрая сборка, гл. 3)."""
    ordered = sorted(values, reverse=True)
    return dict(zip(CLASSES[class_name]["priority"], ordered))


def roll_stats() -> list[int]:
    return [dice.four_d6_drop_lowest() for _ in range(6)]


def apply_racial_bonuses(stats: Mapping[str, int], race: str, subrace: str) -> dict[str, int]:
    result = dict(stats)
    for ability, value in racial_bonuses(race, subrace).items():
        result[ability] = result[ability] + value
    return result


# ---------------------------------------------------------------- навыки, спасброски, проверки (гл. 7)

def skills_of(c: Mapping) -> set[str]:
    return set(jload(c, "skills", []))


def expertise_of(c: Mapping) -> set[str]:
    return set(jload(c, "expertise", []))


def save_proficiencies(c: Mapping) -> set[str]:
    saves = set(CLASSES[class_of(c)]["saves"])
    if class_of(c) == "Плут" and c["level"] >= 15:
        saves.add(WIS)  # Скользкий ум
    return saves


def save_bonus(c: Mapping, ability: str) -> tuple[int, bool]:
    proficient = ability in save_proficiencies(c)
    return mod_of(c, ability) + (proficiency(c["level"]) if proficient else 0), proficient


def half_prof_bonus(c: Mapping, ability: str) -> int:
    """Выдающийся атлет чемпиона (с. 27): половина мастерства (вверх) к СИЛ/ЛОВ/ТЕЛ без мастерства."""
    if class_of(c) == "Воин" and c["level"] >= 7 and ability in (STR, DEX, CON):
        return (proficiency(c["level"]) + 1) // 2
    return 0


def check_bonus(c: Mapping, name: str) -> tuple[int, int, str]:
    """Бонус проверки по навыку или характеристике.
    Возвращает (бонус, уровень мастерства 0/1/2, характеристика)."""
    prof = proficiency(c["level"])
    if name in SKILLS:
        ability = SKILLS[name]
        level = 2 if name in expertise_of(c) else 1 if name in skills_of(c) else 0
        bonus = mod_of(c, ability) + prof * level
        if level == 0:
            bonus += half_prof_bonus(c, ability)
        return bonus, level, ability
    return mod_of(c, name) + half_prof_bonus(c, name), 0, name


def reliable_talent_floor(c: Mapping, prof_level: int) -> int | None:
    """Надёжный талант (с. 30): в навыках с мастерством 9 и меньше считается как 10."""
    if class_of(c) == "Плут" and c["level"] >= 11 and prof_level >= 1:
        return 10
    return None


def passive_perception(c: Mapping) -> int:
    return 10 + check_bonus(c, "Восприятие")[0]


def initiative_bonus(c: Mapping) -> int:
    return check_bonus(c, DEX)[0]


# ---------------------------------------------------------------- состояния

def conditions_of(c: Mapping) -> list[dict]:
    return jload(c, "conditions", [])


def cond_names(conds: list[dict]) -> set[str]:
    return {x["name"] for x in conds}


def find_condition(conds: list[dict], name: str) -> dict | None:
    return next((x for x in conds if x["name"] == name), None)


def add_condition(conds: list[dict], name: str, rounds: int | None = None, save: dict | None = None,
                  src: int | None = None, data: dict | None = None, spell: str = "") -> list[dict]:
    """Добавляет состояние. Одно и то же состояние не суммируется — остаётся более долгое."""
    conds = [x for x in conds if x["name"] != name] if find_condition(conds, name) is None else list(conds)
    existing = find_condition(conds, name)
    entry = {"name": name, "rounds": rounds, "save": save, "src": src, "data": data or {}, "spell": spell}
    if existing is None:
        conds.append(entry)
        return conds
    if rounds is None or (existing["rounds"] is not None and rounds > existing["rounds"]):
        conds = [x for x in conds if x["name"] != name]
        conds.append(entry)
    return conds


def remove_condition(conds: list[dict], name: str) -> list[dict]:
    return [x for x in conds if x["name"] != name]


def remove_by_spell(conds: list[dict], spell: str, src: int | None = None) -> list[dict]:
    return [x for x in conds if not (x.get("spell") == spell and (src is None or x.get("src") == src))]


def tick_conditions(conds: list[dict]) -> tuple[list[dict], list[str]]:
    """Уменьшает длительность на раунд. Возвращает (оставшиеся, истёкшие названия)."""
    kept, expired = [], []
    for x in conds:
        if x["rounds"] is None:
            kept.append(x)
            continue
        left = x["rounds"] - 1
        if left <= 0:
            expired.append(x["name"])
        else:
            kept.append({**x, "rounds": left})
    return kept, expired


def combine_mode(advs: list[str], disadvs: list[str]) -> tuple[int, str]:
    """Преимущество и помеха гасят друг друга (с. 60). Возвращает (режим, пояснение)."""
    if advs and disadvs:
        return 0, ""
    if advs:
        return 1, ", ".join(dict.fromkeys(advs))
    if disadvs:
        return -1, ", ".join(dict.fromkeys(disadvs))
    return 0, ""


def exhaustion_of(c: Mapping) -> int:
    return int(_get(c, "exhaustion", 0))


# ---------------------------------------------------------------- предметы: оружие и доспехи

def _item_value(item: Mapping) -> dict | str:
    raw = _get(item, "value", "")
    if isinstance(raw, str) and raw.startswith("{"):
        try:
            return json.loads(raw)
        except ValueError:
            return {}
    return raw


def srd_item(name: str) -> tuple[str, dict] | None:
    """Предмет из таблиц правил по названию: (тип, значение) или None."""
    weapon = srd.WEAPONS.get(dice.match_name(name, srd.WEAPONS) or "")
    if weapon is not None and dice.match_name(name, srd.WEAPONS) is not None:
        return "weapon", {
            "dice": weapon["dice"], "dtype": weapon["dtype"], "cat": weapon["cat"],
            "ranged": weapon["ranged"], "props": sorted(weapon["props"]), "bonus": 0,
            "srd": weapon["name"],
        }
    armor_name = dice.match_name(name, srd.ARMORS)
    if armor_name is not None:
        cat, base, strength, stealth = srd.ARMORS[armor_name]
        return "armor", {"base": base, "cat": cat, "str": strength, "stealth": stealth, "bonus": 0, "srd": armor_name}
    if dice.match_name(name, [srd.SHIELD_NAME]) is not None:
        return "shield", {"bonus": srd.SHIELD_AC, "srd": srd.SHIELD_NAME}
    return None


def weapon_info(item: Mapping | None) -> dict:
    """Характеристики оружия в предмете; без предмета — безоружный удар."""
    if item is None:
        return {"name": "безоружный удар", "dice": str(srd.UNARMED_DAMAGE), "dtype": "дробящий", "cat": "unarmed",
                "ranged": False, "props": set(), "bonus": 0, "versatile": None, "unarmed": True}
    value = _item_value(item)
    name = item["name"]
    if isinstance(value, dict) and value.get("dice"):
        data = value
    else:
        found = srd_item(name)
        if isinstance(value, str) and dice.parse_notation(value):
            data = {"dice": value, "dtype": "", "cat": "martial", "ranged": False, "props": [], "bonus": 0}
        elif found and found[0] == "weapon":
            data = found[1]
        else:
            data = {"dice": "1d4", "dtype": "", "cat": "simple", "ranged": False, "props": [], "bonus": 0}
    props = set(data.get("props", []))
    versatile = next((p.split(":", 1)[1] for p in props if p.startswith("versatile:")), None)
    return {
        "name": name, "dice": data["dice"], "dtype": data.get("dtype", ""), "cat": data.get("cat", "simple"),
        "ranged": bool(data.get("ranged")), "props": props, "bonus": int(data.get("bonus", 0)),
        "versatile": versatile, "unarmed": False, "srd": data.get("srd", name),
    }


def armor_info(item: Mapping | None) -> dict | None:
    if item is None:
        return None
    value = _item_value(item)
    if isinstance(value, dict) and "base" in value:
        return {"name": item["name"], **{k: value.get(k, d) for k, d in
                                          (("base", 11), ("cat", "light"), ("str", 0), ("stealth", False), ("bonus", 0))}}
    found = srd_item(item["name"])
    if found and found[0] == "armor":
        return {"name": item["name"], **{k: found[1][k] for k in ("base", "cat", "str", "stealth", "bonus")}}
    digits = "".join(ch for ch in str(value) if ch.isdigit())
    return {"name": item["name"], "base": 10 + int(digits or 1), "cat": "light", "str": 0, "stealth": False, "bonus": 0}


def shield_bonus(item: Mapping | None) -> int:
    if item is None:
        return 0
    value = _item_value(item)
    if isinstance(value, dict) and "bonus" in value:
        return int(value["bonus"])
    return srd.SHIELD_AC


def armor_categories(c: Mapping) -> set[str]:
    return set(CLASSES[class_of(c)]["armor"]) | race_info(c)["armor"]


def armor_proficient(c: Mapping, armor: dict | None, shield: Mapping | None) -> bool:
    cats = armor_categories(c)
    if armor is not None and armor["cat"] not in cats:
        return False
    if shield is not None and "shield" not in cats:
        return False
    return True


def weapon_proficient(c: Mapping, winfo: dict) -> bool:
    if winfo.get("unarmed"):
        return True
    allowed = CLASSES[class_of(c)]["weapons"] | race_info(c)["weapons"]
    return winfo["cat"] in allowed or winfo.get("srd", winfo["name"]) in allowed or winfo["name"] in allowed


def armor_class(c: Mapping, armor: dict | None = None, shield: Mapping | None = None,
                conds: list[dict] | None = None) -> tuple[int, list[str]]:
    """Класс доспеха (с. 46, 11): доспех + ЛОВ по категории, щит, боевой стиль, заклинания."""
    conds = conds if conds is not None else conditions_of(c)
    names = cond_names(conds)
    dex = mod_of(c, DEX)
    parts: list[str] = []
    if armor is not None:
        cat = armor["cat"]
        if cat == "light":
            ac, parts = armor["base"] + dex, [f"{armor['name']} {armor['base']}", f"ЛОВ {format_modifier(dex)}"]
        elif cat == "medium":
            capped = min(dex, srd.MEDIUM_ARMOR_MAX_DEX)
            ac, parts = armor["base"] + capped, [f"{armor['name']} {armor['base']}", f"ЛОВ {format_modifier(capped)} (макс. +2)"]
        else:
            ac, parts = armor["base"], [f"{armor['name']} {armor['base']}"]
        if armor.get("bonus"):
            ac += armor["bonus"]
            parts.append(f"магия +{armor['bonus']}")
    elif "доспехи мага" in names:
        ac, parts = 13 + dex, [f"Доспехи мага 13", f"ЛОВ {format_modifier(dex)}"]
    else:
        ac, parts = 10 + dex, ["без доспеха 10", f"ЛОВ {format_modifier(dex)}"]
    if shield is not None:
        ac += shield_bonus(shield)
        parts.append(f"щит +{shield_bonus(shield)}")
    if armor is not None and _get(c, "fighting_style", "") == "Оборона":
        ac += 1
        parts.append("Оборона +1")
    if "щит веры" in names:
        ac += 2
        parts.append("Щит веры +2")
    if "щит" in names:
        ac += 5
        parts.append("заклинание Щит +5")
    if "ускорен" in names:
        ac += 2
        parts.append("Ускорение +2")
    return ac, parts


def armor_penalties(c: Mapping, armor: dict | None, shield: Mapping | None) -> dict:
    """Помехи от доспеха (с. 46): без мастерства — помеха на СИЛ/ЛОВ и нельзя колдовать;
    не хватает Силы — скорость −10; помеха на скрытность."""
    strength = stats_of(c)[STR]
    return {
        "nonproficient": not armor_proficient(c, armor, shield),
        "str_penalty": armor is not None and armor["str"] > 0 and strength < armor["str"],
        "stealth": bool(armor and armor["stealth"]),
    }


def speed_of(c: Mapping, penalties: dict | None = None) -> int:
    speed = race_info(c)["speed"]
    if penalties and penalties.get("str_penalty"):
        speed -= 10
    level = exhaustion_of(c)
    if level >= 5:
        return 0
    if level >= 2:
        speed //= 2
    return max(0, speed)


def crit_range(c: Mapping) -> int:
    """С какого значения d20 удар критический: 20, 19 (чемпион 3) или 18 (чемпион 15)."""
    if class_of(c) == "Воин":
        if c["level"] >= 15:
            return 18
        if c["level"] >= 3:
            return 19
    return 20


def attacks_per_action(c: Mapping) -> int:
    return srd.extra_attacks(c["level"]) if class_of(c) == "Воин" else 1


def sneak_dice(c: Mapping) -> int:
    return srd.sneak_attack_dice(c["level"]) if class_of(c) == "Плут" else 0


def attack_profile(c: Mapping, weapon: Mapping | None, shield: Mapping | None = None,
                   conds: list[dict] | None = None) -> dict:
    """Всё нужное для атаки оружием: бонус к попаданию, кубики и бонус урона (с. 76, 27, 48)."""
    conds = conds if conds is not None else conditions_of(c)
    winfo = weapon_info(weapon)
    stats = stats_of(c)
    props = winfo["props"]
    if winfo["ranged"]:
        ability = DEX
    elif "finesse" in props:
        ability = DEX if stats[DEX] >= stats[STR] else STR
    else:
        ability = STR
    mod = modifier(stats[ability])
    two_handed = "two_handed" in props or (winfo["versatile"] is not None and shield is None)
    damage_dice = winfo["versatile"] if (winfo["versatile"] and shield is None) else winfo["dice"]
    style = _get(c, "fighting_style", "")
    prof_ok = weapon_proficient(c, winfo)
    magic = winfo["bonus"]
    if "волшебное оружие" in cond_names(conds):
        magic = max(magic, 1 + (c["level"] >= 4) + (c["level"] >= 6))
    attack = mod + (proficiency(c["level"]) if prof_ok else 0) + magic
    damage_bonus = mod + magic
    notes: list[str] = []
    if style == "Стрельба" and winfo["ranged"]:
        attack += 2
        notes.append("Стрельба +2")
    if style == "Дуэль" and not winfo["ranged"] and not winfo.get("unarmed") and not two_handed:
        damage_bonus += 2
        notes.append("Дуэль +2 урона")
    return {
        "weapon": winfo, "ability": ability, "attack": attack, "damage_dice": damage_dice,
        "damage_bonus": damage_bonus, "dtype": winfo["dtype"] or "", "ranged": winfo["ranged"],
        "proficient": prof_ok, "two_handed": two_handed, "notes": notes,
        "great_weapon": style == "Бой большим оружием" and not winfo["ranged"] and two_handed,
        "sneak_ok": class_of(c) == "Плут" and (winfo["ranged"] or "finesse" in props),
        "crit_range": crit_range(c),
    }


def roll_weapon_damage(profile: dict, crit: bool = False, extra_dice: list[str] | None = None) -> tuple[int, str]:
    """Урон оружием: кубики (при крите удвоенные) + бонус; Бой большим оружием переигрывает 1 и 2.
    Возвращает (урон, расшифровка)."""
    parsed = dice.parse_notation(profile["damage_dice"])
    if parsed is None:
        count, sides, base_mod = 1, 1, int(profile["damage_dice"]) if str(profile["damage_dice"]).isdigit() else 1
        rolls = [base_mod]
        dice_total = base_mod
        flat = 0
    else:
        count, sides, base_mod = parsed
        count *= 2 if crit else 1
        rolls = dice.roll(count, sides)
        if profile.get("great_weapon"):
            rolls = [dice.roll(1, sides)[0] if r <= 2 else r for r in rolls]
        dice_total = sum(rolls)
        flat = base_mod
    total = dice_total + flat + profile["damage_bonus"]
    detail = " + ".join(map(str, rolls))
    if flat:
        detail += f" {format_modifier(flat)}"
    if profile["damage_bonus"]:
        detail += f" {format_modifier(profile['damage_bonus'])}"
    for notation in extra_dice or []:
        rolled = dice.roll_notation(notation, double_dice=crit)
        if rolled:
            total += rolled[0]
            detail += f" + {rolled[0]} ({notation}{' ×2' if crit else ''})"
    return max(1, total), detail


# ---------------------------------------------------------------- здоровье и уровни (гл. 1, с. 8, 12)

def hit_die_of(c: Mapping) -> int:
    return CLASSES[class_of(c)]["hit_die"]


def initial_max_hp(class_name: str, con_mod: int, hp_per_level: int = 0) -> int:
    """На 1 уровне — максимум кубика хитов + мод. ТЕЛ (с. 8)."""
    return max(1, CLASSES[class_name]["hit_die"] + con_mod + hp_per_level)


def hp_per_level_gain(class_name: str, con_mod: int, hp_per_level: int = 0) -> int:
    """Прирост за уровень: среднее значение кубика хитов + мод. ТЕЛ, минимум 1 (с. 12)."""
    return max(1, srd.avg_hit_die(CLASSES[class_name]["hit_die"]) + con_mod + hp_per_level)


def hit_dice_total(c: Mapping) -> int:
    return c["level"]


def hit_dice_left(c: Mapping) -> int:
    return max(0, c["level"] - int(_get(c, "hit_dice_used", 0)))


def con_change_hp(level: int, old_score: int, new_score: int) -> int:
    """Изменение мод. ТЕЛ пересчитывает максимум хитов задним числом (с. 64)."""
    return (modifier(new_score) - modifier(old_score)) * level


def level_up_gains(c: Mapping, new_level: int) -> dict:
    """Что даёт повышение до new_level: хиты, выбор характеристик, заклинания, компетентность."""
    class_name = class_of(c)
    info = race_info(c)
    gains = {
        "hp": hp_per_level_gain(class_name, mod_of(c, CON), info["hp_per_level"]),
        "asi": 1 if new_level in srd.ASI_LEVELS[class_name] else 0,
        "learn": 2 if class_name == "Волшебник" else 0,
        "cantrips": 0,
        "expertise": 2 if class_name == "Плут" and new_level == 6 else 0,
        "features": list(CLASSES[class_name]["features"].get(new_level, [])),
    }
    if CLASSES[class_name]["caster"] and srd.cantrips_known(new_level) > srd.cantrips_known(new_level - 1):
        gains["cantrips"] = 1
    return gains


def apply_xp(c: Mapping, amount: int) -> dict:
    """Начисляет опыт и повышает уровни по таблице (с. 12). Здоровье при повышении растёт
    на прирост (текущее — на столько же), полностью не восстанавливается."""
    xp = int(c["xp"]) + amount
    old_level = c["level"]
    level = max(old_level, level_for_xp(xp))
    result = {"xp": xp, "level": level, "gained": level - old_level, "hp_gain": 0, "asi": 0, "learn": 0,
              "cantrips": 0, "expertise": 0, "features": [], "levels": []}
    for new_level in range(old_level + 1, level + 1):
        gains = level_up_gains(c, new_level)
        for key in ("hp_gain", "asi", "learn", "cantrips", "expertise"):
            result[key] += gains["hp" if key == "hp_gain" else key]
        result["features"] += [f"{new_level} ур.: {f}" for f in gains["features"]]
        result["levels"].append(new_level)
    result["max_hp"] = c["max_hp"] + result["hp_gain"]
    result["hp"] = min(result["max_hp"], c["hp"] + result["hp_gain"]) if c["hp"] > 0 else c["hp"]
    return result


# ---------------------------------------------------------------- урон, лечение и смерть (с. 77–79)

def damage_outcome(hp: int, max_hp: int, temp_hp: int, amount: int, crit: bool = False) -> dict:
    """Урон персонажу. Временные хиты поглощают первыми. Урон при 0 хитов — провал спасброска
    от смерти (крит — два); остаток урона ≥ максимума хитов — мгновенная смерть (с. 78–79)."""
    absorbed = min(temp_hp, amount)
    temp_hp -= absorbed
    remaining = amount - absorbed
    result = {"temp_hp": temp_hp, "hp": hp, "absorbed": absorbed, "dropped": False,
              "instant_death": False, "death_failures": 0, "dealt": remaining}
    if remaining <= 0:
        return result
    if hp <= 0:
        result["death_failures"] = 2 if crit else 1
        result["instant_death"] = remaining >= max_hp
        return result
    if remaining >= hp:
        overflow = remaining - hp
        result["hp"] = 0
        result["dropped"] = True
        result["instant_death"] = overflow >= max_hp
    else:
        result["hp"] = hp - remaining
    return result


def death_save(successes: int, failures: int, advantage: bool = False, lucky: bool = False) -> dict:
    """Спасбросок от смерти (с. 79): 10+ успех, иначе провал; 1 — два провала; 20 — 1 хит.
    Три успеха — стабилен, три провала — смерть."""
    value, all_dice = dice.roll_d20(1 if advantage else 0, lucky)
    result = {"roll": value, "dice": all_dice, "revived": False, "stable": False, "dead": False}
    if value == 20:
        result.update(revived=True, successes=0, failures=0)
        return result
    if value == 1:
        failures += 2
    elif value >= 10:
        successes += 1
    else:
        failures += 1
    result.update(successes=successes, failures=failures)
    if failures >= 3:
        result["dead"] = True
    elif successes >= 3:
        result["stable"] = True
    return result


def concentration_dc(damage: int) -> int:
    return max(10, damage // 2)


# ---------------------------------------------------------------- магия (гл. 10)

def caster_ability(c: Mapping) -> str | None:
    return CLASSES[class_of(c)]["caster"]


def is_caster(c: Mapping) -> bool:
    return caster_ability(c) is not None


def spell_dc(c: Mapping) -> int:
    ability = caster_ability(c)
    return 8 + proficiency(c["level"]) + (mod_of(c, ability) if ability else 0)


def spell_attack_bonus(c: Mapping) -> int:
    ability = caster_ability(c)
    return proficiency(c["level"]) + (mod_of(c, ability) if ability else 0)


def slots_total(c: Mapping) -> list[int]:
    if not is_caster(c):
        return []
    return list(SPELL_SLOTS[min(c["level"], srd.MAX_LEVEL)])


def slots_used(c: Mapping) -> dict[int, int]:
    raw = jload(c, "slots_used", {})
    return {int(k): int(v) for k, v in raw.items()}


def slots_left(c: Mapping) -> dict[int, int]:
    used = slots_used(c)
    return {lvl: total - used.get(lvl, 0) for lvl, total in enumerate(slots_total(c), start=1)}


def max_slot_level(c: Mapping) -> int:
    return len(slots_total(c))


def prepared_limit(c: Mapping) -> int:
    ability = caster_ability(c)
    return max(1, mod_of(c, ability) + c["level"]) if ability else 0


def domain_spells(c: Mapping) -> list[str]:
    if class_of(c) != "Жрец":
        return []
    result: list[str] = []
    for lvl, names in srd.LIFE_DOMAIN_SPELLS.items():
        if c["level"] >= lvl:
            result += names
    return result


def cantrips_of(c: Mapping) -> list[str]:
    return jload(c, "cantrips", [])


def spellbook_of(c: Mapping) -> list[str]:
    return jload(c, "spellbook", [])


def prepared_of(c: Mapping) -> list[str]:
    return jload(c, "prepared", [])


def castable_spells(c: Mapping) -> list[str]:
    """Что можно колдовать: заговоры, подготовленные и (у жреца) доменные заклинания."""
    seen: dict[str, None] = {}
    for name in cantrips_of(c) + domain_spells(c) + prepared_of(c):
        seen[name] = None
    return list(seen)


def cantrip_multiplier(level: int) -> int:
    """Урон заговора растёт на 5, 11 и 17 уровнях (с. 87)."""
    return 1 + (level >= 5) + (level >= 11) + (level >= 17)


def scale_dice(notation: str, times: int) -> str:
    parsed = dice.parse_notation(notation)
    if parsed is None:
        return notation
    count, sides, bonus = parsed
    return dice.format_notation(count * times, sides, bonus)


def add_dice(notation: str, extra: str, times: int = 1) -> str:
    """'3d6' + 2×'1d6' -> '5d6'. Кубики разных граней не смешиваются."""
    a, b = dice.parse_notation(notation), dice.parse_notation(extra)
    if a is None or b is None or a[1] != b[1]:
        return notation
    return dice.format_notation(a[0] + b[0] * times, a[1], a[2])


def arcane_recovery_budget(level: int) -> int:
    """Суммарный уровень ячеек, которые волшебник возвращает за отдых (с. 33): половина уровня вверх."""
    return (level + 1) // 2


# ---------------------------------------------------------------- лист персонажа

def features_of(c: Mapping) -> list[str]:
    class_name = class_of(c)
    result: list[str] = []
    for lvl in sorted(CLASSES[class_name]["features"]):
        if c["level"] >= lvl:
            result += CLASSES[class_name]["features"][lvl]
    return result


def format_stats(c: Mapping) -> str:
    stats = stats_of(c)
    saves = save_proficiencies(c)
    lines = []
    for ability in ABILITIES:
        bonus, prof = save_bonus(c, ability)
        star = "★" if prof else " "
        lines.append(
            f"{srd.ABILITY_SHORT[ability]} {stats[ability]:>2} ({format_modifier(modifier(stats[ability]))})"
            f"  спасбросок {format_modifier(bonus)} {star}"
        )
    return "\n".join(lines)


def format_skills(c: Mapping) -> str:
    lines = []
    for skill in SKILLS:
        bonus, level, _ = check_bonus(c, skill)
        mark = "◆" if level == 2 else "★" if level == 1 else " "
        lines.append(f"{mark} {skill}: {format_modifier(bonus)}")
    return "\n".join(lines)


def choose_random(items: list, k: int) -> list:
    return random.sample(items, min(k, len(items)))
