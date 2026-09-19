"""Общая подготовка: переменные окружения-заглушки и чистая база на каждый тест."""

import os
import sys

os.environ.setdefault("BOT_TOKEN", "123:test")
os.environ.setdefault("ANTHROPIC_API_KEY", "sk-test")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest  # noqa: E402

import creation  # noqa: E402
import db  # noqa: E402
import rules  # noqa: E402
import srd  # noqa: E402


@pytest.fixture(autouse=True)
def fresh_db(tmp_path):
    """Каждый тест работает со своей пустой базой."""
    db._conn = None
    db.DB_PATH = str(tmp_path / "test.db")
    yield
    if db._conn is not None:
        db._conn.close()
        db._conn = None


CHAT = 1
GM = 10
PLAYER = 11
PLAYER2 = 12

STANDARD = [15, 14, 13, 12, 10, 8]


def make_world(chat_id: int = CHAT, gm: int = GM):
    db.set_world(chat_id, "тест", "тестовый мир", gm)
    return db.get_world(chat_id)


def make_hero(user_id: int = PLAYER, name: str = "Гарен", cls: str = "Воин", race: str = "Человек",
              subrace: str = "", level: int = 1, chat_id: int = CHAT, values=None, skills=None,
              style: str = "", gear: bool = True, **fields):
    """Персонаж по правилам: стандартный набор 15/14/13/12/10/8 по приоритетам класса,
    расовые бонусы, хиты 1 уровня, заклинания быстрой сборки, стартовое снаряжение."""
    stats = creation.build_stats(cls, values or STANDARD, race, subrace)
    info = srd.RACES[race].get("subraces", {}).get(subrace, {})
    max_hp = rules.initial_max_hp(cls, rules.modifier(stats[srd.CON]), info.get("hp_per_level", 0))
    spells = creation.starting_spells(cls, 1, stats, race, subrace)
    base = dict(
        race=race, subrace=subrace, char_class=cls, background="Солдат",
        stats=stats, hp=max_hp, max_hp=max_hp,
        skills=creation.known_skills(race, subrace, "Солдат", skills or []),
        fighting_style=style,
        cantrips=spells["cantrips"], spellbook=spells["spellbook"], prepared=spells["prepared"],
    )
    base.update(fields)
    assert db.save_character(chat_id, user_id, "Игрок", name, "герой", **base)
    if gear:
        creation.give_gear(chat_id, user_id, cls, stats[srd.STR])
    if level > 1:
        c = db.get_character(chat_id, user_id)
        hp_gain = sum(rules.level_up_gains(c, lv)["hp"] for lv in range(2, level + 1))
        db.update_character(chat_id, user_id, level=level, xp=srd.XP_FOR_LEVEL[level - 1],
                            max_hp=max_hp + hp_gain, hp=max_hp + hp_gain)
    return db.get_character(chat_id, user_id)


def make_enemy(name: str = "Гоблин", hp: int = 7, ac: int = 12, attack: int = 2,
               damage: str = "1d6", cr: float = 0.25, chat_id: int = CHAT, **fields):
    return db.save_enemy(chat_id, name=name, hp=hp, armor_class=ac, attack_bonus=attack,
                         damage_dice=damage, cr=cr, xp=srd.CR_TABLE[cr][1], **fields)


def equip(user_id: int, name: str, chat_id: int = CHAT):
    """Даёт и надевает предмет из таблиц правил."""
    kind, value = rules.srd_item(name)
    item = db.add_item(chat_id, user_id, name, kind, value)
    db.equip_item(chat_id, user_id, item["id"], kind)
    return item


def unequip_all(user_id: int, chat_id: int = CHAT):
    for item in db.list_items(chat_id, user_id):
        db.unequip_item(item["id"])
