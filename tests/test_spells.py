import combat
import db
import dice
import engine
import rules
import spells
from conftest import CHAT, PLAYER, PLAYER2, equip, make_enemy, make_hero, make_world
from test_combat import fixed_d20, fixed_dice


def wizard(level=5, prepared=None, **kw):
    hero = make_hero(cls="Волшебник", level=level, **kw)
    if prepared:
        db.update_character(CHAT, hero["user_id"], prepared=prepared)
    return db.get_character(CHAT, hero["user_id"])


def cleric(level=3, user_id=PLAYER, name="Мирра", **kw):
    hero = make_hero(user_id=user_id, name=name, cls="Жрец", level=level, **kw)
    return db.get_character(CHAT, hero["user_id"])


def used_slots(user_id=PLAYER):
    return rules.slots_used(db.get_character(CHAT, user_id))


# ---------------------------------------------------------------- проверки допуска

def test_cannot_cast_unprepared_spell():
    make_world()
    w = wizard()
    ok, lines = spells.cast(CHAT, w, "Огненный шар")
    assert not ok and "нет среди" in lines[0]


def test_cannot_cast_without_slots():
    make_world()
    w = wizard(level=1, prepared=["Волшебная стрела"])
    make_enemy(hp=100)
    assert spells.cast(CHAT, w, "Волшебная стрела")[0]
    assert spells.cast(CHAT, db.get_character(CHAT, PLAYER), "Волшебная стрела")[0]      # 2 ячейки на 1 уровне
    ok, lines = spells.cast(CHAT, db.get_character(CHAT, PLAYER), "Волшебная стрела")
    assert not ok and "ячеек" in lines[0]


def test_cantrips_do_not_use_slots(monkeypatch):
    make_world()
    w = wizard(level=1)
    db.update_character(CHAT, PLAYER, cantrips=["Огненный снаряд"])
    make_enemy(hp=100, ac=5)
    fixed_d20(monkeypatch, 15)
    ok, _ = spells.cast(CHAT, db.get_character(CHAT, PLAYER), "Огненный снаряд")
    assert ok and used_slots() == {}


def test_wizard_in_unproficient_armor_cannot_cast():
    make_world()
    w = wizard(level=1)
    equip(PLAYER, "Латы")
    ok, lines = spells.cast(CHAT, db.get_character(CHAT, PLAYER), "Волшебная стрела")
    assert not ok and "доспех" in lines[0]


def test_incapacitated_or_dead_cannot_cast():
    make_world()
    w = wizard(level=1)
    engine.add_pc_condition(CHAT, w, "парализован", rounds=5)
    assert not spells.cast(CHAT, db.get_character(CHAT, PLAYER), "Волшебная стрела")[0]


def test_slot_level_validation_and_auto_upcast():
    make_world()
    w = wizard(level=3, prepared=["Волшебная стрела"])          # 4 ячейки 1 ур., 2 — 2 ур.
    make_enemy(hp=100)
    for _ in range(4):
        assert spells.cast(CHAT, db.get_character(CHAT, PLAYER), "Волшебная стрела")[0]
    assert used_slots() == {1: 4}
    ok, _ = spells.cast(CHAT, db.get_character(CHAT, PLAYER), "Волшебная стрела")   # 1 ур. кончились → 2 ур.
    assert ok and used_slots() == {1: 4, 2: 1}
    ok, lines = spells.cast(CHAT, db.get_character(CHAT, PLAYER), "Волшебная стрела", slot=5)
    assert not ok and "свободной ячейки" in lines[0]
    ok, lines = spells.cast(CHAT, db.get_character(CHAT, PLAYER), "Волшебная стрела", slot=0)
    assert not ok


# ---------------------------------------------------------------- атака заклинанием и заговоры

def test_fire_bolt_scales_with_level(monkeypatch):
    make_world()
    w = wizard(level=5)                                          # 2d10
    db.update_character(CHAT, PLAYER, cantrips=["Огненный снаряд"])
    enemy = make_enemy(hp=200, ac=10)
    fixed_d20(monkeypatch, 15)
    fixed_dice(monkeypatch, 4)
    ok, lines = spells.cast(CHAT, db.get_character(CHAT, PLAYER), "Огненный снаряд", targets=["Гоблин"])
    assert ok and db.get_enemy(enemy["id"])["hp"] == 200 - 8    # 2d10 по 4
    db.update_character(CHAT, PLAYER, level=11)
    fixed_d20(monkeypatch, 15)
    spells.cast(CHAT, db.get_character(CHAT, PLAYER), "Огненный снаряд")
    assert db.get_enemy(enemy["id"])["hp"] == 200 - 8 - (12 + 3)  # 3d10 + мод. ИНТ (усиленное воплощение, 10 ур.)


def test_spell_attack_miss_and_crit_doubles_dice(monkeypatch):
    make_world()
    w = wizard(level=1)
    db.update_character(CHAT, PLAYER, cantrips=["Огненный снаряд"])
    enemy = make_enemy(hp=100, ac=30)
    fixed_d20(monkeypatch, 3)
    spells.cast(CHAT, db.get_character(CHAT, PLAYER), "Огненный снаряд")
    assert db.get_enemy(enemy["id"])["hp"] == 100
    fixed_d20(monkeypatch, 20)
    fixed_dice(monkeypatch, 5)
    spells.cast(CHAT, db.get_character(CHAT, PLAYER), "Огненный снаряд")
    assert db.get_enemy(enemy["id"])["hp"] == 100 - 10


def test_guiding_bolt_marks_target(monkeypatch):
    make_world()
    c = cleric(level=1)
    db.update_character(CHAT, PLAYER, prepared=["Направляющий снаряд"])
    enemy = make_enemy(hp=200, ac=5)
    fixed_d20(monkeypatch, 15)
    fixed_dice(monkeypatch, 3)
    ok, _ = spells.cast(CHAT, db.get_character(CHAT, PLAYER), "Направляющий снаряд")
    assert ok
    assert "отмечен" in rules.cond_names(engine.enemy_conditions(db.get_enemy(enemy["id"])))
    assert db.get_enemy(enemy["id"])["hp"] == 200 - 12                      # 4d6 по 3


def test_upcast_adds_dice(monkeypatch):
    make_world()
    c = cleric(level=3)
    db.update_character(CHAT, PLAYER, prepared=["Направляющий снаряд"])
    enemy = make_enemy(hp=200, ac=5)
    fixed_d20(monkeypatch, 15)
    fixed_dice(monkeypatch, 2)
    spells.cast(CHAT, db.get_character(CHAT, PLAYER), "Направляющий снаряд", slot=2)
    assert db.get_enemy(enemy["id"])["hp"] == 200 - 5 * 2                  # 5d6 по 2


def test_no_target_does_not_crash():
    make_world()
    w = wizard(level=1)
    db.update_character(CHAT, PLAYER, cantrips=["Огненный снаряд"])
    ok, lines = spells.cast(CHAT, db.get_character(CHAT, PLAYER), "Огненный снаряд")
    assert ok and any("цел" in l.lower() for l in lines)


# ---------------------------------------------------------------- волшебная стрела

def test_magic_missile_always_hits_and_upcast_adds_darts(monkeypatch):
    make_world()
    w = wizard(level=3, prepared=["Волшебная стрела"])
    enemy = make_enemy(hp=100)
    fixed_dice(monkeypatch, 3)
    spells.cast(CHAT, w, "Волшебная стрела")
    assert db.get_enemy(enemy["id"])["hp"] == 100 - 3 * (3 + 1)            # 3 снаряда по 1d4+1
    spells.cast(CHAT, db.get_character(CHAT, PLAYER), "Волшебная стрела", slot=2)
    assert db.get_enemy(enemy["id"])["hp"] == 100 - 12 - 4 * 4             # 4 снаряда


def test_magic_missile_splits_between_targets(monkeypatch):
    make_world()
    w = wizard(level=1, prepared=["Волшебная стрела"])
    a = make_enemy("Гоблин", hp=100)
    b = make_enemy("Орк", hp=100)
    fixed_dice(monkeypatch, 3)
    spells.cast(CHAT, w, "Волшебная стрела", targets=["Гоблин", "Орк"])
    assert db.get_enemy(a["id"])["hp"] == 100 - 8 and db.get_enemy(b["id"])["hp"] == 100 - 4


# ---------------------------------------------------------------- спасброски цели

def test_fireball_half_on_save_full_on_fail(monkeypatch):
    make_world()
    w = wizard(level=5, prepared=["Огненный шар"])
    a = make_enemy("Гоблин", hp=200, save_bonus=0)
    b = make_enemy("Орк", hp=200, save_bonus=0)
    fixed_dice(monkeypatch, 4)                                              # 8d6 = 32
    fixed_d20(monkeypatch, 1, 20)                                           # гоблин проваливает, орк проходит
    ok, _ = spells.cast(CHAT, w, "Огненный шар", slot=3)
    assert ok
    assert db.get_enemy(a["id"])["hp"] == 200 - 32 and db.get_enemy(b["id"])["hp"] == 200 - 16
    assert used_slots() == {3: 1}


def test_fireball_upcast_adds_d6_per_level(monkeypatch):
    make_world()
    w = wizard(level=7, prepared=["Огненный шар"])
    enemy = make_enemy(hp=500, save_bonus=0)
    fixed_dice(monkeypatch, 3)
    fixed_d20(monkeypatch, 1)
    spells.cast(CHAT, w, "Огненный шар", slot=4)                            # 9d6
    assert db.get_enemy(enemy["id"])["hp"] == 500 - 27


def test_sacred_flame_no_damage_on_save_but_evocation_wizard_cantrip_does_half(monkeypatch):
    make_world()
    c = cleric(level=1)
    enemy = make_enemy(hp=100, save_bonus=0)
    fixed_dice(monkeypatch, 6)
    fixed_d20(monkeypatch, 20)
    spells.cast(CHAT, c, "Священное пламя")
    assert db.get_enemy(enemy["id"])["hp"] == 100                            # успех — урона нет
    fixed_d20(monkeypatch, 1)
    spells.cast(CHAT, db.get_character(CHAT, PLAYER), "Священное пламя")
    assert db.get_enemy(enemy["id"])["hp"] == 94
    # Сильный заговор (с. 34): волшебник-воплощение 6 уровня — половина урона даже при успехе
    db.reset_game(CHAT)
    make_world()
    w = wizard(level=6)
    db.update_character(CHAT, PLAYER, cantrips=["Ядовитые брызги"])
    enemy = make_enemy(hp=100, save_bonus=0)
    fixed_d20(monkeypatch, 20)
    spells.cast(CHAT, db.get_character(CHAT, PLAYER), "Ядовитые брызги")
    assert db.get_enemy(enemy["id"])["hp"] == 100 - 6                        # 1d12 = 12 → половина


def test_empowered_evocation_adds_int_modifier(monkeypatch):
    make_world()
    w = wizard(level=10, prepared=["Огненные ладони"])
    enemy = make_enemy(hp=500, save_bonus=0)
    fixed_dice(monkeypatch, 2)
    fixed_d20(monkeypatch, 1)
    spells.cast(CHAT, w, "Огненные ладони")                                  # 3d6=6 + ИНТ(+3)
    assert db.get_enemy(enemy["id"])["hp"] == 500 - 9


def test_max_targets_limit_for_area_spell(monkeypatch):
    make_world()
    w = wizard(level=1, prepared=["Огненные ладони"])
    enemies = [make_enemy(f"Крыса{i}", hp=100) for i in range(5)]
    fixed_dice(monkeypatch, 3)
    fixed_d20(monkeypatch, 1)
    spells.cast(CHAT, w, "Огненные ладони")
    hit = [e for e in db.list_enemies(CHAT) if e["hp"] < 100]
    assert len(hit) == 3


def test_thunderwave_and_shatter_use_con_save(monkeypatch):
    make_world()
    w = wizard(level=3, prepared=["Волна грома", "Дребезги"])
    enemy = make_enemy(hp=500, save_bonus=0)
    fixed_dice(monkeypatch, 4)
    fixed_d20(monkeypatch, 1)
    spells.cast(CHAT, w, "Волна грома")
    assert db.get_enemy(enemy["id"])["hp"] == 500 - 8
    spells.cast(CHAT, db.get_character(CHAT, PLAYER), "Дребезги")
    assert db.get_enemy(enemy["id"])["hp"] == 500 - 8 - 12


def test_ice_storm_has_two_damage_types(monkeypatch):
    make_world()
    w = wizard(level=7, prepared=["Град"])
    enemy = make_enemy(hp=500, save_bonus=0)
    fixed_dice(monkeypatch, 3)
    fixed_d20(monkeypatch, 1)
    spells.cast(CHAT, w, "Град")                                              # 2d8 + 4d6 = 6 + 12
    assert db.get_enemy(enemy["id"])["hp"] == 500 - 18


# ---------------------------------------------------------------- состояния от заклинаний

def test_hold_person_paralyzes_on_failed_save_and_needs_concentration(monkeypatch):
    make_world()
    c = cleric(level=3)
    db.update_character(CHAT, PLAYER, prepared=["Удержание личности"])
    enemy = make_enemy(hp=50, save_bonus=0)
    fixed_d20(monkeypatch, 1)
    ok, _ = spells.cast(CHAT, db.get_character(CHAT, PLAYER), "Удержание личности")
    assert ok
    conds = engine.enemy_conditions(db.get_enemy(enemy["id"]))
    assert "парализован" in rules.cond_names(conds)
    assert db.get_character(CHAT, PLAYER)["concentration"] == "Удержание личности"
    engine.end_concentration(CHAT, db.get_character(CHAT, PLAYER))
    assert "парализован" not in rules.cond_names(engine.enemy_conditions(db.get_enemy(enemy["id"])))


def test_successful_save_applies_no_condition_and_no_concentration(monkeypatch):
    make_world()
    c = cleric(level=3)
    db.update_character(CHAT, PLAYER, prepared=["Удержание личности"])
    enemy = make_enemy(hp=50, save_bonus=0)
    fixed_d20(monkeypatch, 20)
    spells.cast(CHAT, db.get_character(CHAT, PLAYER), "Удержание личности")
    assert not engine.enemy_conditions(db.get_enemy(enemy["id"]))
    assert db.get_character(CHAT, PLAYER)["concentration"] == ""


def test_new_concentration_spell_ends_previous(monkeypatch):
    make_world()
    c = cleric(level=3)
    db.update_character(CHAT, PLAYER, prepared=["Удержание личности", "Щит веры"])
    enemy = make_enemy(hp=50, save_bonus=0)
    fixed_d20(monkeypatch, 1)
    spells.cast(CHAT, db.get_character(CHAT, PLAYER), "Удержание личности")
    ok, lines = spells.cast(CHAT, db.get_character(CHAT, PLAYER), "Щит веры")
    assert ok and any("теряет концентрацию" in l for l in lines)
    assert "парализован" not in rules.cond_names(engine.enemy_conditions(db.get_enemy(enemy["id"])))
    assert db.get_character(CHAT, PLAYER)["concentration"] == "Щит веры"


def test_web_restrains_and_dex_save_disadvantage(monkeypatch):
    make_world()
    w = wizard(level=3, prepared=["Паутина"])
    enemy = make_enemy(hp=50, save_bonus=0)
    fixed_d20(monkeypatch, 1)
    spells.cast(CHAT, w, "Паутина")
    conds = engine.enemy_conditions(db.get_enemy(enemy["id"]))
    entry = rules.find_condition(conds, "опутан")
    assert entry and entry["save"]["ability"] == "Сила"


def test_sleep_puts_lowest_hp_first_and_wakes_on_damage(monkeypatch):
    make_world()
    w = wizard(level=1, prepared=["Усыпление"])
    small = make_enemy("Крыса", hp=5)
    mid = make_enemy("Гоблин", hp=10)
    big = make_enemy("Огр", hp=50)
    fixed_dice(monkeypatch, 4)                                               # 5d8 = 20 хитов
    spells.cast(CHAT, w, "Усыпление")
    asleep = {e["name"] for e in db.list_enemies(CHAT)
              if "без сознания" in rules.cond_names(engine.enemy_conditions(e))}
    assert asleep == {"Крыса", "Гоблин"}                                     # 5 + 10 = 15 ≤ 20; Огр 50 — нет
    engine.enemy_damage(CHAT, db.get_enemy(small["id"]), 1)
    assert "без сознания" not in rules.cond_names(engine.enemy_conditions(db.get_enemy(small["id"])))


def test_sleep_skips_undead(monkeypatch):
    make_world()
    w = wizard(level=1, prepared=["Усыпление"])
    zombie = make_enemy("Зомби", hp=5, etype="нежить")
    fixed_dice(monkeypatch, 8)
    spells.cast(CHAT, w, "Усыпление")
    assert not engine.enemy_conditions(db.get_enemy(zombie["id"]))


def test_charm_person_stops_attacks_on_caster(monkeypatch):
    make_world()
    w = wizard(level=1, prepared=["Очарование личности"])
    make_hero(PLAYER2, "Лира")
    enemy = make_enemy(save_bonus=0)
    fixed_d20(monkeypatch, 1)
    spells.cast(CHAT, w, "Очарование личности")
    lines: list[str] = []
    for _ in range(8):
        assert combat._pick_target(CHAT, db.get_enemy(enemy["id"]), lines)["user_id"] == PLAYER2


# ---------------------------------------------------------------- лечение

def test_cure_wounds_uses_casting_modifier_and_disciple_of_life(monkeypatch):
    make_world()
    c = cleric(level=1)                                                       # МДР 16 → +3
    make_hero(PLAYER2, "Гарен")
    db.update_character(CHAT, PLAYER2, hp=1)
    fixed_dice(monkeypatch, 4)                                                # 1d8 = 4
    ok, lines = spells.cast(CHAT, c, "Лечение ран", targets=["Гарен"])
    # 4 + мод. МДР 3 + ученик жизни (2 + ячейка 1) = 10
    assert ok and db.get_character(CHAT, PLAYER2)["hp"] == 11


def test_healing_word_is_a_bonus_action(monkeypatch):
    make_world()
    c = cleric(level=1)
    make_hero(PLAYER2, "Гарен")
    db.update_character(CHAT, PLAYER2, hp=1)
    make_enemy()
    fixed_d20(monkeypatch, 20, 1)
    combat.start(CHAT)
    combat._save_turn(CHAT, combat._fresh_turn(PLAYER))
    assert spells.cast(CHAT, c, "Лечащее слово", targets=["Гарен"])[0]
    turn = combat.turn_state(CHAT)
    assert turn["bonus"] == 1 and turn["action"] == 0 and turn["bonus_spell"] == 1
    ok, lines = spells.cast(CHAT, db.get_character(CHAT, PLAYER), "Лечение ран")
    assert not ok and "заговор" in lines[0]                                   # после бонусного заклинания — только заговор


def test_healing_wakes_unconscious_ally(monkeypatch):
    make_world()
    c = cleric(level=1)
    hero = make_hero(PLAYER2, "Гарен")
    engine.pc_damage(CHAT, hero, hero["max_hp"] + 1)
    fixed_dice(monkeypatch, 1)
    spells.cast(CHAT, c, "Лечение ран", targets=["Гарен"])
    healed = db.get_character(CHAT, PLAYER2)
    assert healed["hp"] > 0 and "без сознания" not in rules.cond_names(rules.conditions_of(healed))


def test_cannot_heal_the_dead():
    make_world()
    c = cleric(level=1)
    hero = make_hero(PLAYER2, "Гарен")
    db.update_character(CHAT, PLAYER2, alive=0, hp=0)
    ok, lines = spells.cast(CHAT, c, "Лечение ран", targets=["Гарен"])
    assert any("мёртв" in l for l in lines) and db.get_character(CHAT, PLAYER2)["alive"] == 0


def test_mass_healing_word_heals_up_to_six_most_wounded(monkeypatch):
    make_world()
    c = cleric(level=5)
    db.update_character(CHAT, PLAYER, prepared=["Массовое лечащее слово"])
    for i in range(3):
        h = make_hero(20 + i, f"Б{i}")
        db.update_character(CHAT, 20 + i, hp=1)
    fixed_dice(monkeypatch, 2)
    ok, _ = spells.cast(CHAT, db.get_character(CHAT, PLAYER), "Массовое лечащее слово")
    assert ok and all(db.get_character(CHAT, 20 + i)["hp"] > 1 for i in range(3))


def test_beacon_of_hope_maximizes_healing(monkeypatch):
    make_world()
    c = cleric(level=5)
    hero = make_hero(PLAYER2, "Гарен")
    db.update_character(CHAT, PLAYER2, hp=1)
    engine.add_pc_condition(CHAT, db.get_character(CHAT, PLAYER2), "маяк надежды", rounds=10)
    fixed_dice(monkeypatch, 1)
    spells.cast(CHAT, c, "Лечение ран", targets=["Гарен"])
    # 1d8 максимум = 8 + 3 (МДР) + 3 (ученик жизни 2 + ячейка 1) = 14 → хиты 1 + 14, но не выше максимума
    assert db.get_character(CHAT, PLAYER2)["hp"] == min(hero["max_hp"], 15)


def test_prayer_of_healing_only_out_of_combat(monkeypatch):
    make_world()
    c = cleric(level=3)
    db.update_character(CHAT, PLAYER, prepared=["Молитва исцеления"])
    make_enemy()
    fixed_d20(monkeypatch, 20, 1)
    combat.start(CHAT)
    ok, lines = spells.cast(CHAT, db.get_character(CHAT, PLAYER), "Молитва исцеления")
    assert not ok and "в бою" in lines[0]


# ---------------------------------------------------------------- усиления и эффекты

def test_bless_targets_and_bonus_on_attacks_and_saves(monkeypatch):
    make_world()
    c = cleric(level=1)
    make_hero(PLAYER2, "Гарен")
    ok, _ = spells.cast(CHAT, c, "Благословение", targets=["Мирра", "Гарен"])
    assert ok
    for uid in (PLAYER, PLAYER2):
        assert "благословлён" in rules.cond_names(rules.conditions_of(db.get_character(CHAT, uid)))
    assert db.get_character(CHAT, PLAYER)["concentration"] == "Благословение"
    fixed_dice(monkeypatch, 4)
    fixed_d20(monkeypatch, 10)
    result = engine.pc_save(CHAT, db.get_character(CHAT, PLAYER2), "Мудрость", 99)
    assert "+4 (Благословение)" in result["text"]


def test_shield_spell_adds_five_ac_and_uses_reaction(monkeypatch):
    make_world()
    w = wizard(level=1)
    make_enemy()
    fixed_d20(monkeypatch, 20, 1)
    combat.start(CHAT)
    combat._save_turn(CHAT, combat._fresh_turn(PLAYER))
    before = engine.gear(CHAT, w)["ac"]
    ok, _ = spells.cast(CHAT, w, "Щит")
    assert ok and engine.gear(CHAT, db.get_character(CHAT, PLAYER))["ac"] == before + 5
    db.update_character(CHAT, PLAYER, slots_used={})
    ok, lines = spells.cast(CHAT, db.get_character(CHAT, PLAYER), "Щит")
    assert not ok and "Реакция" in lines[0]


def test_mage_armor_sets_base_ac_and_fails_with_armor():
    make_world()
    w = wizard(level=1, gear=False)
    ok, _ = spells.cast(CHAT, w, "Доспехи мага")
    assert ok
    assert engine.gear(CHAT, db.get_character(CHAT, PLAYER))["ac"] == 13 + rules.mod_of(w, "Ловкость")
    # союзник в доспехе: заклинание не действует; сам волшебник в доспехе без мастерства колдовать не может
    db.reset_game(CHAT)
    make_world()
    w = wizard(level=1)
    make_hero(PLAYER2, "Рурик")                                # воин в кольчуге и со щитом
    ok, lines = spells.cast(CHAT, db.get_character(CHAT, PLAYER), "Доспехи мага", targets=["Рурик"])
    assert any("носит доспех" in l for l in lines)
    assert "доспехи мага" not in rules.cond_names(rules.conditions_of(db.get_character(CHAT, PLAYER2)))


def test_aid_raises_max_hp_and_long_rest_removes_it():
    import features
    make_world()
    c = cleric(level=3)
    hero = make_hero(PLAYER2, "Гарен")
    db.update_character(CHAT, PLAYER, prepared=["Помощь"])
    spells.cast(CHAT, db.get_character(CHAT, PLAYER), "Помощь", targets=["Гарен"])
    assert db.get_character(CHAT, PLAYER2)["max_hp"] == hero["max_hp"] + 5
    features.long_rest(CHAT)
    assert db.get_character(CHAT, PLAYER2)["max_hp"] == hero["max_hp"]


def test_lesser_restoration_removes_poison():
    make_world()
    c = cleric(level=3)
    hero = make_hero(PLAYER2, "Гарен")
    engine.add_pc_condition(CHAT, hero, "отравлен", rounds=10)
    db.update_character(CHAT, PLAYER, prepared=["Малое восстановление"])
    ok, _ = spells.cast(CHAT, db.get_character(CHAT, PLAYER), "Малое восстановление", targets=["Гарен"])
    assert ok and "отравлен" not in rules.cond_names(rules.conditions_of(db.get_character(CHAT, PLAYER2)))


def test_spare_the_dying_stabilizes():
    make_world()
    c = cleric(level=1)
    hero = make_hero(PLAYER2, "Гарен")
    engine.pc_damage(CHAT, hero, hero["max_hp"] + 1)
    ok, _ = spells.cast(CHAT, c, "Сохранение жизни", targets=["Гарен"])
    assert ok and db.get_character(CHAT, PLAYER2)["death_successes"] == 3


def test_revivify_only_right_after_death():
    make_world()
    c = cleric(level=5)
    hero = make_hero(PLAYER2, "Гарен")
    db.update_character(CHAT, PLAYER2, alive=0, hp=0, died_scene=0)
    db.save_situation(CHAT, "сцена 1")
    db.update_character(CHAT, PLAYER, prepared=["Возвращение к жизни"])
    ok, lines = spells.cast(CHAT, db.get_character(CHAT, PLAYER), "Возвращение к жизни", targets=["Гарен"])
    assert any("слишком давно" in l for l in lines) and db.get_character(CHAT, PLAYER2)["alive"] == 0
    db.update_character(CHAT, PLAYER2, died_scene=1)
    ok, _ = spells.cast(CHAT, db.get_character(CHAT, PLAYER), "Возвращение к жизни", targets=["Гарен"])
    assert ok and db.get_character(CHAT, PLAYER2)["alive"] == 1 and db.get_character(CHAT, PLAYER2)["hp"] == 1


def test_spiritual_weapon_first_cast_then_bonus_reuse_without_slot(monkeypatch):
    make_world()
    c = cleric(level=3)
    enemy = make_enemy(hp=200, ac=5)
    fixed_d20(monkeypatch, 15)
    fixed_dice(monkeypatch, 4)
    ok, lines = spells.cast(CHAT, c, "Духовное оружие")
    assert ok and used_slots() == {2: 1}
    first_hp = db.get_enemy(enemy["id"])["hp"]
    assert first_hp < 200
    fixed_d20(monkeypatch, 15)
    ok, _ = spells.cast(CHAT, db.get_character(CHAT, PLAYER), "Духовное оружие")     # без ячейки
    assert ok and used_slots() == {2: 1} and db.get_enemy(enemy["id"])["hp"] < first_hp


def test_spirit_guardians_damage_enemies_on_their_turn(monkeypatch):
    make_world()
    c = cleric(level=5)
    db.update_character(CHAT, PLAYER, prepared=["Духовные стражи"])
    enemy = make_enemy(hp=100, attack=-50, save_bonus=0)
    spells.cast(CHAT, db.get_character(CHAT, PLAYER), "Духовные стражи", slot=3)
    assert db.get_character(CHAT, PLAYER)["concentration"] == "Духовные стражи"
    fixed_dice(monkeypatch, 4)
    fixed_d20(monkeypatch, 1)
    combat.enemy_turn(CHAT, db.get_enemy(enemy["id"]))
    assert db.get_enemy(enemy["id"])["hp"] == 100 - 12                          # 3d8 по 4, спасбросок провален


def test_narrative_spell_consumes_slot_and_logs():
    make_world()
    w = wizard(level=1, prepared=["Маскировка"])
    ok, lines = spells.cast(CHAT, w, "Маскировка")
    assert ok and used_slots() == {1: 1}
    assert any("Маскировка" in a["text"] for a in db.pending_actions(CHAT, kind="event"))


def test_casting_is_logged_for_the_scene(monkeypatch):
    make_world()
    w = wizard(level=1, prepared=["Волшебная стрела"])
    make_enemy(hp=100)
    fixed_dice(monkeypatch, 3)
    spells.cast(CHAT, w, "Волшебная стрела")
    assert any("Волшебная стрела" in a["text"] for a in db.pending_actions(CHAT, kind="event"))


def test_action_economy_blocks_second_action_spell(monkeypatch):
    make_world()
    w = wizard(level=1, prepared=["Волшебная стрела"])
    make_enemy(hp=100)
    fixed_d20(monkeypatch, 20, 1)
    combat.start(CHAT)
    combat._save_turn(CHAT, combat._fresh_turn(PLAYER))
    assert spells.cast(CHAT, w, "Волшебная стрела")[0]
    db.update_character(CHAT, PLAYER, slots_used={})
    ok, lines = spells.cast(CHAT, db.get_character(CHAT, PLAYER), "Волшебная стрела")
    assert not ok and "Действие" in lines[0]
    assert used_slots() == {}                                                    # ячейка не потрачена
