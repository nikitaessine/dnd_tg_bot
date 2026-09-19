"""Кубики: запись вида 2d6+1, d20 с преимуществом/помехой и везением, поиск по названию."""

import random
import re

NOTATION = re.compile(r"^(\d*)d(\d+)([+-]\d+)?$", re.IGNORECASE)

MAX_DICE = 40
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


def average_notation(text: str) -> float:
    parsed = parse_notation(text)
    if parsed is None:
        try:
            return float(text)
        except ValueError:
            return 0.0
    count, sides, modifier = parsed
    return count * (sides + 1) / 2 + modifier


def d20() -> int:
    return random.randint(1, 20)


def roll_d20(mode: int = 0, lucky: bool = False, floor: int | None = None) -> tuple[int, list[int]]:
    """d20 с преимуществом (mode=1), помехой (mode=-1) или без них.

    lucky — «Везучий» полуросликов: выпавшую 1 можно перебросить, новый результат обязателен (с. 18).
    floor — «Надёжный талант» плута: значения ниже floor считаются как floor (с. 30).
    Возвращает (итоговое значение, все брошенные кубики)."""
    dice_list = [d20()] if mode == 0 else [d20(), d20()]

    def pick(values: list[int]) -> int:
        return max(values) if mode > 0 else min(values) if mode < 0 else values[0]

    if lucky and pick(dice_list) == 1:
        dice_list[dice_list.index(1)] = d20()
    value = pick(dice_list)
    if floor is not None and value < floor:
        value = floor
    return value, dice_list


def d20_check(bonus: int, mode: int = 0, lucky: bool = False,
              floor: int | None = None) -> tuple[int, int, list[int]]:
    """Проверка d20 + бонус. Возвращает (кубик, итог, все кубики)."""
    value, all_dice = roll_d20(mode, lucky, floor)
    return value, value + bonus, all_dice


def four_d6_drop_lowest() -> int:
    """Генерация характеристики (с. 9): 4d6, худший кубик отбрасывается."""
    results = sorted(roll(4, 6))
    return sum(results[1:])


def _norm(text: str) -> str:
    return text.strip().casefold().replace("ё", "е")


def match_name(query: str, names) -> str | None:
    """Ищет название: точное совпадение, затем начало слова, затем вхождение. Регистр и «ё» не важны."""
    q = _norm(query)
    if not q:
        return None
    names = list(names)
    for name in names:
        if _norm(name) == q:
            return name
    for name in names:
        if _norm(name).startswith(q):
            return name
    for name in names:
        if q in _norm(name):
            return name
    return None


def match_prefix(tokens: list[str], names) -> tuple[str, int] | None:
    """Ищет самое длинное начало списка слов, совпадающее с названием (точно или по началу).
    Возвращает (название, сколько слов использовано) — для команд вида «/cast Огненный шар 3 Гоблин»."""
    names = list(names)
    for size in range(len(tokens), 0, -1):
        candidate = _norm(" ".join(tokens[:size]))
        for name in names:
            if _norm(name) == candidate:
                return name, size
    for size in range(len(tokens), 0, -1):
        candidate = _norm(" ".join(tokens[:size]))
        for name in names:
            if _norm(name).startswith(candidate):
                return name, size
    return None


# Обратная совместимость с прежним именем
match_attribute = match_name
