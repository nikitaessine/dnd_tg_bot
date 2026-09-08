"""Игровые правила: характеристики, модификаторы, уровни, здоровье, класс доспеха.

Здесь нет ни Telegram, ни базы — только чистые вычисления, которые легко тестировать.
"""

import json
import random
from collections.abc import Mapping

import dice
from config import (
    ATTR_CON,
    ATTR_DEX,
    ATTR_STR,
    ATTRIBUTES,
    BASE_ARMOR_CLASS,
    DEFAULT_HP,
    HP_PER_LEVEL,
    MAX_LEVEL,
    XP_PER_LEVEL,
)


def modifier(score: int) -> int:
    """Модификатор по классической формуле D&D: (значение − 10) / 2 с округлением вниз."""
    return (score - 10) // 2


def format_modifier(value: int) -> str:
    return f"+{value}" if value >= 0 else str(value)


def proficiency(level: int) -> int:
    """Бонус мастерства: +2 на 1–4 уровнях, +3 на 5–8 и так далее."""
    return 2 + (level - 1) // 4


def xp_needed(level: int) -> int:
    return XP_PER_LEVEL * level


def chosen_attributes(character: Mapping) -> list[str]:
    return [a.strip() for a in character["attributes"].split(",") if a.strip()]


def generate_stats(chosen: list[str]) -> dict[str, int]:
    """Бросает 4d6 (без худшего) для всех атрибутов; четыре лучших результата
    достаются выбранным атрибутам, чтобы персонаж был силён именно в них."""
    rolls = sorted((dice.four_d6_drop_lowest() for _ in ATTRIBUTES), reverse=True)
    chosen_order = [a for a in ATTRIBUTES if a in chosen]
    other_order = [a for a in ATTRIBUTES if a not in chosen]
    random.shuffle(chosen_order)
    random.shuffle(other_order)
    stats: dict[str, int] = {}
    for attr, value in zip(chosen_order + other_order, rolls):
        stats[attr] = value
    return stats


def default_stats(chosen: list[str]) -> dict[str, int]:
    """Характеристики для персонажей, созданных до появления числовых значений."""
    return {a: (16 if a in chosen else 10) for a in ATTRIBUTES}


def stats_of(character: Mapping) -> dict[str, int]:
    raw = character["stats"] if "stats" in character.keys() else None
    if raw:
        stats = json.loads(raw)
        # На случай, если список атрибутов в конфиге расширили
        for attr in ATTRIBUTES:
            stats.setdefault(attr, 10)
        return stats
    return default_stats(chosen_attributes(character))


def check_bonus(character: Mapping, attribute: str) -> tuple[int, bool]:
    """Бонус к проверке атрибута: модификатор + мастерство, если атрибут — один из выбранных.
    Возвращает (бонус, применено ли мастерство)."""
    stats = stats_of(character)
    proficient = attribute in chosen_attributes(character)
    bonus = modifier(stats[attribute]) + (proficiency(character["level"]) if proficient else 0)
    return bonus, proficient


def attack_attribute(stats: Mapping[str, int]) -> str:
    """Для атаки берётся лучший из Силы и Ловкости."""
    return ATTR_STR if stats[ATTR_STR] >= stats[ATTR_DEX] else ATTR_DEX


def attack_bonus(character: Mapping) -> tuple[int, str]:
    stats = stats_of(character)
    attr = attack_attribute(stats)
    return modifier(stats[attr]) + proficiency(character["level"]), attr


def armor_class(character: Mapping, armor_bonus: int = 0) -> int:
    stats = stats_of(character)
    return BASE_ARMOR_CLASS + modifier(stats[ATTR_DEX]) + armor_bonus


def initial_max_hp(stats: Mapping[str, int]) -> int:
    return max(1, DEFAULT_HP + modifier(stats[ATTR_CON]))


def weapon_damage(notation: str, stats: Mapping[str, int], crit: bool = False) -> tuple[int, str]:
    """Урон оружием: кубики (удвоенные при крите) + модификатор атакующего атрибута.
    Возвращает (урон, расшифровка)."""
    rolled = dice.roll_notation(notation, double_dice=crit)
    if rolled is None:
        rolled = dice.roll_notation("1d4", double_dice=crit)
    total, results, mod = rolled
    attr_mod = modifier(stats[attack_attribute(stats)])
    damage = max(1, total + attr_mod)
    parts = " + ".join(map(str, results))
    detail = f"{parts}"
    if mod:
        detail += f" {format_modifier(mod)}"
    if attr_mod:
        detail += f" {format_modifier(attr_mod)}"
    return damage, detail


def apply_xp(character: Mapping, amount: int) -> dict:
    """Начисляет опыт, повышает уровни. Возвращает новые значения и число полученных уровней."""
    level, xp = character["level"], character["xp"] + amount
    max_hp, hp = character["max_hp"], character["hp"]
    con_mod = modifier(stats_of(character)[ATTR_CON])
    gained = 0
    while level < MAX_LEVEL and xp >= xp_needed(level):
        xp -= xp_needed(level)
        level += 1
        gained += 1
        max_hp += max(1, HP_PER_LEVEL + con_mod)
    if gained:
        hp = max_hp  # повышение уровня полностью восстанавливает здоровье
    return {"level": level, "xp": xp, "max_hp": max_hp, "hp": hp, "gained": gained}


def death_save(character: Mapping) -> dict:
    """Спасбросок от смерти для персонажа с 0 HP.
    20 — приходит в себя с 1 HP; 10+ — успех; иначе провал.
    Три успеха — стабилизирован, три провала — смерть."""
    value = dice.d20()
    successes, failures = character["death_successes"], character["death_failures"]
    result = {"roll": value, "hp": 0, "alive": True, "stable": False, "revived": False}
    if value == 20:
        result.update(hp=1, revived=True, successes=0, failures=0)
        return result
    if value >= 10:
        successes += 1
    else:
        failures += 1
    result.update(successes=successes, failures=failures)
    if failures >= 3:
        result["alive"] = False
    elif successes >= 3:
        result["stable"] = True
    return result


def format_stats(character: Mapping) -> str:
    stats = stats_of(character)
    chosen = chosen_attributes(character)
    lines = []
    for attr in ATTRIBUTES:
        star = "★ " if attr in chosen else "   "
        lines.append(f"{star}{attr}: {stats[attr]} ({format_modifier(modifier(stats[attr]))})")
    return "\n".join(lines)
