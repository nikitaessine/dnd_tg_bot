"""Разбор команды /take и описание предметов. Без Telegram."""

import dice
import rules
import srd


def set_magic_bonus(kind: str, value: dict, bonus: int) -> dict:
    """Магический бонус предмета. У щита поле bonus — полный бонус к КД (2 + магия)."""
    value["bonus"] = (srd.SHIELD_AC + bonus) if kind == "shield" else bonus
    return value


def parse_take(text: str) -> tuple[str, str, dict | str] | None:
    """Разбирает текст команды /take. Возвращает (название, тип, значение) или None, если непонятно.

    Форматы:
      «Длинный меч»                   — предмет из правил
      «Кольчуга +1»                   — предмет из правил с магическим бонусом
      «Меч пламени | Длинный меч +1»  — своё название на основе предмета из правил
      «Нож 1d4»                       — своё оружие (кубик урона)
      «Верёвка»                       — обычный предмет
    """
    text = text.strip()
    if not text:
        return None
    if "|" in text:
        name, base = (part.strip() for part in text.split("|", 1))
        tokens = base.split()
        bonus = 0
        if tokens and tokens[-1].startswith("+") and tokens[-1][1:].isdigit():
            bonus = min(3, int(tokens[-1][1:]))
            tokens = tokens[:-1]
        found = rules.srd_item(" ".join(tokens))
        if not name or found is None:
            return None
        kind, value = found
        return name[:60], kind, set_magic_bonus(kind, value, bonus)
    tokens = text.split()
    bonus = None
    body = tokens
    if len(tokens) > 1 and tokens[-1].startswith("+") and tokens[-1][1:].isdigit():
        bonus = min(10, int(tokens[-1][1:]))
        body = tokens[:-1]
    name = " ".join(body)
    found = rules.srd_item(name)
    if found is not None:
        kind, value = found
        if bonus is not None:
            set_magic_bonus(kind, value, min(3, bonus))
        return value.get("srd", name), kind, value
    if bonus is not None:  # прежний формат: «Кольчуга +2» для своей брони
        return name[:60], "armor", {"base": 10 + bonus, "cat": "light", "str": 0, "stealth": False, "bonus": 0}
    if len(tokens) > 1 and dice.parse_notation(tokens[-1]) is not None:
        return " ".join(tokens[:-1])[:60], "weapon", {
            "dice": tokens[-1].lower(), "dtype": "", "cat": "simple", "ranged": False, "props": [], "bonus": 0}
    return name[:60], "item", ""


def describe_item(item) -> str:
    """Краткое описание для инвентаря."""
    if item["kind"] == "weapon":
        w = rules.weapon_info(item)
        props = []
        if w["ranged"]:
            props.append("дальнобойное")
        for p in sorted(w["props"]):
            props.append({"finesse": "фехтовальное", "light": "лёгкое", "heavy": "тяжёлое", "two_handed": "двуручное",
                          "thrown": "метательное", "reach": "досягаемость", "loading": "перезарядка",
                          "ammo": "боеприпасы"}.get(p, f"универсальное {p.split(':')[1]}" if p.startswith("versatile:") else p))
        bonus = f" +{w['bonus']}" if w["bonus"] else ""
        return f"урон {w['dice']}{bonus} {w['dtype']}".strip() + (f" ({', '.join(props)})" if props else "")
    if item["kind"] == "armor":
        a = rules.armor_info(item)
        cat = srd.ARMOR_CATEGORY_NAMES.get(a["cat"], a["cat"])
        extra = f", нужна Сила {a['str']}" if a["str"] else ""
        extra += ", помеха на скрытность" if a["stealth"] else ""
        bonus = f" +{a['bonus']}" if a["bonus"] else ""
        return f"{cat} доспех, КД {a['base']}{bonus}{extra}"
    if item["kind"] == "shield":
        return f"щит, +{rules.shield_bonus(item)} к КД"
    return ""
