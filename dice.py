"""Кубики: запись вида 2d6+1, d20-проверки и поиск атрибута по названию."""

import random
import re

NOTATION = re.compile(r"^(\d*)d(\d+)([+-]\d+)?$", re.IGNORECASE)

MAX_DICE = 20
MAX_SIDES = 1000


def parse_notation(text: str) -> tuple[int, int, int] | None:
    """'2d6+1' -> (2, 6, 1); 'd20' -> (1, 20, 0). None, если это не запись броска."""
    match = NOTATION.match(text.strip())
    if match is None:
        return None
    count = int(match.group(1)) if match.group(1) else 1
    sides = int(match.group(2))
    modifier = int(match.group(3)) if match.group(3) else 0
    if not (1 <= count <= MAX_DICE) or not (2 <= sides <= MAX_SIDES):
        return None
    return count, sides, modifier


def format_notation(count: int, sides: int, modifier: int = 0) -> str:
    base = f"{count}d{sides}"
    if modifier > 0:
        return f"{base}+{modifier}"
    if modifier < 0:
        return f"{base}{modifier}"
    return base


def roll(count: int, sides: int) -> list[int]:
    return [random.randint(1, sides) for _ in range(count)]


def roll_notation(text: str, double_dice: bool = False) -> tuple[int, list[int], int] | None:
    """Бросок по записи. Возвращает (итог, кубики, модификатор). double_dice — для критов."""
    parsed = parse_notation(text)
    if parsed is None:
        return None
    count, sides, modifier = parsed
    if double_dice:
        count *= 2
    results = roll(count, sides)
    return sum(results) + modifier, results, modifier


def d20() -> int:
    return random.randint(1, 20)


def d20_check(bonus: int) -> tuple[int, int]:
    """Бросок d20 с бонусом. Возвращает (значение кубика, итог)."""
    value = d20()
    return value, value + bonus


def four_d6_drop_lowest() -> int:
    """Классическая генерация характеристики: 4d6, худший кубик отбрасывается."""
    results = sorted(roll(4, 6))
    return sum(results[1:])


def match_attribute(query: str, attributes: list[str]) -> str | None:
    """Ищет атрибут по началу слова, без учёта регистра."""
    q = query.strip().casefold()
    if not q:
        return None
    for attr in attributes:
        if attr.casefold() == q:
            return attr
    for attr in attributes:
        if attr.casefold().startswith(q):
            return attr
    return None
