import sqlite3

import combat
import creation
import db
import dice
import engine
import features
import rules
import srd
from conftest import CHAT, PLAYER, PLAYER2, equip, make_enemy, make_hero, make_world
from test_combat import fixed_d20, fixed_dice


def start_combat(monkeypatch, player=PLAYER, init=(20, 1)):
    fixed_d20(monkeypatch, *init)
    combat.start(CHAT)
    combat._save_turn(CHAT, combat._fresh_turn(player))


# ---------------------------------------------------------------- способности воина

def test_second_wind_heals_and_is_once_per_rest(monkeypatch):
    make_world()
    hero = make_hero(level=3)
    db.update_character(CHAT, PLAYER, hp=1)
    fixed_dice(monkeypatch, 5)
    ok, lines = features.second_wind(CHAT, db.get_character(CHAT, PLAYER))
    assert ok and db.get_character(CHAT, PLAYER)["hp"] == 1 + 5 + 3           # 1d10 + уровень воина
    ok, lines = features.second_wind(CHAT, db.get_character(CHAT, PLAYER))
    assert not ok and "использовано" in lines[0]
    features.short_rest(CHAT)
    assert features.second_wind(CHAT, db.get_character(CHAT, PLAYER))[0]


def test_second_wind_is_a_bonus_action(monkeypatch):
    make_world()
    make_hero(level=2)
    make_enemy()
    start_combat(monkeypatch)
    db.update_character(CHAT, PLAYER, hp=2)
    assert features.second_wind(CHAT, db.get_character(CHAT, PLAYER))[0]
    assert combat.turn_state(CHAT)["bonus"] == 1


def test_only_fighter_has_second_wind_and_action_surge():
    make_world()
    rogue = make_hero(cls="Плут")
    assert not features.second_wind(CHAT, rogue)[0]
    assert not features.action_surge(CHAT, rogue)[0]


def test_action_surge_grants_another_action_once_per_rest(monkeypatch):
    make_world()
    make_hero(level=2)
    make_enemy()
    start_combat(monkeypatch)
    assert combat.use_action(CHAT, PLAYER) is None
    assert combat.use_action(CHAT, PLAYER) is not None
    ok, _ = features.action_surge(CHAT, db.get_character(CHAT, PLAYER))
    assert ok and combat.use_action(CHAT, PLAYER) is None                      # второе действие
    assert combat.use_action(CHAT, PLAYER) is not None
    combat._save_turn(CHAT, combat._fresh_turn(PLAYER))
    ok, lines = features.action_surge(CHAT, db.get_character(CHAT, PLAYER))
    assert not ok and "использован" in lines[0]                                # 1 раз за отдых до 17 уровня


def test_action_surge_requires_level_two_and_combat(monkeypatch):
    make_world()
    hero = make_hero(level=1)
    assert not features.action_surge(CHAT, hero)[0]
    hero = make_hero(user_id=PLAYER2, name="Б", level=2)
    assert not features.action_surge(CHAT, hero)[0]                            # вне боя


# ---------------------------------------------------------------- плут и действия боя

def test_cunning_action_hide_uses_bonus_action(monkeypatch):
    make_world()
    make_hero(cls="Плут", level=2, skills=["Скрытность"])
    make_enemy()
    start_combat(monkeypatch)
    fixed_d20(monkeypatch, 20)
    ok, lines = features.cunning_action(CHAT, db.get_character(CHAT, PLAYER), "скрыться")
    assert ok and "скрыт" in rules.cond_names(rules.conditions_of(db.get_character(CHAT, PLAYER)))
    assert combat.turn_state(CHAT)["bonus"] == 1 and combat.turn_state(CHAT)["action"] == 0


def test_cunning_action_needs_level_two():
    make_world()
    rogue = make_hero(cls="Плут", level=1)
    assert not features.cunning_action(CHAT, rogue, "рывок")[0]


def test_hide_check_against_passive_perception_and_armor_disadvantage(monkeypatch):
    make_world()
    hero = make_hero(cls="Плут", skills=["Скрытность"])                        # кожаный доспех
    make_enemy(save_bonus=3)                                                    # пассивное Восприятие 13
    fixed_d20(monkeypatch, 5)
    ok, lines = features.hide(CHAT, hero)
    assert ok and "замечен" in lines[0]
    fixed_d20(monkeypatch, 19)
    ok, lines = features.hide(CHAT, db.get_character(CHAT, PLAYER))
    assert "скрыт" in lines[0]
    db.update_character(CHAT, PLAYER, conditions=[])
    equip(PLAYER, "Стёганый доспех")                                            # помеха на скрытность
    ok, lines = features.hide(CHAT, db.get_character(CHAT, PLAYER))
    assert "помеха" in lines[0]


def test_hidden_attacker_gets_advantage_once(monkeypatch):
    make_world()
    hero = make_hero()
    enemy = make_enemy(hp=100, ac=10)
    engine.add_pc_condition(CHAT, hero, "скрыт")
    fixed_d20(monkeypatch, 3, 18)
    fixed_dice(monkeypatch, 3)
    lines, _ = combat.attack_action(CHAT, db.get_character(CHAT, PLAYER), enemy)
    assert "преимущество" in " ".join(lines)
    assert "скрыт" not in rules.cond_names(rules.conditions_of(db.get_character(CHAT, PLAYER)))


def test_dodge_gives_condition_until_next_turn(monkeypatch):
    make_world()
    make_hero()
    make_enemy()
    start_combat(monkeypatch)
    ok, _ = features.dodge(CHAT, db.get_character(CHAT, PLAYER))
    assert ok and "уклоняется" in rules.cond_names(rules.conditions_of(db.get_character(CHAT, PLAYER)))
    conds, expired = rules.tick_conditions(rules.conditions_of(db.get_character(CHAT, PLAYER)))
    assert "уклоняется" in expired                                              # закончится в начале следующего хода


def test_assist_grants_advantage_to_ally_once(monkeypatch):
    make_world()
    make_hero(PLAYER, "Гарен")
    make_hero(PLAYER2, "Лира")
    ok, _ = features.assist(CHAT, db.get_character(CHAT, PLAYER), "Лира")
    assert ok
    ally = db.get_character(CHAT, PLAYER2)
    fixed_d20(monkeypatch, 4, 18)
    result = engine.check_roll(CHAT, ally, "Атлетика", dc=10)
    assert "преимущество" in result["lines"][1]
    assert "помощь" not in rules.cond_names(rules.conditions_of(db.get_character(CHAT, PLAYER2)))
    assert not features.assist(CHAT, db.get_character(CHAT, PLAYER), "Гарен")[0]      # себе нельзя


def test_shove_knocks_prone_on_contest_win(monkeypatch):
    make_world()
    make_hero()
    enemy = make_enemy(save_bonus=0)
    fixed_d20(monkeypatch, 15, 5)
    ok, lines = features.shove(CHAT, db.get_character(CHAT, PLAYER), "Гоблин")
    assert ok and "сбит с ног" in rules.cond_names(engine.enemy_conditions(db.get_enemy(enemy["id"])))
    engine.remove_enemy_condition(db.get_enemy(enemy["id"]), "сбит с ног")
    fixed_d20(monkeypatch, 5, 10)                                                # 5 + 5 = 10 против 10 — ничья, толчок не удался
    features.shove(CHAT, db.get_character(CHAT, PLAYER), "Гоблин")
    assert "сбит с ног" not in rules.cond_names(engine.enemy_conditions(db.get_enemy(enemy["id"])))


def test_stabilize_medicine_dc_10(monkeypatch):
    make_world()
    make_hero(PLAYER, "Гарен")
    hero = make_hero(PLAYER2, "Лира")
    engine.pc_damage(CHAT, hero, hero["max_hp"] + 1)
    fixed_d20(monkeypatch, 1)
    ok, lines = features.stabilize(CHAT, db.get_character(CHAT, PLAYER), "Лира")
    assert ok and db.get_character(CHAT, PLAYER2)["death_successes"] == 0
    fixed_d20(monkeypatch, 20)
    features.stabilize(CHAT, db.get_character(CHAT, PLAYER), "Лира")
    assert db.get_character(CHAT, PLAYER2)["death_successes"] == 3
    assert not features.stabilize(CHAT, db.get_character(CHAT, PLAYER), "Гарен")[0]      # у Гарена есть хиты


# ---------------------------------------------------------------- Божественный канал

def test_preserve_life_heals_up_to_half_max_hp(monkeypatch):
    make_world()
    cleric = make_hero(PLAYER, "Мирра", cls="Жрец", level=2)
    hero = make_hero(PLAYER2, "Гарен")
    db.update_character(CHAT, PLAYER2, hp=1)
    ok, lines = features.channel(CHAT, cleric, "сохранение")
    assert ok
    healed = db.get_character(CHAT, PLAYER2)
    assert healed["hp"] == hero["max_hp"] // 2                                   # не выше половины
    ok, lines = features.channel(CHAT, db.get_character(CHAT, PLAYER), "сохранение")
    assert not ok and "исчерпан" in lines[0]


def test_channel_uses_by_level():
    assert [srd.channel_divinity_uses(lv) for lv in (1, 2, 5, 6, 17, 18)] == [0, 1, 1, 2, 2, 3]


def test_turn_undead_scares_and_destroys_weak_undead(monkeypatch):
    make_world()
    cleric = make_hero(PLAYER, "Мирра", cls="Жрец", level=5)
    skeleton = make_enemy("Скелет", hp=13, cr=0.25, etype="нежить", save_bonus=0)
    ghoul = make_enemy("Упырь", hp=22, cr=1, etype="нежить", save_bonus=0)
    fixed_d20(monkeypatch, 1)
    ok, lines = features.channel(CHAT, cleric, "изгнание")
    assert ok
    assert not db.get_enemy(skeleton["id"])["alive"]                             # ПО 1/4 ≤ 1/2 — уничтожен (5 ур.)
    assert "испуган" in rules.cond_names(engine.enemy_conditions(db.get_enemy(ghoul["id"])))


# ---------------------------------------------------------------- отдых

def test_short_rest_and_hit_dice(monkeypatch):
    make_world()
    hero = make_hero(level=3)
    db.update_character(CHAT, PLAYER, hp=1)
    assert not features.spend_hit_dice(CHAT, db.get_character(CHAT, PLAYER), 1)[0]      # нужен короткий отдых
    features.short_rest(CHAT)
    fixed_dice(monkeypatch, 4)
    ok, lines = features.spend_hit_dice(CHAT, db.get_character(CHAT, PLAYER), 2)
    con = rules.mod_of(hero, "Телосложение")
    assert ok and db.get_character(CHAT, PLAYER)["hp"] == 1 + 2 * (4 + con)
    assert db.get_character(CHAT, PLAYER)["hit_dice_used"] == 2
    ok, lines = features.spend_hit_dice(CHAT, db.get_character(CHAT, PLAYER), 5)       # осталась 1 кость
    assert ok and db.get_character(CHAT, PLAYER)["hit_dice_used"] == 3
    assert not features.spend_hit_dice(CHAT, db.get_character(CHAT, PLAYER), 1)[0]


def test_hit_dice_cannot_be_spent_in_combat(monkeypatch):
    make_world()
    make_hero()
    make_enemy()
    start_combat(monkeypatch)
    assert not features.spend_hit_dice(CHAT, db.get_character(CHAT, PLAYER), 1)[0]


def test_long_rest_restores_hp_slots_features_and_half_hit_dice():
    make_world()
    w = make_hero(cls="Волшебник", level=4)
    db.update_character(CHAT, PLAYER, hp=1, hit_dice_used=4, slots_used={"1": 3, "2": 2}, exhaustion=2,
                        temp_hp=4, uses={"arcane_recovery": 1}, concentration="Паутина",
                        death_failures=2)
    engine.add_pc_condition(CHAT, db.get_character(CHAT, PLAYER), "отравлен", rounds=5)
    features.long_rest(CHAT)
    c = db.get_character(CHAT, PLAYER)
    assert c["hp"] == c["max_hp"] and c["slots_used"] == "{}" and c["uses"] == "{}"
    assert c["hit_dice_used"] == 2                                               # вернулась половина (4/2)
    assert c["exhaustion"] == 1 and c["temp_hp"] == 0 and c["concentration"] == ""
    assert c["death_failures"] == 0 and rules.conditions_of(c) == []


def test_long_rest_regains_at_least_one_hit_die():
    make_world()
    make_hero(level=1)
    db.update_character(CHAT, PLAYER, hit_dice_used=1)
    features.long_rest(CHAT)
    assert db.get_character(CHAT, PLAYER)["hit_dice_used"] == 0


def test_long_rest_does_not_revive_the_dead():
    make_world()
    make_hero()
    db.update_character(CHAT, PLAYER, alive=0, hp=0)
    features.long_rest(CHAT)
    assert db.get_character(CHAT, PLAYER)["alive"] == 0 and db.get_character(CHAT, PLAYER)["hp"] == 0


def test_arcane_recovery(monkeypatch):
    make_world()
    make_hero(cls="Волшебник", level=4)                                          # бюджет 2
    db.update_character(CHAT, PLAYER, slots_used={"1": 4, "2": 3})
    features.short_rest(CHAT)
    w = db.get_character(CHAT, PLAYER)
    assert not features.arcane_recovery(CHAT, w, [2, 1])[0]                      # 3 > 2
    assert not features.arcane_recovery(CHAT, w, [6])[0]
    ok, _ = features.arcane_recovery(CHAT, w, [2])
    assert ok and rules.slots_used(db.get_character(CHAT, PLAYER)) == {1: 4, 2: 2}
    assert not features.arcane_recovery(CHAT, db.get_character(CHAT, PLAYER), [1])[0]  # раз в день
    features.long_rest(CHAT)
    features.short_rest(CHAT)
    assert features.arcane_recovery(CHAT, db.get_character(CHAT, PLAYER), [1])[0] is False   # нет потраченных


# ---------------------------------------------------------------- развитие

def test_asi_plus_two_or_two_plus_one_capped_at_20():
    make_world()
    hero = make_hero(level=4)
    db.update_character(CHAT, PLAYER, asi_pending=2)
    ok, _ = features.asi(CHAT, db.get_character(CHAT, PLAYER), "Сила", "Сила")
    assert ok and rules.stats_of(db.get_character(CHAT, PLAYER))["Сила"] == 18
    ok, _ = features.asi(CHAT, db.get_character(CHAT, PLAYER), "Ловкость", "Мудрость")
    stats = rules.stats_of(db.get_character(CHAT, PLAYER))
    assert ok and stats["Ловкость"] == 15 and stats["Мудрость"] == 12
    assert not features.asi(CHAT, db.get_character(CHAT, PLAYER), "Сила", "Сила")[0]     # больше нет повышений
    db.update_character(CHAT, PLAYER, asi_pending=1, stats={**stats, "Сила": 19})
    ok, lines = features.asi(CHAT, db.get_character(CHAT, PLAYER), "Сила", "Сила")
    assert not ok and "20" in lines[0]


def test_asi_constitution_recomputes_hit_points_retroactively():
    make_world()
    hero = make_hero(level=4)                                                    # ТЕЛ 15 (+2) → 16 (+3)
    db.update_character(CHAT, PLAYER, asi_pending=1)
    ok, lines = features.asi(CHAT, db.get_character(CHAT, PLAYER), "Телосложение", "Мудрость")
    assert ok
    assert db.get_character(CHAT, PLAYER)["max_hp"] == hero["max_hp"] + 4         # +1 за каждый из 4 уровней


def test_asi_input_validation():
    make_world()
    make_hero(level=4)
    db.update_character(CHAT, PLAYER, asi_pending=1)
    assert not features.asi(CHAT, db.get_character(CHAT, PLAYER), "Удача", "")[0]


def test_expertise_selection():
    make_world()
    make_hero(cls="Плут", level=6, skills=["Скрытность", "Восприятие", "Обман", "Акробатика"])
    db.update_character(CHAT, PLAYER, expertise_pending=2, expertise=["Скрытность"])
    rogue = db.get_character(CHAT, PLAYER)
    assert not features.expertise(CHAT, rogue, ["Скрытность", "Восприятие"])[0]        # уже есть
    assert not features.expertise(CHAT, rogue, ["Магия", "Восприятие"])[0]             # навыка нет
    ok, _ = features.expertise(CHAT, rogue, ["Восприятие", "Обман"])
    assert ok and rules.expertise_of(db.get_character(CHAT, PLAYER)) == {"Скрытность", "Восприятие", "Обман"}


def test_wizard_learns_spells_and_cantrips():
    make_world()
    w = make_hero(cls="Волшебник", level=3)
    db.update_character(CHAT, PLAYER, learn_pending=2, cantrip_pending=1)
    w = db.get_character(CHAT, PLAYER)
    ok, _ = features.learn_spell(CHAT, w, "Молния")
    assert not ok                                                                  # 3 ур. ещё недоступен
    ok, _ = features.learn_spell(CHAT, db.get_character(CHAT, PLAYER), "Паутина")
    assert ok and "Паутина" in rules.spellbook_of(db.get_character(CHAT, PLAYER))
    assert not features.learn_spell(CHAT, db.get_character(CHAT, PLAYER), "Паутина")[0]   # уже в книге
    ok, _ = features.learn_cantrip(CHAT, db.get_character(CHAT, PLAYER), "Электрошок")
    assert ok and "Электрошок" in rules.cantrips_of(db.get_character(CHAT, PLAYER))
    assert not features.learn_cantrip(CHAT, db.get_character(CHAT, PLAYER), "Кислотные брызги")[0]  # лимит


def test_prepare_spells_limit_and_source():
    make_world()
    w = make_hero(cls="Волшебник", level=1)                                        # лимит 4
    ok, lines = features.prepare(CHAT, w, ["Волшебная стрела", "Щит"])
    assert ok and rules.prepared_of(db.get_character(CHAT, PLAYER)) == ["Волшебная стрела", "Щит"]
    ok, lines = features.prepare(CHAT, w, ["Волшебная стрела", "Щит", "Доспехи мага", "Усыпление", "Огненные ладони"])
    assert not ok and "4" in lines[0]
    ok, lines = features.prepare(CHAT, w, ["Огненный шар"])                        # нет в книге и уровень слишком высок
    assert not ok
    cleric = make_hero(PLAYER2, "Мирра", cls="Жрец", level=1)                      # лимит 4; доменные не считаются
    ok, _ = features.prepare(CHAT, cleric, ["Благословение", "Лечащее слово", "Щит веры", "Приказ", "Нанесение ран"])
    assert ok and "Благословение" not in rules.prepared_of(db.get_character(CHAT, PLAYER2))
    assert len(rules.prepared_of(db.get_character(CHAT, PLAYER2))) == 4
    assert not features.prepare(CHAT, make_hero(user_id=13, name="В"), ["Щит"])[0]  # воин не колдует


def test_inspiration_spend_and_advantage(monkeypatch):
    make_world()
    hero = make_hero()
    assert not features.inspire(CHAT, hero)[0]
    db.update_character(CHAT, PLAYER, inspiration=1)
    ok, _ = features.inspire(CHAT, db.get_character(CHAT, PLAYER))
    assert ok and db.get_character(CHAT, PLAYER)["inspiration"] == 0
    fixed_d20(monkeypatch, 3, 17)
    result = engine.check_roll(CHAT, db.get_character(CHAT, PLAYER), "Атлетика")
    assert "17" in result["lines"][1] and "вдохновение" in result["lines"][1]
    assert "вдохновлён" not in rules.cond_names(rules.conditions_of(db.get_character(CHAT, PLAYER)))


# ---------------------------------------------------------------- проверки и спасброски

def test_check_roll_skill_with_proficiency_and_dc(monkeypatch):
    make_world()
    hero = make_hero(skills=["Восприятие"])                                        # МДР 11 → 0, +2
    fixed_d20(monkeypatch, 12)
    result = engine.check_roll(CHAT, hero, "Восприятие", dc=14)
    assert result["total"] == 14 and result["success"] is True and "мастерство" in result["lines"][1]
    fixed_d20(monkeypatch, 11)
    assert engine.check_roll(CHAT, hero, "Восприятие", dc=14)["success"] is False


def test_natural_twenty_is_not_automatic_success_on_checks(monkeypatch):
    make_world()
    hero = make_hero()
    fixed_d20(monkeypatch, 20)
    assert engine.check_roll(CHAT, hero, "Интеллект", dc=25)["success"] is False       # с. 61: автоуспеха нет


def test_check_disadvantage_sources(monkeypatch):
    make_world()
    hero = make_hero()
    engine.add_pc_condition(CHAT, hero, "отравлен", rounds=5)
    fixed_d20(monkeypatch, 18, 4)
    result = engine.check_roll(CHAT, db.get_character(CHAT, PLAYER), "Атлетика")
    assert "помеха" in result["lines"][1]
    db.update_character(CHAT, PLAYER, conditions=[], exhaustion=1)
    result = engine.check_roll(CHAT, db.get_character(CHAT, PLAYER), "Атлетика")
    assert "истощение" in result["lines"][1]


def test_nonproficient_armor_gives_disadvantage_on_str_dex_checks(monkeypatch):
    make_world()
    w = make_hero(cls="Волшебник")
    equip(PLAYER, "Латы")
    fixed_d20(monkeypatch, 15, 3)
    result = engine.check_roll(CHAT, db.get_character(CHAT, PLAYER), "Акробатика")
    assert "доспех без мастерства" in result["lines"][1]
    fixed_d20(monkeypatch, 15, 3)
    assert "доспех" not in engine.check_roll(CHAT, db.get_character(CHAT, PLAYER), "История")["lines"][1]


def test_halfling_lucky_rerolls_natural_one(monkeypatch):
    make_world()
    hero = make_hero(race="Полурослик", subrace="Легконогий")
    fixed_d20(monkeypatch, 1, 14)
    result = engine.check_roll(CHAT, hero, "Атлетика")
    assert "14" in result["lines"][1]


def test_elf_has_perception_proficiency():
    make_world()
    elf = make_hero(race="Эльф", subrace="Лесной", cls="Плут")
    assert "Восприятие" in rules.skills_of(elf)
    assert rules.speed_of(elf) == 35 and rules.speed_of(make_hero(user_id=PLAYER2, name="Б")) == 30


def test_saving_throw_proficiency_and_racial_advantage(monkeypatch):
    make_world()
    dwarf = make_hero(race="Дварф", subrace="Холмовой")
    fixed_d20(monkeypatch, 3, 15)
    result = engine.pc_save(CHAT, dwarf, "Телосложение", 15, against="яд")
    assert "преимущество" in result["text"] and result["success"] is True              # 15 + 3 (ТЕЛ) + 2 (мастерство)
    fixed_d20(monkeypatch, 3, 15)
    result = engine.pc_save(CHAT, dwarf, "Телосложение", 15, against="огонь")
    assert "преимущество" not in result["text"]


def test_paralyzed_or_unconscious_auto_fail_str_dex_saves():
    make_world()
    hero = make_hero()
    engine.add_pc_condition(CHAT, hero, "парализован", rounds=5)
    result = engine.pc_save(CHAT, db.get_character(CHAT, PLAYER), "Ловкость", 1)
    assert result["success"] is False and result["auto"]
    assert engine.pc_save(CHAT, db.get_character(CHAT, PLAYER), "Мудрость", 1)["auto"] is False


def test_dodge_and_restrained_affect_dex_saves(monkeypatch):
    make_world()
    hero = make_hero()
    engine.add_pc_condition(CHAT, hero, "уклоняется", rounds=1)
    fixed_d20(monkeypatch, 3, 15)
    assert "преимущество" in engine.pc_save(CHAT, db.get_character(CHAT, PLAYER), "Ловкость", 10)["text"]
    db.update_character(CHAT, PLAYER, conditions=[])
    engine.add_pc_condition(CHAT, db.get_character(CHAT, PLAYER), "опутан", rounds=3)
    fixed_d20(monkeypatch, 15, 3)
    assert "помеха" in engine.pc_save(CHAT, db.get_character(CHAT, PLAYER), "Ловкость", 10)["text"]


def test_rogue_evasion_not_needed_for_pc_but_uncanny_dodge_present():
    assert any("Невероятное уклонение" in f for f in srd.CLASSES["Плут"]["features"][5])


# ---------------------------------------------------------------- создание персонажа

def test_creation_builds_valid_character():
    make_world()
    data = {"race": "Эльф", "subrace": "Высший", "cls": "Волшебник", "bg": "Мудрец", "values": [15, 14, 13, 12, 10, 8],
            "skills": ["Расследование", "Медицина"], "expertise": [], "style": ""}
    assert creation.create(CHAT, PLAYER, "Игрок", "Элдрин", "маг", data)
    c = db.get_character(CHAT, PLAYER)
    stats = rules.stats_of(c)
    # Волшебник: ИНТ 15 +1 (высший эльф) = 16, ЛОВ 13 +2 = 15, ТЕЛ 14
    assert stats["Интеллект"] == 16 and stats["Ловкость"] == 15 and stats["Телосложение"] == 14
    assert c["max_hp"] == 6 + 2 and c["hp"] == c["max_hp"] and c["level"] == 1 and c["xp"] == 0
    skills = rules.skills_of(c)
    assert {"Магия", "История", "Расследование", "Медицина", "Восприятие"} <= skills
    assert len(rules.cantrips_of(c)) == 4                                        # 3 + заговор высшего эльфа
    assert len(rules.spellbook_of(c)) == 6 and len(rules.prepared_of(c)) == rules.prepared_limit(c)
    assert db.equipped_item(CHAT, PLAYER, "weapon")["name"] == "Боевой посох"
    assert db.equipped_item(CHAT, PLAYER, "armor") is None


def test_skill_options_exclude_duplicates_from_background_and_race():
    options = creation.skill_options("Воин", "Эльф", "Лесной", "Солдат")
    assert "Атлетика" not in options and "Запугивание" not in options            # даёт предыстория Солдат
    assert "Восприятие" not in options                                           # даёт раса эльфов
    assert len(options) == 8 - 3
    assert len(creation.skill_options("Плут", "Человек", "", "Преступник")) == 11 - 2


def test_creation_gives_class_equipment():
    make_world()
    for user, cls, weapon, armor, shield in (
        (21, "Воин", "Длинный меч", "Кольчуга", True),
        (22, "Плут", "Рапира", "Кожаный доспех", False),
        (23, "Жрец", "Булава", "Кольчуга", True),
    ):
        data = {"race": "Человек", "cls": cls, "bg": "Солдат", "values": [15, 14, 13, 12, 10, 8], "skills": []}
        assert creation.create(CHAT, user, "И", f"Г{user}", "x", data)
        assert db.equipped_item(CHAT, user, "weapon")["name"] == weapon
        assert (db.equipped_item(CHAT, user, "armor") or {"name": None})["name"] == armor
        assert (db.equipped_item(CHAT, user, "shield") is not None) == shield


def test_weak_cleric_gets_scale_mail_not_chain_mail():
    assert ("Чешуйчатый доспех", "armor") in creation.starting_gear("Жрец", 10)
    assert ("Кольчуга", "armor") in creation.starting_gear("Жрец", 13)


def test_creation_rejects_duplicate_name():
    make_world()
    data = {"race": "Человек", "cls": "Воин", "bg": "Солдат", "values": [15, 14, 13, 12, 10, 8]}
    assert creation.create(CHAT, 21, "А", "Гарен", "x", data)
    assert not creation.create(CHAT, 22, "Б", "Гарен", "x", data)


def test_cleric_starting_spells():
    stats = creation.build_stats("Жрец", [15, 14, 13, 12, 10, 8], "Человек", "")
    s = creation.starting_spells("Жрец", 1, stats, "Человек", "")
    assert s["cantrips"] == ["Священное пламя", "Указание", "Сохранение жизни"] and len(s["prepared"]) == 4
    assert all(name in srd.QUICK_CLERIC_PREPARE for name in s["prepared"])


# ---------------------------------------------------------------- предметы

def test_srd_item_lookup():
    kind, value = rules.srd_item("Длинный меч")
    assert kind == "weapon" and value["dice"] == "1d8" and value["srd"] == "Длинный меч"
    assert rules.srd_item("кольчуга")[0] == "armor" and rules.srd_item("щит")[0] == "shield"
    assert rules.srd_item("Верёвка") is None


def test_legacy_item_formats_still_work():
    weapon = rules.weapon_info({"name": "Меч", "kind": "weapon", "value": "1d8"})
    assert weapon["dice"] == "1d8" and not weapon["ranged"]
    armor = rules.armor_info({"name": "Броня", "kind": "armor", "value": "2"})
    assert armor["base"] == 12 and armor["cat"] == "light"


def test_magic_bonus_applies_to_attack_and_damage():
    make_world()
    hero = make_hero()
    kind, value = rules.srd_item("Длинный меч")
    value["bonus"] = 2
    item = db.add_item(CHAT, PLAYER, "Меч +2", kind, value)
    db.equip_item(CHAT, PLAYER, item["id"], "weapon")
    p = rules.attack_profile(hero, item, None)
    plain = rules.attack_profile(hero, {"name": "Длинный меч", "kind": "weapon", "value": ""}, None)
    assert p["attack"] == plain["attack"] + 2 and p["damage_bonus"] == plain["damage_bonus"] + 2


# ---------------------------------------------------------------- миграция базы

def test_migration_from_first_version_database(tmp_path):
    path = str(tmp_path / "old.db")
    c = sqlite3.connect(path)
    c.executescript(
        "CREATE TABLE games (chat_id INTEGER PRIMARY KEY, theme TEXT NOT NULL, world_desc TEXT NOT NULL);"
        "CREATE TABLE characters (id INTEGER PRIMARY KEY AUTOINCREMENT, chat_id INTEGER NOT NULL,"
        " user_id INTEGER NOT NULL, user_name TEXT NOT NULL, name TEXT NOT NULL,"
        " description TEXT NOT NULL, attributes TEXT NOT NULL, hp INTEGER NOT NULL DEFAULT 20,"
        " max_hp INTEGER NOT NULL DEFAULT 20, level INTEGER NOT NULL DEFAULT 1, xp INTEGER NOT NULL DEFAULT 0,"
        " UNIQUE (chat_id, user_id), UNIQUE (chat_id, name));"
        "CREATE TABLE enemies (id INTEGER PRIMARY KEY AUTOINCREMENT, chat_id INTEGER NOT NULL, name TEXT NOT NULL,"
        " description TEXT NOT NULL DEFAULT '', hp INTEGER NOT NULL, max_hp INTEGER NOT NULL,"
        " armor_class INTEGER NOT NULL, attack_bonus INTEGER NOT NULL, damage_dice TEXT NOT NULL,"
        " initiative_bonus INTEGER NOT NULL DEFAULT 0, xp INTEGER NOT NULL DEFAULT 0, alive INTEGER NOT NULL DEFAULT 1);"
        "CREATE TABLE combat (chat_id INTEGER PRIMARY KEY, round INTEGER NOT NULL, turn_index INTEGER NOT NULL,"
        " order_json TEXT NOT NULL);"
    )
    c.execute("INSERT INTO games VALUES (1, 'старая', 'мир')")
    # уровень 2, старый xp — прогресс внутри уровня (20 из 200)
    c.execute("INSERT INTO characters (chat_id,user_id,user_name,name,description,attributes,level,xp,hp,max_hp)"
              " VALUES (1,10,'N','Гарен','воин','Сила, Воля',2,20,25,28)")
    c.execute("INSERT INTO enemies (chat_id,name,hp,max_hp,armor_class,attack_bonus,damage_dice)"
              " VALUES (1,'Гоблин',7,7,12,3,'1d6')")
    c.execute("INSERT INTO combat VALUES (1, 2, 0, '[]')")
    c.commit()
    c.close()
    db._conn = None
    db.DB_PATH = path
    hero = db.get_character(1, 10)
    assert hero["name"] == "Гарен" and hero["hp"] == 25 and hero["max_hp"] == 28
    assert hero["xp"] == 300 + 20                                                # суммарный опыт по таблице правил
    assert rules.class_of(hero) == "Воин" and rules.race_of(hero) == "Человек"   # прежние герои — воины-люди
    assert rules.stats_of(hero)["Сила"] == 16                                    # 16 в выбранных, 10 в остальных
    assert hero["hit_dice_used"] == 0 and hero["temp_hp"] == 0
    enemy = db.list_enemies(1)[0]
    assert enemy["save_bonus"] == 1 and enemy["cr"] == 0.25 and enemy["attacks"] == 1
    assert db.get_combat(1)["state"] == {}
    # повторное открытие не пересчитывает опыт второй раз
    db._conn = None
    assert db.get_character(1, 10)["xp"] == 320
    # в старой базе attributes обязателен: новый герой всё равно должен сохраняться
    import creation
    data = {"race": "Эльф", "subrace": "Высший эльф", "cls": "Воин", "bg": "Солдат",
            "values": [15, 14, 13, 12, 10, 8], "skills": ["Атлетика", "Запугивание"], "style": "Защита"}
    assert creation.create(1, 11, "M", "Новый", "герой", data) is True
    assert creation.create(1, 12, "K", "Новый", "занято", data) is False   # имя занято — честный отказ


def test_legacy_hero_can_fight_and_cast_checks(monkeypatch):
    """Персонаж из первой версии (без класса и снаряжения) работает как воин-человек."""
    make_world()
    db.save_character(CHAT, PLAYER, "Игрок", "Старый", "воин", attributes="Сила, Воля", hp=20, max_hp=20)
    hero = db.get_character(CHAT, PLAYER)
    enemy = make_enemy(hp=30, ac=10)
    fixed_d20(monkeypatch, 15)
    fixed_dice(monkeypatch, 3)
    lines, _ = combat.attack_action(CHAT, hero, enemy)
    assert db.get_enemy(enemy["id"])["hp"] < 30
    assert engine.check_roll(CHAT, hero, "Атлетика", dc=5)["success"] is not None
