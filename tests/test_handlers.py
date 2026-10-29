"""Проверки слоя Telegram без сети: разбор команд, клавиатуры, лист персонажа."""

import re

import pytest

import combat
import db
import items
import rules
import srd
from handlers import checks, fight, hero, magic, story, turns
from handlers.common import split_text
from tests.conftest import CHAT, make_enemy, make_hero, make_world


def all_commands() -> list[str]:
    import bot
    routers = [m.router for m in (checks, fight, hero, magic, story)]
    from handlers import items as items_h, setup
    routers += [items_h.router, setup.router]
    names = []
    for r in routers:
        for h in r.message.handlers:
            for f in h.filters:
                cmds = getattr(f.callback, "commands", None)
                if cmds:
                    names += [c if isinstance(c, str) else c.pattern for c in cmds]
    return names


def test_no_duplicate_commands():
    names = all_commands()
    assert len(names) == len(set(names)), sorted(n for n in names if names.count(n) > 1)
    for needed in ("hero", "sheet", "roll", "attack", "cast", "take", "fight", "rest", "asi"):
        assert needed in names


def test_split_text():
    parts = split_text("абв\n\n" * 3000, 4000)
    assert all(len(p) <= 4000 for p in parts) and len(parts) > 1


def test_parse_check():
    assert checks.parse_check("Ловкость 15 помеха") == ("Ловкость", 15, -1, "")
    name, dc, mode, _ = checks.parse_check("скрыт 12")
    assert (name, dc, mode) == ("Скрытность", 12, 0)
    assert checks.parse_check("абракадабра")[0] is None


def test_parse_cast():
    known = ["Огненный шар", "Волшебная стрела"]
    assert magic.parse_cast("Огненный шар 3 Гоблин 2, Орк", known) == ("Огненный шар", 3, ["Гоблин 2", "Орк"])
    assert magic.parse_cast("волшебная стрела", known) == ("Волшебная стрела", None, [])
    assert magic.parse_cast("ерунда", known)[0] is None


def test_parse_manual_enemy():
    e = fight.parse_manual_enemy("Тёмный гоблин 7 13 +3 1d6")
    assert e["name"] == "Тёмный гоблин" and e["hp"] == 7 and e["armor_class"] == 13 and e["attack_bonus"] == 3
    assert fight.parse_manual_enemy("гоблин просто злой") is None


def test_parse_take():
    assert items.parse_take("Длинный меч")[:2] == ("Длинный меч", "weapon")
    name, kind, value = items.parse_take("Кольчуга +1")
    assert kind == "armor" and value["bonus"] == 1
    name, kind, value = items.parse_take("Щит +1")
    assert kind == "shield" and value["bonus"] == srd.SHIELD_AC + 1
    name, kind, value = items.parse_take("Меч пламени | Длинный меч +2")
    assert name == "Меч пламени" and value["bonus"] == 2
    assert items.parse_take("Нож 1d4")[1] == "weapon"
    assert items.parse_take("Верёвка") == ("Верёвка", "item", "")


@pytest.mark.parametrize("cls", ["Воин", "Плут", "Жрец", "Волшебник"])
def test_sheet_and_keyboard(cls):
    make_world()
    make_hero(1, "Герой", cls, level=3)
    character = db.get_character(CHAT, 1)
    text = hero.sheet_text(CHAT, character)
    assert "Герой" in text and "КД" in text
    make_enemy()
    combat.start(CHAT)
    kb = turns.turn_keyboard(CHAT, character)
    for row in kb.inline_keyboard:
        for b in row:
            assert len(b.callback_data.encode()) <= 64


def test_creation_views_within_limits():
    make_world()
    data = {"race": "Эльф", "subrace": "Высший эльф", "cls": "Плут", "bg": "Преступник",
            "values": list(srd.STANDARD_ARRAY), "skills": []}
    for stage in ("race", "subrace", "class", "bg", "method", "skills", "expertise", "style"):
        options = hero._stage_options(data, stage)
        text, markup = hero.stage_view(CHAT, 1, data, stage, options)
        assert text
        for row in markup.inline_keyboard:
            for b in row:
                assert len(b.callback_data.encode()) <= 64
                assert re.match(r"^hc:\d+:[a-z]+:[\w]+$", b.callback_data)


# ---------------------------------------------------------------- тайные противники и NPC мастера

GROUP = -100


def test_hidden_enemies_wait_and_block_auto_encounter():
    import asyncio
    import ai
    make_world(GROUP)
    assert db.gm_group_chat(10) == GROUP and db.gm_group_chat(11) is None
    make_enemy("Тролль", hp=30, chat_id=GROUP, hidden=1)
    make_enemy("Тролль", hp=30, chat_id=GROUP, hidden=1)
    assert db.list_enemies(GROUP) == []                       # игроки их не видят
    assert [e["name"] for e in db.list_enemies(GROUP, hidden=True)] == ["Тролль", "Тролль 2"]
    game = db.get_world(GROUP)
    scene = ai.SceneResult(text="", location="", new_facts=[], checks=[], new_enemy="Гоблин 7 13 +3 1d6")
    # пока тролли ждут, своего противника модель не добавляет
    assert asyncio.run(story._scene_enemies(None, GROUP, game, scene)) == []
    scene.gm_enemies_appear = True
    assert len(asyncio.run(story._scene_enemies(None, GROUP, game, scene))) == 2
    assert len(db.list_enemies(GROUP)) == 2 and db.list_enemies(GROUP, hidden=True) == []
    # тролли уже здесь — новых тоже нет
    assert asyncio.run(story._scene_enemies(None, GROUP, game, scene)) == []
    for e in db.list_enemies(GROUP):
        db.update_enemy(e["id"], alive=0)
    scene.new_enemy_count = 2
    assert [e["name"] for e in asyncio.run(story._scene_enemies(None, GROUP, game, scene))] == ["Гоблин", "Гоблин 2"]


def test_hidden_npc_revealed_by_name():
    make_world(GROUP)
    db.save_npc(GROUP, "Мира", "Мира — травница", hidden=True)
    assert db.list_npcs(GROUP) == []
    db.reveal_npcs(GROUP, ["Мира"])
    assert [n["name"] for n in db.list_npcs(GROUP)] == ["Мира"]
