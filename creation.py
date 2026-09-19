"""Создание персонажа по правилам гл. 1: раса, класс, предыстория, характеристики,
навыки, заклинания и стартовое снаряжение.

Без Telegram: принимает выбор игрока и записывает готового персонажа в базу.
"""

import db
import rules
import srd
from spelldata import SPELLS
from srd import CLASSES, CON, STR

# Порядок, в котором быстрая сборка выбирает боевые заклинания при небольшом лимите (с. 32)
WIZARD_PREPARE_ORDER = ["Волшебная стрела", "Щит", "Доспехи мага", "Усыпление", "Огненные ладони", "Очарование личности"]


def skill_options(class_name: str, race: str, subrace: str, background: str) -> list[str]:
    """Навыки класса, которых у персонажа ещё нет: одно и то же мастерство дважды не даётся (с. 38)."""
    known = set(srd.BACKGROUNDS[background]["skills"]) | set(srd.RACES[race].get("skills", []))
    known |= set(srd.RACES[race].get("subraces", {}).get(subrace, {}).get("skills", []))
    return [s for s in CLASSES[class_name]["skill_choices"] if s not in known]


def known_skills(race: str, subrace: str, background: str, picked: list[str]) -> list[str]:
    skills = list(srd.BACKGROUNDS[background]["skills"]) + list(srd.RACES[race].get("skills", []))
    skills += list(srd.RACES[race].get("subraces", {}).get(subrace, {}).get("skills", []))
    for s in picked:
        if s not in skills:
            skills.append(s)
    return skills


def build_stats(class_name: str, values: list[int], race: str, subrace: str) -> dict[str, int]:
    return rules.apply_racial_bonuses(rules.assign_stats(class_name, values), race, subrace)


def starting_spells(class_name: str, level: int, stats: dict, race: str, subrace: str) -> dict:
    """Заклинания на 1 уровне: быстрая сборка из описания класса (с. 23, 32)."""
    if class_name not in ("Жрец", "Волшебник"):
        return {"cantrips": [], "spellbook": [], "prepared": []}
    cantrips = list(srd.QUICK_CANTRIPS[class_name])
    info = srd.RACES[race].get("subraces", {}).get(subrace, {})
    if class_name == "Волшебник" and info.get("bonus_cantrip"):
        extra = next((c for c in ("Огненный снаряд", "Электрошок", "Кислотные брызги") if c not in cantrips), None)
        if extra:
            cantrips.append(extra)
    ability = CLASSES[class_name]["caster"]
    limit = max(1, rules.modifier(stats[ability]) + level)
    if class_name == "Жрец":
        return {"cantrips": cantrips, "spellbook": [], "prepared": srd.QUICK_CLERIC_PREPARE[:limit]}
    spellbook = list(srd.QUICK_SPELLBOOK)
    prepared = [s for s in WIZARD_PREPARE_ORDER if s in spellbook][:limit]
    return {"cantrips": cantrips, "spellbook": spellbook, "prepared": prepared}


def starting_gear(class_name: str, strength: int) -> list[tuple[str, str]]:
    gear = list(srd.STARTING_GEAR[class_name])
    if class_name == "Жрец":
        gear.insert(1, ("Кольчуга" if strength >= 13 else "Чешуйчатый доспех", "armor"))
    gear.append(("Рюкзак путешественника", "item"))
    return gear


def give_gear(chat_id: int, user_id: int, class_name: str, strength: int) -> None:
    """Выдаёт снаряжение и надевает лучшее: основное оружие, доспех, щит."""
    equipped: set[str] = set()
    for name, kind in starting_gear(class_name, strength):
        found = rules.srd_item(name)
        value = found[1] if found else ""
        item_kind = found[0] if found else kind
        item = db.add_item(chat_id, user_id, name, item_kind, value)
        if item_kind in ("weapon", "armor", "shield") and item_kind not in equipped:
            db.equip_item(chat_id, user_id, item["id"], item_kind)
            equipped.add(item_kind)


def create(chat_id: int, user_id: int, user_name: str, name: str, description: str, data: dict) -> bool:
    """Записывает персонажа. data: race, subrace, cls, bg, values, skills, expertise, style."""
    race, subrace, cls = data["race"], data.get("subrace", ""), data["cls"]
    stats = build_stats(cls, data["values"], race, subrace)
    info = srd.RACES[race].get("subraces", {}).get(subrace, {})
    max_hp = rules.initial_max_hp(cls, rules.modifier(stats[CON]), info.get("hp_per_level", 0))
    spells = starting_spells(cls, 1, stats, race, subrace)
    saved = db.save_character(
        chat_id, user_id, user_name, name, description,
        race=race, subrace=subrace, char_class=cls, background=data["bg"],
        stats=stats, hp=max_hp, max_hp=max_hp,
        skills=known_skills(race, subrace, data["bg"], data.get("skills", [])),
        expertise=data.get("expertise", []), fighting_style=data.get("style", ""),
        cantrips=spells["cantrips"], spellbook=spells["spellbook"], prepared=spells["prepared"],
    )
    if saved:
        give_gear(chat_id, user_id, cls, stats[STR])
    return saved
