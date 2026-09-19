"""Правила: формулы, таблицы и производные величины — сверка с Basic Rules."""

import pytest

import db
import dice
import rules
import srd
from conftest import CHAT, PLAYER, equip, make_enemy, make_hero, make_world, unequip_all


# ---------------------------------------------------------------- базовые формулы (с. 9, 12, 60)

def test_modifier_table_matches_rulebook():
    expected = {1: -5, 2: -4, 3: -4, 4: -3, 5: -3, 6: -2, 7: -2, 8: -1, 9: -1, 10: 0, 11: 0, 12: 1, 13: 1,
                14: 2, 15: 2, 16: 3, 17: 3, 18: 4, 19: 4, 20: 5, 21: 5, 22: 6, 24: 7, 26: 8, 28: 9, 30: 10}
    for score, mod in expected.items():
        assert rules.modifier(score) == mod, score


def test_proficiency_bonus_by_level():
    expected = [2, 2, 2, 2, 3, 3, 3, 3, 4, 4, 4, 4, 5, 5, 5, 5, 6, 6, 6, 6]
    assert [rules.proficiency(lv) for lv in range(1, 21)] == expected


def test_xp_table_matches_rulebook():
    assert srd.XP_FOR_LEVEL == [0, 300, 900, 2700, 6500, 14000, 23000, 34000, 48000, 64000, 85000, 100000,
                                120000, 140000, 165000, 195000, 225000, 265000, 305000, 355000]
    assert rules.level_for_xp(0) == 1
    assert rules.level_for_xp(299) == 1
    assert rules.level_for_xp(300) == 2
    assert rules.level_for_xp(6500) == 5
    assert rules.level_for_xp(999999) == 20


def test_only_six_abilities():
    assert srd.ABILITIES == ["Сила", "Ловкость", "Телосложение", "Интеллект", "Мудрость", "Харизма"]
    assert len(srd.SKILLS) == 18
    assert set(srd.SKILLS.values()) <= set(srd.ABILITIES)


# ---------------------------------------------------------------- раса и создание

def test_racial_bonuses():
    assert rules.racial_bonuses("Дварф", "Холмовой") == {"Телосложение": 2, "Мудрость": 1}
    assert rules.racial_bonuses("Дварф", "Горный") == {"Телосложение": 2, "Сила": 2}
    assert rules.racial_bonuses("Эльф", "Высший") == {"Ловкость": 2, "Интеллект": 1}
    assert rules.racial_bonuses("Полурослик", "Крепкий") == {"Ловкость": 2, "Телосложение": 1}
    assert rules.racial_bonuses("Человек", "") == {a: 1 for a in srd.ABILITIES}


def test_stat_assignment_follows_class_priority():
    stats = rules.assign_stats("Воин", [8, 10, 12, 13, 14, 15])
    assert stats["Сила"] == 15 and stats["Телосложение"] == 14
    stats = rules.assign_stats("Волшебник", [8, 10, 12, 13, 14, 15])
    assert stats["Интеллект"] == 15 and stats["Телосложение"] == 14


def test_first_level_hit_points_are_max_hit_die_plus_con():
    # Пример из правил (с. 9): Брюнор, дварф-воин, ТЕЛ 16 → 10 + 3 = 13
    assert rules.initial_max_hp("Воин", 3) == 13
    assert rules.initial_max_hp("Волшебник", 1) == 7   # 6 + 1
    assert rules.initial_max_hp("Жрец", 0) == 8
    assert rules.initial_max_hp("Плут", 2) == 10
    assert rules.initial_max_hp("Воин", 2, hp_per_level=1) == 13  # холмовой дварф


def test_hp_per_level_uses_average_die():
    # d6→4, d8→5, d10→6 (с. 12) + мод. ТЕЛ, минимум 1
    assert rules.hp_per_level_gain("Волшебник", 0) == 4
    assert rules.hp_per_level_gain("Жрец", 2) == 7
    assert rules.hp_per_level_gain("Воин", 3) == 9
    assert rules.hp_per_level_gain("Волшебник", -3) == 1


def test_hill_dwarf_toughness_adds_hp_each_level():
    hero = make_hero(race="Дварф", subrace="Холмовой")
    # набор 15/14/13/12/10/8 → Воин: СИЛ15 ТЕЛ14(+2 дварф = 16) → мод +3; хиты 10 + 3 + 1
    assert hero["max_hp"] == 14
    assert rules.hp_per_level_gain("Воин", 3, hp_per_level=1) == 10


def test_con_increase_recomputes_hp_retroactively():
    assert rules.con_change_hp(level=8, old_score=17, new_score=18) == 8  # пример правил: +1 мод × 8 уровней
    assert rules.con_change_hp(level=3, old_score=14, new_score=15) == 0


# ---------------------------------------------------------------- навыки и спасброски (с. 60–65)

def test_skill_bonus_with_proficiency_and_expertise():
    hero = make_hero(cls="Плут", skills=["Скрытность", "Восприятие"], expertise=["Скрытность"])
    # Плут (человек): ЛОВ 16 → +3; Скрытность с компетентностью: +3 + 2×2 = +7; Восприятие: МДР 11 → 0 + 2
    assert rules.check_bonus(hero, "Скрытность") == (7, 2, "Ловкость")
    assert rules.check_bonus(hero, "Восприятие")[0] == 2
    assert rules.check_bonus(hero, "Атлетика")[0] == rules.mod_of(hero, "Сила") + 2  # фон Солдат: мастерство


def test_save_proficiencies_by_class():
    assert rules.save_proficiencies(make_hero(cls="Воин")) == {"Сила", "Телосложение"}
    assert rules.save_proficiencies(make_hero(user_id=12, name="Б", cls="Волшебник")) == {"Интеллект", "Мудрость"}
    hero = make_hero(user_id=13, name="В", cls="Плут", level=15)
    assert "Мудрость" in rules.save_proficiencies(hero)  # Скользкий ум


def test_reliable_talent_only_from_level_11_on_proficient_skills():
    rogue = make_hero(cls="Плут", level=11)
    assert rules.reliable_talent_floor(rogue, 1) == 10
    assert rules.reliable_talent_floor(rogue, 0) is None
    assert rules.reliable_talent_floor(make_hero(user_id=12, name="Б", cls="Плут", level=10), 1) is None


def test_remarkable_athlete_adds_half_proficiency_rounded_up():
    fighter = make_hero(level=7)
    bonus, level, ability = rules.check_bonus(fighter, "Сила")
    assert bonus == rules.mod_of(fighter, "Сила") + 2  # +3 мастерство на 7 ур., половина вверх = 2
    assert rules.check_bonus(fighter, "Интеллект")[0] == rules.mod_of(fighter, "Интеллект")


def test_advantage_and_disadvantage_cancel():
    assert rules.combine_mode(["a"], []) == (1, "a")
    assert rules.combine_mode([], ["b"]) == (-1, "b")
    assert rules.combine_mode(["a", "a2"], ["b"]) == (0, "")


def test_roll_d20_advantage_takes_higher_and_lucky_rerolls_ones(monkeypatch):
    seq = iter([3, 17])
    monkeypatch.setattr(dice, "d20", lambda: next(seq))
    assert dice.roll_d20(1)[0] == 17
    seq = iter([15, 4])
    monkeypatch.setattr(dice, "d20", lambda: next(seq))
    assert dice.roll_d20(-1)[0] == 4
    seq = iter([1, 12])  # полурослик: 1 перебрасывается, новый результат обязателен
    monkeypatch.setattr(dice, "d20", lambda: next(seq))
    assert dice.roll_d20(0, lucky=True)[0] == 12
    seq = iter([5])
    monkeypatch.setattr(dice, "d20", lambda: next(seq))
    assert dice.roll_d20(0, floor=10)[0] == 10  # Надёжный талант


# ---------------------------------------------------------------- доспехи и оружие (с. 46–48, 63, 76)

def test_armor_class_by_category():
    make_world()
    hero = make_hero(cls="Плут")          # ЛОВ 16 → +3
    unequip_all(PLAYER)
    assert rules.armor_class(hero)[0] == 13                      # без доспеха 10 + ЛОВ
    leather = rules.armor_info(equip(PLAYER, "Кожаный доспех"))
    assert rules.armor_class(hero, leather)[0] == 14             # 11 + ЛОВ
    scale = {"name": "Чешуйчатый", "base": 14, "cat": "medium", "str": 0, "stealth": True, "bonus": 0}
    assert rules.armor_class(hero, scale)[0] == 16               # 14 + ЛОВ (макс. +2) = 16
    hero_dex4 = dict(hero)
    hero_dex4["stats"] = '{"Сила": 10, "Ловкость": 18, "Телосложение": 10, "Интеллект": 10, "Мудрость": 10, "Харизма": 10}'
    assert rules.armor_class(hero_dex4, scale)[0] == 16          # ЛОВ +4, но лимит +2
    plate = {"name": "Латы", "base": 18, "cat": "heavy", "str": 15, "stealth": True, "bonus": 0}
    assert rules.armor_class(hero_dex4, plate)[0] == 18          # тяжёлый доспех не добавляет ЛОВ
    shield = {"name": "Щит", "kind": "shield", "value": '{"bonus": 2}'}
    assert rules.armor_class(hero_dex4, plate, shield)[0] == 20


def test_example_from_rulebook_bruenor_ac18():
    # Брюнор: кольчуга (16) + щит (+2) = 18 (с. 11)
    make_world()
    hero = make_hero(race="Дварф", subrace="Горный")
    g = __import__("engine").gear(CHAT, hero)
    assert g["ac"] == 18


def test_mage_armor_shield_and_haste_stack_on_ac():
    hero = make_hero(cls="Волшебник")     # ЛОВ 14 → +2
    base = rules.armor_class(hero, None, None, [])[0]
    assert base == 12
    conds = rules.add_condition([], "доспехи мага")
    assert rules.armor_class(hero, None, None, conds)[0] == 15   # 13 + ЛОВ
    conds = rules.add_condition(conds, "щит")
    assert rules.armor_class(hero, None, None, conds)[0] == 20   # +5
    conds = rules.add_condition(conds, "щит веры")
    assert rules.armor_class(hero, None, None, conds)[0] == 22


def test_defense_style_only_with_armor():
    hero = make_hero(style="Оборона")
    armor = {"name": "Кольчуга", "base": 16, "cat": "heavy", "str": 13, "stealth": True, "bonus": 0}
    assert rules.armor_class(hero, armor)[0] == 17
    assert rules.armor_class(hero, None)[0] == 12  # ЛОВ 14 → +2


def test_armor_proficiency_penalties():
    wizard = make_hero(cls="Волшебник", gear=False)
    plate = {"name": "Латы", "base": 18, "cat": "heavy", "str": 15, "stealth": True, "bonus": 0}
    assert rules.armor_penalties(wizard, plate, None)["nonproficient"] is True
    cleric = make_hero(user_id=12, name="Б", cls="Жрец", gear=False)
    assert rules.armor_penalties(cleric, plate, None)["nonproficient"] is False   # домен Жизни
    weak = dict(cleric)
    weak["stats"] = '{"Сила": 10, "Ловкость": 10, "Телосложение": 10, "Интеллект": 10, "Мудрость": 10, "Харизма": 10}'
    assert rules.armor_penalties(weak, plate, None)["str_penalty"] is True
    assert rules.speed_of(weak, rules.armor_penalties(weak, plate, None)) == 20


def test_attack_ability_by_weapon_type():
    make_world()
    rogue = make_hero(cls="Плут")         # ЛОВ 16(+3), СИЛ 9(−1)
    rapier = {"name": "Рапира", "kind": "weapon", "value": ""}
    profile = rules.attack_profile(rogue, rapier)
    assert profile["ability"] == "Ловкость" and profile["attack"] == 3 + 2
    club = {"name": "Дубинка", "kind": "weapon", "value": ""}
    assert rules.attack_profile(rogue, club)["ability"] == "Сила"   # без finesse — Сила
    bow = {"name": "Короткий лук", "kind": "weapon", "value": ""}
    assert rules.attack_profile(rogue, bow)["ability"] == "Ловкость"
    fighter = make_hero(user_id=12, name="Б")
    lsword = {"name": "Длинный меч", "kind": "weapon", "value": ""}
    assert rules.attack_profile(fighter, lsword)["ability"] == "Сила"
    crossbow = {"name": "Лёгкий арбалет", "kind": "weapon", "value": ""}
    assert rules.attack_profile(fighter, crossbow)["ability"] == "Ловкость"  # дальнобойное — Ловкость


def test_example_from_rulebook_battleaxe_attack_bonus():
    # Брюнор: Сила 17 (+3), мастерство +2 → +5; топор 1d8 + 3 (с. 11)
    hero = make_hero(race="Дварф", subrace="Горный")
    axe = {"name": "Боевой топор", "kind": "weapon", "value": ""}
    shield = {"name": "Щит", "kind": "shield", "value": '{"bonus": 2}'}
    p = rules.attack_profile(hero, axe, shield)
    assert p["attack"] == 5 and p["damage_bonus"] == 3
    assert p["damage_dice"] == "1d8"                       # со щитом — одной рукой
    assert rules.attack_profile(hero, axe, None)["damage_dice"] == "1d10"   # универсальное двумя руками


def test_weapon_proficiency_rules():
    wizard = make_hero(cls="Волшебник", gear=False)
    assert rules.weapon_proficient(wizard, rules.weapon_info({"name": "Кинжал", "kind": "weapon", "value": ""}))
    assert not rules.weapon_proficient(wizard, rules.weapon_info({"name": "Длинный меч", "kind": "weapon", "value": ""}))
    cleric = make_hero(user_id=12, name="Б", cls="Жрец", gear=False)
    assert not rules.weapon_proficient(cleric, rules.weapon_info({"name": "Длинный меч", "kind": "weapon", "value": ""}))
    elf = make_hero(user_id=13, name="В", cls="Жрец", race="Эльф", subrace="Лесной", gear=False)
    assert rules.weapon_proficient(elf, rules.weapon_info({"name": "Длинный меч", "kind": "weapon", "value": ""}))
    rogue = make_hero(user_id=14, name="Г", cls="Плут", gear=False)
    assert rules.weapon_proficient(rogue, rules.weapon_info({"name": "Рапира", "kind": "weapon", "value": ""}))
    assert not rules.weapon_proficient(rogue, rules.weapon_info({"name": "Длинный лук", "kind": "weapon", "value": ""}))


def test_unproficient_weapon_gets_no_proficiency_bonus():
    wizard = make_hero(cls="Волшебник", gear=False)    # СИЛ 9 → −1
    sword = {"name": "Длинный меч", "kind": "weapon", "value": ""}
    assert rules.attack_profile(wizard, sword)["attack"] == -1     # мастерства нет (с. 47)
    dagger = {"name": "Кинжал", "kind": "weapon", "value": ""}
    assert rules.attack_profile(wizard, dagger)["attack"] == 2 + 2  # финес: ЛОВ 14 → +2, мастерство +2


def test_unarmed_strike_is_one_plus_strength():
    fighter = make_hero()
    p = rules.attack_profile(fighter, None)
    assert p["weapon"]["unarmed"] and p["damage_dice"] == "1"
    assert p["attack"] == rules.mod_of(fighter, "Сила") + 2


def test_fighting_styles():
    fighter = make_hero(style="Стрельба")
    bow = {"name": "Длинный лук", "kind": "weapon", "value": ""}
    plain = make_hero(user_id=12, name="Б")
    assert rules.attack_profile(fighter, bow)["attack"] == rules.attack_profile(plain, bow)["attack"] + 2
    dueling = make_hero(user_id=13, name="В", style="Дуэль")
    sword = {"name": "Длинный меч", "kind": "weapon", "value": ""}
    shield = {"name": "Щит", "kind": "shield", "value": '{"bonus": 2}'}
    assert rules.attack_profile(dueling, sword, shield)["damage_bonus"] == rules.mod_of(dueling, "Сила") + 2
    assert rules.attack_profile(dueling, sword, None)["damage_bonus"] == rules.mod_of(dueling, "Сила")  # двумя руками
    gwf = make_hero(user_id=14, name="Г", style="Бой большим оружием")
    greatsword = {"name": "Двуручный меч", "kind": "weapon", "value": ""}
    assert rules.attack_profile(gwf, greatsword)["great_weapon"] is True
    assert rules.attack_profile(gwf, sword, shield)["great_weapon"] is False


def test_champion_critical_range():
    assert rules.crit_range(make_hero(level=1)) == 20
    assert rules.crit_range(make_hero(user_id=12, name="Б", level=3)) == 19
    assert rules.crit_range(make_hero(user_id=13, name="В", level=15)) == 18
    assert rules.crit_range(make_hero(user_id=14, name="Г", cls="Плут", level=15)) == 20


def test_extra_attacks_and_sneak_dice():
    assert [srd.extra_attacks(lv) for lv in (1, 4, 5, 10, 11, 19, 20)] == [1, 1, 2, 2, 3, 3, 4]
    assert [srd.sneak_attack_dice(lv) for lv in (1, 2, 3, 5, 9, 19, 20)] == [1, 1, 2, 3, 5, 10, 10]
    assert rules.attacks_per_action(make_hero(level=5)) == 2
    assert rules.attacks_per_action(make_hero(user_id=12, name="Б", cls="Плут", level=5)) == 1


# ---------------------------------------------------------------- здоровье, смерть (с. 77–79)

def test_damage_reduces_temp_hp_first():
    out = rules.damage_outcome(hp=10, max_hp=10, temp_hp=5, amount=7)
    assert out["temp_hp"] == 0 and out["hp"] == 8 and out["absorbed"] == 5
    # Пример из правил: 5 временных, урон 7 → 2 урона по хитам


def test_drop_to_zero_and_instant_death():
    out = rules.damage_outcome(hp=6, max_hp=12, temp_hp=0, amount=10)
    assert out["hp"] == 0 and out["dropped"] and not out["instant_death"]
    # Пример из правил: жрец, максимум 12, хитов 6, урон 18 → остаток 12 = максимум → мгновенная смерть
    out = rules.damage_outcome(hp=6, max_hp=12, temp_hp=0, amount=18)
    assert out["instant_death"]


def test_damage_at_zero_hp_is_a_death_save_failure():
    out = rules.damage_outcome(hp=0, max_hp=20, temp_hp=0, amount=3)
    assert out["death_failures"] == 1 and out["hp"] == 0
    out = rules.damage_outcome(hp=0, max_hp=20, temp_hp=0, amount=3, crit=True)
    assert out["death_failures"] == 2
    out = rules.damage_outcome(hp=0, max_hp=20, temp_hp=0, amount=20)
    assert out["instant_death"]


def test_death_save_outcomes(monkeypatch):
    monkeypatch.setattr(dice, "d20", lambda: 1)
    r = rules.death_save(0, 1)
    assert r["failures"] == 3 and r["dead"]                 # 1 = два провала
    monkeypatch.setattr(dice, "d20", lambda: 20)
    r = rules.death_save(0, 2)
    assert r["revived"] and r["successes"] == 0 and r["failures"] == 0
    monkeypatch.setattr(dice, "d20", lambda: 10)
    assert rules.death_save(2, 0)["stable"]
    monkeypatch.setattr(dice, "d20", lambda: 9)
    r = rules.death_save(0, 0)
    assert r["failures"] == 1 and not r["dead"]


def test_concentration_dc():
    assert rules.concentration_dc(4) == 10
    assert rules.concentration_dc(30) == 15


# ---------------------------------------------------------------- опыт и уровни

def test_apply_xp_levels_up_by_table():
    hero = make_hero()
    result = rules.apply_xp(hero, 300)
    assert result["level"] == 2 and result["xp"] == 300 and result["gained"] == 1
    # Воин: среднее d10 = 6, ТЕЛ 14 (+2) → +8 хитов; текущее растёт на столько же
    assert result["hp_gain"] == 8 and result["max_hp"] == hero["max_hp"] + 8
    assert result["hp"] == hero["hp"] + 8


def test_multiple_levels_and_asi_schedule():
    hero = make_hero()
    result = rules.apply_xp(hero, 6500)
    assert result["level"] == 5 and result["gained"] == 4
    assert result["asi"] == 1                                # воин: ASI на 4 (следующий на 6)
    assert any("Дополнительная атака" in f for f in result["features"])
    fighter_asi = srd.ASI_LEVELS["Воин"]
    assert fighter_asi == [4, 6, 8, 12, 14, 16, 19]
    assert srd.ASI_LEVELS["Плут"] == [4, 8, 10, 12, 16, 19]


def test_wizard_learns_two_spells_per_level_and_cantrips_at_4_and_10():
    wiz = make_hero(cls="Волшебник")
    result = rules.apply_xp(wiz, 2700)                       # уровень 4
    assert result["learn"] == 6 and result["cantrips"] == 1
    assert rules.apply_xp(wiz, 85000)["cantrips"] == 2       # 4-й и 10-й


def test_rogue_expertise_at_level_6():
    rogue = make_hero(cls="Плут")
    assert rules.apply_xp(rogue, 14000)["expertise"] == 2
    assert rules.apply_xp(rogue, 6500)["expertise"] == 0


# ---------------------------------------------------------------- магия

def test_spell_slot_table():
    wiz = make_hero(cls="Волшебник")
    assert rules.slots_total(wiz) == [2]
    assert srd.SPELL_SLOTS[3] == [4, 2] and srd.SPELL_SLOTS[5] == [4, 3, 2] and srd.SPELL_SLOTS[20] == [4, 3, 3, 3, 3, 2, 2, 1, 1]
    assert rules.slots_total(make_hero(user_id=12, name="Б")) == []      # воин не колдует


def test_cantrips_known_and_scaling():
    assert [srd.cantrips_known(lv) for lv in (1, 3, 4, 9, 10)] == [3, 3, 4, 4, 5]
    assert [rules.cantrip_multiplier(lv) for lv in (1, 4, 5, 10, 11, 16, 17)] == [1, 1, 2, 2, 3, 3, 4]
    assert rules.scale_dice("1d10", 3) == "3d10"
    assert rules.add_dice("3d6", "1d6", 2) == "5d6"


def test_spell_dc_and_attack():
    wiz = make_hero(cls="Волшебник")          # ИНТ 16 → +3, мастерство +2
    assert rules.spell_dc(wiz) == 8 + 2 + 3 and rules.spell_attack_bonus(wiz) == 5


def test_prepared_spell_limit_is_modifier_plus_level():
    wiz = make_hero(cls="Волшебник")
    assert rules.prepared_limit(wiz) == 4     # +3 ИНТ +1 уровень
    cleric = make_hero(user_id=12, name="Б", cls="Жрец")
    assert rules.prepared_limit(cleric) == 4  # +3 МДР +1 уровень


def test_cleric_domain_spells_are_always_prepared():
    cleric = make_hero(cls="Жрец")
    assert rules.domain_spells(cleric) == ["Благословение", "Лечение ран"]
    cleric3 = make_hero(user_id=12, name="Б", cls="Жрец", level=3)
    assert "Духовное оружие" in rules.domain_spells(cleric3)
    assert "Лечение ран" in rules.castable_spells(cleric)


def test_arcane_recovery_budget():
    assert [rules.arcane_recovery_budget(lv) for lv in (1, 2, 4, 5)] == [1, 1, 2, 3]   # половина уровня вверх


# ---------------------------------------------------------------- состояния

def test_conditions_tick_and_expire():
    conds = rules.add_condition([], "благословлён", rounds=2)
    conds = rules.add_condition(conds, "доспехи мага", rounds=None)
    conds, expired = rules.tick_conditions(conds)
    assert expired == [] and rules.find_condition(conds, "благословлён")["rounds"] == 1
    conds, expired = rules.tick_conditions(conds)
    assert expired == ["благословлён"] and rules.find_condition(conds, "доспехи мага")


def test_same_condition_does_not_stack_keeps_longer():
    conds = rules.add_condition([], "отравлен", rounds=3)
    conds = rules.add_condition(conds, "отравлен", rounds=8)
    assert len(conds) == 1 and conds[0]["rounds"] == 8
    conds = rules.add_condition(conds, "отравлен", rounds=2)
    assert conds[0]["rounds"] == 8


def test_remove_by_spell():
    conds = rules.add_condition([], "благословлён", rounds=10, src=5, spell="Благословение")
    conds = rules.add_condition(conds, "отравлен", rounds=10)
    assert [x["name"] for x in rules.remove_by_spell(conds, "Благословение", 5)] == ["отравлен"]


# ---------------------------------------------------------------- бой: сложность встречи (с. 165–166)

def test_encounter_multiplier_table():
    assert srd.encounter_multiplier(1, 4) == 1
    assert srd.encounter_multiplier(2, 4) == 1.5
    assert srd.encounter_multiplier(3, 4) == 2 and srd.encounter_multiplier(6, 4) == 2
    assert srd.encounter_multiplier(7, 4) == 2.5 and srd.encounter_multiplier(10, 4) == 2.5
    assert srd.encounter_multiplier(11, 4) == 3 and srd.encounter_multiplier(15, 4) == 4
    # мало героев — множитель выше; один монстр → ×1.5; 15+ → ×5
    assert srd.encounter_multiplier(1, 2) == 1.5 and srd.encounter_multiplier(15, 2) == 5
    # шесть и больше — ниже; один монстр → ×0.5
    assert srd.encounter_multiplier(1, 6) == 0.5 and srd.encounter_multiplier(2, 6) == 1


def test_rulebook_example_encounter_is_hard():
    # Пример из правил: три героя 3-го и один 2-го уровня; бугбир + три хобгоблина = 1000 → сложный.
    make_world()
    for i, lv in enumerate((3, 3, 3, 2)):
        make_hero(user_id=20 + i, name=f"Г{i}", level=lv)
    db.save_enemy(CHAT, name="Бугбир", hp=27, max_hp=27, armor_class=16, attack_bonus=4, damage_dice="2d8+2",
                  cr=1, xp=200) if False else None
    for name, xp in (("Бугбир", 200), ("Хоб1", 100), ("Хоб2", 100), ("Хоб3", 100)):
        db.save_enemy(CHAT, name=name, hp=10, armor_class=12, attack_bonus=2, damage_dice="1d6", xp=xp)
    info = __import__("engine").encounter_difficulty(CHAT)
    # Опыт монстров 500 × 2 = 1000; пороги: сложный 825 (225×3+150), смертельный 1400
    assert info["thresholds"] == [275, 550, 825, 1400]
    assert info["adjusted"] == 1000 and info["label"] == "сложный"


def test_thresholds_table_spot_checks():
    assert srd.XP_THRESHOLDS[1] == (25, 50, 75, 100)
    assert srd.XP_THRESHOLDS[5] == (250, 500, 750, 1100)
    assert srd.XP_THRESHOLDS[20] == (2800, 5700, 8500, 12700)


def test_challenge_rating_table():
    assert srd.CR_TABLE[0.125] == (2, 25) and srd.CR_TABLE[1] == (2, 200) and srd.CR_TABLE[5] == (3, 1800)
    assert srd.CR_TABLE[9][0] == 4 and srd.CR_TABLE[13][0] == 5 and srd.CR_TABLE[17][0] == 6
    assert srd.nearest_cr(0.3) == 0.25 and srd.default_cr_for_hp(7) == 0.25


# ---------------------------------------------------------------- оружие и урон

def test_weapon_table_spot_checks_against_rulebook():
    w = srd.WEAPONS
    assert w["Длинный меч"]["dice"] == "1d8" and "versatile:1d10" in w["Длинный меч"]["props"]
    assert w["Рапира"]["props"] == {"finesse"} and w["Двуручный меч"]["dice"] == "2d6"
    assert w["Секира"]["dice"] == "1d12" and w["Короткий лук"]["ranged"]
    assert w["Кинжал"]["props"] >= {"finesse", "light", "thrown"}
    assert w["Боевой посох"]["dice"] == "1d6" and "versatile:1d8" in w["Боевой посох"]["props"]
    assert w["Молот"]["dice"] == "2d6" and w["Ручной арбалет"]["cat"] == "martial"


def test_armor_table_spot_checks_against_rulebook():
    a = srd.ARMORS
    assert a["Кожаный доспех"][:2] == ("light", 11) and a["Проклёпанная кожа"][1] == 12
    assert a["Кольчужная рубаха"][:2] == ("medium", 13) and a["Полулаты"][1] == 15
    assert a["Кольчуга"] == ("heavy", 16, 13, True) and a["Латы"] == ("heavy", 18, 15, True)
    assert srd.SHIELD_AC == 2 and srd.MEDIUM_ARMOR_MAX_DEX == 2

