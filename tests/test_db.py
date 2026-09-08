import sqlite3

import db
from conftest import CHAT, GM, PLAYER, make_enemy, make_hero, make_world


def test_migration_keeps_old_campaign(tmp_path):
    """База первой версии (без hp, stats, kind…) открывается и дополняется без потери данных."""
    path = str(tmp_path / "old.db")
    c = sqlite3.connect(path)
    c.executescript(
        "CREATE TABLE games (chat_id INTEGER PRIMARY KEY, theme TEXT NOT NULL, world_desc TEXT NOT NULL);"
        "CREATE TABLE characters (id INTEGER PRIMARY KEY AUTOINCREMENT, chat_id INTEGER NOT NULL,"
        " user_id INTEGER NOT NULL, user_name TEXT NOT NULL, name TEXT NOT NULL,"
        " description TEXT NOT NULL, attributes TEXT NOT NULL,"
        " UNIQUE (chat_id, user_id), UNIQUE (chat_id, name));"
        "CREATE TABLE actions (id INTEGER PRIMARY KEY AUTOINCREMENT, chat_id INTEGER NOT NULL,"
        " after_situation INTEGER NOT NULL, character_name TEXT NOT NULL, text TEXT NOT NULL);"
    )
    c.execute("INSERT INTO games VALUES (1, 'старая', 'мир')")
    c.execute("INSERT INTO characters (chat_id,user_id,user_name,name,description,attributes)"
              " VALUES (1,10,'N','Гарен','воин','Сила, Воля')")
    c.execute("INSERT INTO actions (chat_id,after_situation,character_name,text) VALUES (1,0,'Гарен','идёт')")
    c.commit()
    c.close()

    db._conn = None
    db.DB_PATH = path
    game = db.get_world(1)
    assert game["theme"] == "старая" and game["gm_user_id"] is None and game["difficulty"] == "обычная"
    hero = db.get_character(1, 10)
    assert hero["name"] == "Гарен" and hero["hp"] == 20 and hero["level"] == 1 and hero["alive"] == 1
    assert hero["stats"] is None
    assert db.pending_actions(1)[0]["kind"] == "action"
    # Новые таблицы тоже появились
    assert db.list_enemies(1) == [] and db.get_combat(1) is None


def test_actions_are_scoped_to_scene():
    make_world()
    db.save_situation(CHAT, "сцена 1")
    db.save_action(CHAT, "Гарен", "иду", "action")
    db.save_action(CHAT, "Гарен", "бросок", "event")
    assert len(db.pending_actions(CHAT)) == 2
    assert len(db.pending_actions(CHAT, kind="action")) == 1
    db.save_situation(CHAT, "сцена 2")
    assert db.pending_actions(CHAT) == []


def test_hp_clamped_and_death_saves_reset():
    make_hero(max_hp=20)
    db.update_character(CHAT, PLAYER, death_failures=2)
    assert db.adjust_hp(CHAT, PLAYER, -50)["hp"] == 0
    assert db.get_character(CHAT, PLAYER)["death_failures"] == 2  # на нуле счётчики остаются
    healed = db.adjust_hp(CHAT, PLAYER, 5)
    assert healed["hp"] == 5 and healed["death_failures"] == 0
    assert db.adjust_hp(CHAT, PLAYER, 999)["hp"] == 20
    assert db.adjust_hp(CHAT, 99, -5) is None


def test_unique_character_per_player_and_name():
    make_hero(PLAYER, "Гарен")
    assert not db.save_character(CHAT, PLAYER, "Игрок", "Другой", "d", "Сила")
    assert not db.save_character(CHAT, 12, "Игрок2", "Гарен", "d", "Сила")
    assert db.save_character(CHAT, 12, "Игрок2", "Лира", "d", "Сила")


def test_find_helpers_are_prefix_and_case_insensitive():
    make_hero(PLAYER, "Гарен")
    make_enemy("Гоблин-шаман")
    assert db.find_character(CHAT, "гар")["name"] == "Гарен"
    assert db.find_enemy(CHAT, "ГОБ")["name"] == "Гоблин-шаман"
    assert db.find_enemy(CHAT, "дракон") is None


def test_items_equip_replaces_same_kind():
    make_hero()
    sword = db.add_item(CHAT, PLAYER, "Меч", "weapon", "1d8")
    axe = db.add_item(CHAT, PLAYER, "Топор", "weapon", "1d10")
    db.equip_item(CHAT, PLAYER, sword["id"], "weapon")
    db.equip_item(CHAT, PLAYER, axe["id"], "weapon")
    equipped = db.equipped_item(CHAT, PLAYER, "weapon")
    assert equipped["name"] == "Топор"
    db.delete_character(CHAT, PLAYER)
    assert db.list_items(CHAT, PLAYER) == []


def test_drafts_roundtrip():
    db.set_draft(CHAT, PLAYER, "attrs", ["Сила"], [])
    draft = db.get_draft(CHAT, PLAYER)
    assert draft["stage"] == "attrs" and draft["selected"] == ["Сила"]
    db.set_draft(CHAT, PLAYER, "pick", ["Сила"], [{"name": "X"}])
    assert db.get_draft(CHAT, PLAYER)["options"][0]["name"] == "X"
    db.delete_draft(CHAT, PLAYER)
    assert db.get_draft(CHAT, PLAYER) is None


def test_usage_and_reset():
    make_world()
    db.record_usage(CHAT, "scene", 1000, 200)
    db.record_usage(CHAT, "scene", 500, 100)
    totals = db.usage_totals(CHAT)
    assert totals["calls"] == 2 and totals["input_tokens"] == 1500
    make_hero()
    make_enemy()
    db.add_fact(CHAT, 1, "факт")
    db.reset_game(CHAT)
    assert db.get_world(CHAT) is None
    assert db.list_characters(CHAT) == [] and db.list_enemies(CHAT) == [] and db.list_facts(CHAT) == []


def test_backup_is_readable(tmp_path):
    make_world()
    make_hero()
    target = str(tmp_path / "copy.db")
    db.backup_to(target)
    copy = sqlite3.connect(target)
    assert copy.execute("SELECT COUNT(*) FROM characters").fetchone()[0] == 1
    copy.close()
