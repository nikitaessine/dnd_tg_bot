"""Общая подготовка: переменные окружения-заглушки и чистая база на каждый тест."""

import os
import sys
import tempfile

os.environ.setdefault("BOT_TOKEN", "123:test")
os.environ.setdefault("ANTHROPIC_API_KEY", "sk-test")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest  # noqa: E402

import db  # noqa: E402


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


def make_world(chat_id: int = CHAT, gm: int = GM):
    db.set_world(chat_id, "тест", "тестовый мир", gm)
    return db.get_world(chat_id)


def make_hero(user_id: int = PLAYER, name: str = "Гарен", chosen=("Сила", "Ловкость", "Телосложение", "Воля"),
              stats=None, max_hp: int = 20, chat_id: int = CHAT):
    if stats is None:
        stats = {a: (16 if a in chosen else 10) for a in
                 ["Сила", "Ловкость", "Телосложение", "Интеллект", "Мудрость", "Харизма", "Удача", "Воля"]}
    assert db.save_character(chat_id, user_id, "Игрок", name, "воин", ", ".join(chosen), stats, max_hp)
    return db.get_character(chat_id, user_id)


def make_enemy(name: str = "Гоблин", hp: int = 7, ac: int = 12, attack: int = 2,
               damage: str = "1d6", xp: int = 30, chat_id: int = CHAT):
    return db.save_enemy(chat_id, name=name, hp=hp, armor_class=ac, attack_bonus=attack,
                         damage_dice=damage, xp=xp)
