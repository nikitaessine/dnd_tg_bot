import dice
import rules
from config import ATTRIBUTES
from conftest import make_hero


def test_modifier_formula():
    assert rules.modifier(10) == 0
    assert rules.modifier(16) == 3
    assert rules.modifier(8) == -1
    assert rules.modifier(7) == -2


def test_proficiency_by_level():
    assert rules.proficiency(1) == 2
    assert rules.proficiency(4) == 2
    assert rules.proficiency(5) == 3
    assert rules.proficiency(9) == 4


def test_generate_stats_prefers_chosen():
    chosen = ["Сила", "Ловкость", "Телосложение", "Воля"]
    for _ in range(20):
        stats = rules.generate_stats(chosen)
        assert set(stats) == set(ATTRIBUTES)
        assert all(3 <= v <= 18 for v in stats.values())
        assert min(stats[a] for a in chosen) >= max(stats[a] for a in ATTRIBUTES if a not in chosen)


def test_check_bonus_uses_proficiency_only_for_chosen():
    hero = make_hero()
    bonus, prof = rules.check_bonus(hero, "Сила")
    assert (bonus, prof) == (3 + 2, True)
    bonus, prof = rules.check_bonus(hero, "Интеллект")
    assert (bonus, prof) == (0, False)


def test_stats_fallback_for_legacy_character():
    # Пустой словарь сохраняется как NULL — персонаж считается созданным до появления
    # числовых характеристик и получает 16 в выбранных атрибутах, 10 в остальных.
    hero = make_hero(stats={})
    assert hero["stats"] is None
    stats = rules.stats_of(hero)
    assert stats["Сила"] == 16 and stats["Интеллект"] == 10
    # Частично заполненный JSON дополняется значениями по умолчанию
    partial = dict(hero)
    partial["stats"] = '{"Сила": 12}'
    stats = rules.stats_of(partial)
    assert stats["Сила"] == 12 and stats["Интеллект"] == 10


def test_armor_class_and_attack():
    hero = make_hero()
    assert rules.armor_class(hero) == 13
    assert rules.armor_class(hero, armor_bonus=2) == 15
    bonus, attr = rules.attack_bonus(hero)
    assert bonus == 5 and attr == "Сила"


def test_weapon_damage_minimum_one():
    stats = {a: 3 for a in ATTRIBUTES}  # модификатор -4
    for _ in range(30):
        damage, _ = rules.weapon_damage("1d4", stats)
        assert damage >= 1


def test_apply_xp_levels_up_and_heals():
    hero = make_hero(max_hp=20)
    result = rules.apply_xp(hero, 250)  # 100 за 1→2, 200 за 2→3: хватает на один уровень
    assert result["level"] == 2 and result["xp"] == 150
    assert result["max_hp"] == 20 + 5 + 3  # HP_PER_LEVEL + мод. Телосложения (16 → +3)
    assert result["hp"] == result["max_hp"]
    assert result["gained"] == 1


def test_apply_xp_multiple_levels():
    hero = make_hero()
    result = rules.apply_xp(hero, 1000)
    assert result["level"] == 5  # 100 + 200 + 300 + 400 = 1000 — ровно четыре уровня
    assert result["xp"] == 0 and result["gained"] == 4


def test_death_save_outcomes(monkeypatch):
    hero = dict(make_hero())
    hero["death_successes"], hero["death_failures"] = 0, 2
    monkeypatch.setattr(dice, "d20", lambda: 5)
    assert rules.death_save(hero)["alive"] is False
    monkeypatch.setattr(dice, "d20", lambda: 20)
    r = rules.death_save(hero)
    assert r["revived"] and r["hp"] == 1
    hero["death_successes"], hero["death_failures"] = 2, 0
    monkeypatch.setattr(dice, "d20", lambda: 12)
    assert rules.death_save(hero)["stable"] is True


def test_dice_notation():
    assert dice.parse_notation("2d6") == (2, 6, 0)
    assert dice.parse_notation("d20") == (1, 20, 0)
    assert dice.parse_notation("1d8+3") == (1, 8, 3)
    assert dice.parse_notation("2d4-1") == (2, 4, -1)
    assert dice.parse_notation("Сила") is None
    assert dice.parse_notation("999d6") is None
    assert dice.parse_notation("2d1") is None
    total, results, mod = dice.roll_notation("2d6+1")
    assert total == sum(results) + 1 and mod == 1 and len(results) == 2
    total, results, _ = dice.roll_notation("1d6", double_dice=True)
    assert len(results) == 2


def test_match_attribute():
    assert dice.match_attribute("сила", ATTRIBUTES) == "Сила"
    assert dice.match_attribute("ЛОВ", ATTRIBUTES) == "Ловкость"
    assert dice.match_attribute("xyz", ATTRIBUTES) is None
    assert dice.match_attribute("", ATTRIBUTES) is None
