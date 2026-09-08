import combat
import db
import dice
from conftest import CHAT, PLAYER, make_enemy, make_hero, make_world


def test_initiative_order_players_win_ties(monkeypatch):
    make_world()
    make_hero(PLAYER, "Гарен")
    make_enemy("Гоблин")
    monkeypatch.setattr(dice, "d20", lambda: 10)
    order = combat.start(CHAT)
    # Гарен: 10 + мод. Ловкости 16 (+3) = 13; Гоблин: 10 + 0 = 10
    assert [a["name"] for a in order] == ["Гарен", "Гоблин"]
    assert combat.current_actor(CHAT)["name"] == "Гарен"
    combat.advance(CHAT)
    assert combat.current_actor(CHAT)["name"] == "Гоблин"
    combat.advance(CHAT)
    state = db.get_combat(CHAT)
    assert state["round"] == 2 and state["turn_index"] == 0


def test_player_attack_hit_and_defeat(monkeypatch):
    make_world()
    hero = make_hero()
    enemy = make_enemy(hp=3, ac=10)
    monkeypatch.setattr(dice, "d20", lambda: 15)
    lines, defeated = combat.player_attack(CHAT, hero, enemy)
    assert defeated and db.get_enemy(enemy["id"])["alive"] == 0
    assert any("повержен" in line for line in lines)
    events = [a["text"] for a in db.pending_actions(CHAT, kind="event")]
    assert any("побеждает Гоблин" in e for e in events)


def test_player_attack_miss_on_natural_one(monkeypatch):
    make_world()
    hero = make_hero()
    enemy = make_enemy(hp=10, ac=5)
    monkeypatch.setattr(dice, "d20", lambda: 1)
    lines, defeated = combat.player_attack(CHAT, hero, enemy)
    assert not defeated and db.get_enemy(enemy["id"])["hp"] == 10
    assert any("промах" in line.lower() for line in lines)


def test_equipped_weapon_is_used(monkeypatch):
    make_world()
    hero = make_hero()
    item = db.add_item(CHAT, PLAYER, "Меч", "weapon", "1d8")
    db.equip_item(CHAT, PLAYER, item["id"], "weapon")
    enemy = make_enemy(hp=50, ac=5)
    monkeypatch.setattr(dice, "d20", lambda: 15)
    lines, _ = combat.player_attack(CHAT, hero, enemy)
    assert "Меч" in lines[0] and "1d8" in lines[1]


def test_enemy_attack_reduces_hp_and_logs(monkeypatch):
    make_world()
    hero = make_hero(max_hp=20)
    enemy = make_enemy(attack=5, damage="1d6")
    monkeypatch.setattr(dice, "d20", lambda: 18)
    monkeypatch.setattr(dice, "roll", lambda count, sides: [4] * count)
    combat.enemy_attack(CHAT, enemy, hero)
    assert db.get_character(CHAT, PLAYER)["hp"] == 16
    assert any("наносит Гарен 4 урона" in a["text"] for a in db.pending_actions(CHAT, kind="event"))


def test_award_xp_levels_up():
    make_world()
    make_hero()
    enemy = make_enemy(xp=120)
    lines = combat.award_xp(CHAT, enemy)
    hero = db.get_character(CHAT, PLAYER)
    assert hero["level"] == 2 and hero["xp"] == 20
    assert any("2 уровня" in line for line in lines)


def test_run_until_player_ends_on_victory(monkeypatch):
    make_world()
    make_hero()
    enemy = make_enemy(hp=1)
    monkeypatch.setattr(dice, "d20", lambda: 10)
    combat.start(CHAT)
    db.update_enemy(enemy["id"], hp=0, alive=0)
    lines, over = combat.run_until_player(CHAT)
    assert over and db.get_combat(CHAT) is None
    assert any("Бой окончен" in line for line in lines)
    assert db.list_enemies(CHAT, alive_only=False) == []  # трупы убраны


def test_run_until_player_processes_enemy_turn_then_stops_at_player(monkeypatch):
    make_world()
    make_hero(max_hp=20)
    make_enemy(attack=0, damage="1d4")
    # Инициатива: гоблин первый (игрок бросает 1, гоблин 20)
    rolls = iter([1, 20])
    monkeypatch.setattr(dice, "d20", lambda: next(rolls))
    combat.start(CHAT)
    assert combat.current_actor(CHAT)["type"] == "enemy"
    # Ход гоблина: атака d20=18 попадает (КД 13), урон 1d4 → 2
    monkeypatch.setattr(dice, "d20", lambda: 18)
    monkeypatch.setattr(dice, "roll", lambda count, sides: [2] * count)
    lines, over = combat.run_until_player(CHAT)
    assert not over
    assert db.get_character(CHAT, PLAYER)["hp"] == 18
    assert combat.current_actor(CHAT)["type"] == "pc"
    assert any("ход Гарен" in line for line in lines)


def test_unconscious_player_rolls_death_save_and_can_die(monkeypatch):
    make_world()
    make_hero(PLAYER, "Гарен")
    make_hero(12, "Лира")
    make_enemy(attack=-20)  # гоблин никогда не попадает
    rolls = iter([20, 5, 1])  # Гарен → Лира → гоблин
    monkeypatch.setattr(dice, "d20", lambda: next(rolls))
    combat.start(CHAT)
    db.update_character(CHAT, PLAYER, hp=0, death_failures=2)
    monkeypatch.setattr(dice, "d20", lambda: 3)  # провал спасброска
    lines, over = combat.run_until_player(CHAT)
    assert db.get_character(CHAT, PLAYER)["alive"] == 0
    assert any("погибает" in line for line in lines)
    assert not over  # Лира в сознании — бой продолжается, её ход
    assert combat.current_actor(CHAT)["name"] == "Лира"


def test_combat_ends_when_whole_party_is_down(monkeypatch):
    make_world()
    make_hero()
    make_enemy()
    monkeypatch.setattr(dice, "d20", lambda: 10)
    combat.start(CHAT)
    db.update_character(CHAT, PLAYER, hp=0)
    lines, over = combat.run_until_player(CHAT)
    assert over and db.get_combat(CHAT) is None
    assert any("Бой окончен" in line for line in lines)
    assert db.get_character(CHAT, PLAYER)["alive"] == 1  # без сознания, но жив


def test_end_combat_clears_state():
    make_world()
    make_hero()
    make_enemy()
    combat.start(CHAT)
    combat.end(CHAT, "тест")
    assert db.get_combat(CHAT) is None
