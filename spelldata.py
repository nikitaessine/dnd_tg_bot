"""Заклинания жреца и волшебника (D&D Basic Rules, гл. 11, списки на с. 86).

SPELL_LISTS — полные списки классов. SPELLS — механика заклинаний, которые бот считает
сам (урон, лечение, спасброски, состояния). Остальные заклинания из списков можно
подготовить и колдовать: бот тратит ячейку и записывает событие в журнал, а мастер и
сюжет учитывают эффект «по описанию».
"""

# ---------------------------------------------------------------- полные списки (с. 86)

SPELL_LISTS = {
    "Жрец": {
        0: ["Указание", "Свет", "Сопротивление", "Священное пламя", "Сохранение жизни", "Чудотворство"],
        1: ["Благословение", "Приказ", "Лечение ран", "Обнаружение магии", "Направляющий снаряд",
            "Лечащее слово", "Нанесение ран", "Убежище", "Щит веры"],
        2: ["Помощь", "Знамение", "Удержание личности", "Малое восстановление", "Молитва исцеления",
            "Тишина", "Духовное оружие", "Оберегающая связь"],
        3: ["Маяк надежды", "Рассеивание магии", "Массовое лечащее слово", "Защита от энергии",
            "Снятие проклятия", "Возвращение к жизни", "Разговор с мёртвыми", "Духовные стражи"],
        4: ["Защита от смерти", "Гадание", "Свобода перемещения", "Страж веры", "Поиск существа"],
        5: ["Общение", "Небесный огонь", "Высшее восстановление", "Массовое лечение ран", "Воскрешение мёртвых"],
        6: ["Барьер клинков", "Поиск пути", "Вред", "Исцеление", "Пир героев", "Истинное зрение"],
        7: ["Эфирность", "Огненный шторм", "Регенерация", "Воскрешение"],
        8: ["Антимагическое поле", "Землетрясение", "Святая аура"],
        9: ["Астральная проекция", "Врата", "Массовое исцеление", "Истинное воскрешение"],
    },
    "Волшебник": {
        0: ["Кислотные брызги", "Танцующие огоньки", "Огненный снаряд", "Свет", "Волшебная рука", "Малая иллюзия",
            "Ядовитые брызги", "Фокусы", "Луч холода", "Электрошок"],
        1: ["Огненные ладони", "Очарование личности", "Понимание языков", "Обнаружение магии", "Маскировка",
            "Опознание", "Доспехи мага", "Волшебная стрела", "Щит", "Тихий образ", "Усыпление", "Волна грома"],
        2: ["Волшебный замок", "Размытость", "Тьма", "Пылающая сфера", "Удержание личности", "Невидимость",
            "Открывание", "Левитация", "Волшебное оружие", "Туманный шаг", "Дребезги", "Паучье лазание",
            "Внушение", "Паутина"],
        3: ["Контрзаклинание", "Рассеивание магии", "Огненный шар", "Полёт", "Ускорение", "Молния",
            "Крупный образ", "Защита от энергии"],
        4: ["Волшебный глаз", "Дверь измерений", "Высшая невидимость", "Град", "Каменная кожа", "Стена огня"],
        5: ["Конус холода", "Подчинение личности", "Сон-видение", "Проход", "Каменная стена"],
        6: ["Цепная молния", "Дезинтеграция", "Сфера неуязвимости", "Массовое внушение",
            "Неудержимый танец Отто", "Истинное зрение"],
        7: ["Огненный шар с задержкой", "Палец смерти", "Меч Морденкайнена", "Телепортация"],
        8: ["Подчинение чудовища", "Лабиринт", "Слово силы: оглушение", "Солнечный взрыв"],
        9: ["Предвидение", "Заточение", "Метеоритный дождь", "Слово силы: смерть", "Остановка времени"],
    },
}

# ---------------------------------------------------------------- механика

SPELLS: dict[str, dict] = {}


def _spell(name: str, level: int, classes: list[str], kind: str, **kw) -> None:
    SPELLS[name] = {"name": name, "level": level, "classes": classes, "kind": kind, **kw}


CL, WZ = "Жрец", "Волшебник"

# ---- заговоры
_spell("Священное пламя", 0, [CL], "save", school="воплощение", dice="1d8", dtype="излучение",
       save="Ловкость", half=False, max_targets=1, cantrip=True)
_spell("Огненный снаряд", 0, [WZ], "attack", school="воплощение", dice="1d10", dtype="огонь", cantrip=True)
_spell("Луч холода", 0, [WZ], "attack", school="воплощение", dice="1d8", dtype="холод", cantrip=True)
_spell("Электрошок", 0, [WZ], "attack", school="воплощение", dice="1d8", dtype="электричество",
       melee=True, cantrip=True)
_spell("Кислотные брызги", 0, [WZ], "save", school="вызов", dice="1d6", dtype="кислота",
       save="Ловкость", half=False, max_targets=2, cantrip=True)
_spell("Ядовитые брызги", 0, [WZ], "save", school="вызов", dice="1d12", dtype="яд",
       save="Телосложение", half=False, max_targets=1, cantrip=True)
_spell("Указание", 0, [CL], "buff", effect="указание", target="ally", rounds=10)
_spell("Сопротивление", 0, [CL], "buff", effect="сопротивление", target="ally", rounds=10)
_spell("Сохранение жизни", 0, [CL], "stabilize")
for _n in ("Свет", "Чудотворство", "Танцующие огоньки", "Волшебная рука", "Малая иллюзия", "Фокусы"):
    _spell(_n, 0, [CL, WZ], "narrative")

# ---- 1 уровень
_spell("Направляющий снаряд", 1, [CL], "attack", school="воплощение", dice="4d6", dtype="излучение",
       per_slot="1d6", effect="отмечен", effect_rounds=2)
_spell("Нанесение ран", 1, [CL], "attack", school="некромантия", dice="3d10", dtype="некротический",
       per_slot="1d10", melee=True)
_spell("Лечение ран", 1, [CL], "heal", school="воплощение", dice="1d8", per_slot="1d8")
_spell("Лечащее слово", 1, [CL], "heal", school="воплощение", dice="1d4", per_slot="1d4", time="bonus")
_spell("Благословение", 1, [CL], "buff", effect="благословлён", target="allies", max_targets=3,
       conc=True, rounds=10, per_slot_targets=1)
_spell("Щит веры", 1, [CL], "buff", effect="щит веры", target="ally", conc=True, rounds=100, time="bonus")
_spell("Приказ", 1, [CL], "save", save="Мудрость", effect="приказ", effect_rounds=1, max_targets=1,
       school="очарование", per_slot_targets=1)
_spell("Убежище", 1, [CL], "buff", effect="убежище", target="ally", rounds=10, time="bonus")
_spell("Огненные ладони", 1, [WZ], "save", school="воплощение", dice="3d6", dtype="огонь", per_slot="1d6",
       save="Ловкость", half=True, max_targets=3)
_spell("Волшебная стрела", 1, [WZ], "auto", school="воплощение", dice="1d4+1", dtype="сила", darts=3)
_spell("Щит", 1, [WZ], "buff", school="ограждение", effect="щит", target="self", rounds=1, time="reaction")
_spell("Доспехи мага", 1, [WZ], "buff", school="ограждение", effect="доспехи мага", target="ally", rounds=None)
_spell("Усыпление", 1, [WZ], "sleep", school="очарование", dice="5d8", per_slot="2d8")
_spell("Волна грома", 1, [WZ], "save", school="воплощение", dice="2d8", dtype="звук", per_slot="1d8",
       save="Телосложение", half=True, max_targets=3)
_spell("Очарование личности", 1, [WZ], "save", school="очарование", save="Мудрость", effect="очарован",
       effect_rounds=None, max_targets=1, per_slot_targets=1)
for _n in ("Обнаружение магии", "Понимание языков", "Маскировка", "Опознание", "Тихий образ"):
    _spell(_n, 1, [CL, WZ], "narrative")

# ---- 2 уровень
_spell("Духовное оружие", 2, [CL], "persistent", school="воплощение", dice="1d8", dtype="сила",
       per_slot="1d8", per_slot_step=2, effect="духовное оружие", rounds=10, time="bonus", melee=True)
_spell("Удержание личности", 2, [CL, WZ], "save", school="очарование", save="Мудрость", effect="парализован",
       effect_rounds=10, save_repeat=True, conc=True, max_targets=1, per_slot_targets=1)
_spell("Помощь", 2, [CL], "aid", school="ограждение", bonus=5)
_spell("Молитва исцеления", 2, [CL], "heal", school="воплощение", dice="2d8", per_slot="1d8",
       party=True, out_of_combat=True)
_spell("Малое восстановление", 2, [CL], "cure")
_spell("Дребезги", 2, [WZ], "save", school="воплощение", dice="3d8", dtype="звук", per_slot="1d8",
       save="Телосложение", half=True, max_targets=3)
_spell("Паутина", 2, [WZ], "save", school="вызов", save="Ловкость", effect="опутан", effect_rounds=10,
       save_repeat=True, conc=True, max_targets=3, escape_check=True)
_spell("Размытость", 2, [WZ], "buff", school="иллюзия", effect="размытость", target="self", conc=True, rounds=10)
_spell("Невидимость", 2, [WZ], "buff", school="иллюзия", effect="невидим", target="ally", conc=True, rounds=100)
_spell("Пылающая сфера", 2, [WZ], "persistent", school="вызов", dice="2d6", dtype="огонь", per_slot="1d6",
       save="Ловкость", half=False, effect="пылающая сфера", rounds=10, conc=True, time="action")
_spell("Волшебное оружие", 2, [WZ], "buff", school="преобразование", effect="волшебное оружие", target="ally",
       conc=True, rounds=100, time="bonus")
_spell("Внушение", 2, [WZ], "save", school="очарование", save="Мудрость", effect="внушение",
       effect_rounds=10, conc=True, max_targets=1)
_spell("Туманный шаг", 2, [WZ], "narrative", time="bonus")
for _n in ("Знамение", "Тишина", "Оберегающая связь", "Волшебный замок", "Тьма", "Открывание",
           "Левитация", "Паучье лазание"):
    _spell(_n, 2, [CL, WZ], "narrative")

# ---- 3 уровень
_spell("Огненный шар", 3, [WZ], "save", school="воплощение", dice="8d6", dtype="огонь", per_slot="1d6",
       save="Ловкость", half=True, max_targets=6)
_spell("Молния", 3, [WZ], "save", school="воплощение", dice="8d6", dtype="электричество", per_slot="1d6",
       save="Ловкость", half=True, max_targets=3)
_spell("Ускорение", 3, [WZ], "buff", school="преобразование", effect="ускорен", target="ally", conc=True, rounds=10)
_spell("Массовое лечащее слово", 3, [CL], "heal", school="воплощение", dice="1d4", per_slot="1d4",
       time="bonus", max_targets=6)
_spell("Духовные стражи", 3, [CL], "aura", school="вызов", dice="3d8", dtype="излучение", per_slot="1d8",
       save="Мудрость", half=True, effect="духовные стражи", conc=True, rounds=100)
_spell("Маяк надежды", 3, [CL], "buff", school="ограждение", effect="маяк надежды", target="party", conc=True, rounds=10)
_spell("Возвращение к жизни", 3, [CL], "revive", school="некромантия", window="scene")
for _n in ("Рассеивание магии", "Защита от энергии", "Снятие проклятия", "Разговор с мёртвыми",
           "Контрзаклинание", "Полёт", "Крупный образ"):
    _spell(_n, 3, [CL, WZ], "narrative")

# ---- 4–6 уровни: избранные заклинания с механикой
_spell("Град", 4, [WZ], "save", school="воплощение", dice="2d8", dtype="дробящий", per_slot="1d8",
       extra_dice="4d6", extra_dtype="холод", save="Ловкость", half=True, max_targets=4)
_spell("Конус холода", 5, [WZ], "save", school="воплощение", dice="8d8", dtype="холод", per_slot="1d8",
       save="Телосложение", half=True, max_targets=4)
_spell("Небесный огонь", 5, [CL], "save", school="воплощение", dice="4d6", dtype="огонь", per_slot="1d6",
       extra_dice="4d6", extra_dtype="излучение", save="Ловкость", half=True, max_targets=3)
_spell("Массовое лечение ран", 5, [CL], "heal", school="воплощение", dice="3d8", per_slot="1d8", max_targets=6)
_spell("Воскрешение мёртвых", 5, [CL], "revive", school="некромантия", window="days")
_spell("Цепная молния", 6, [WZ], "save", school="воплощение", dice="10d8", dtype="электричество",
       save="Ловкость", half=True, max_targets=4)
_spell("Исцеление", 6, [CL], "heal_fixed", school="воплощение", bonus=70, per_slot_bonus=10)

# Остальные заклинания из списков — «по описанию»
for _cls, _levels in SPELL_LISTS.items():
    for _lvl, _names in _levels.items():
        for _n in _names:
            if _n not in SPELLS:
                _spell(_n, _lvl, [_cls], "narrative")
            elif _cls not in SPELLS[_n]["classes"]:
                SPELLS[_n]["classes"].append(_cls)


def spells_of_class(class_name: str, max_level: int, min_level: int = 0) -> list[str]:
    """Названия заклинаний класса от min_level до max_level включительно (в порядке списка)."""
    lists = SPELL_LISTS.get(class_name, {})
    result: list[str] = []
    for lvl in range(min_level, max_level + 1):
        result += lists.get(lvl, [])
    return result


def is_class_spell(class_name: str, spell: str) -> bool:
    return any(spell in names for names in SPELL_LISTS.get(class_name, {}).values())
