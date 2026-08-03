"""Нопанхейтот: d20-проверки атрибутов и произвольные броски вида 2d6."""

import random
import re

NOTATION = re.compile(r"^(\d*)d(\d+)$", re.IGNORECASE)

MAX_DICE = 20
MAX_SIDES = 1000


def parse_notation(text: str) -> tuple[int, int] | None:
    """'2d6' -> (2, 6), 'd20' -> (1, 20). None, если это не запись броска."""
    match = NOTATION.match(text.strip())
    if match is None:
        return None
    count = int(match.group(1)) if match.group(1) else 1
    sides = int(match.group(2))
    if not (1 <= count <= MAX_DICE) or not (2 <= sides <= MAX_SIDES):
        return None
    return count, sides


def roll(count: int, sides: int) -> list[int]:
    return [random.randint(1, sides) for _ in range(count)]


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


def d20_check(bonus: int) -> tuple[int, int]:
    """Бросок d20 с бонусом. Возвращает (значение кубика, итог)."""
    value = random.randint(1, 20)
    return value, value + bonus
