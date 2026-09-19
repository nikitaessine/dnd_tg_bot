import combat
import db
import dice
import engine
import rules
import srd
from conftest import CHAT, PLAYER, PLAYER2, equip, make_enemy, make_hero, make_world


def fixed_d20(monkeypatch, *values):
    """Кубики d20 выпадают по списку; после конца списка повторяется последнее значение."""
    import itertools
    seq = itertools.chain(values, itertools.repeat(values[-1]))
    monkeypatch.setattr(dice, "d20", lambda: next(seq))


def fixed_dice(monkeypatch, value):
    """Все кубики урона выпадают на value (но не больше числа граней)."""
    monkeypatch.setattr(dice, "roll", lambda count, sides: [min(value, sides)] * count)


# ---------------------------------------------------------------- инициатива и порядок

def test_initiative_players_win_ties_and_group_rolls_once(monkeypatch):
    make_world()
    make_hero(PLAYER, "Гарен")                    # ЛОВ 14 → +2
    make_enemy("Гоблин")
    make_enemy("Гоблин")                          # получит имя «Гоблин 2»
    fixed_d20(monkeypatch, 10, 12)                # Гарен: 10+2; группа гоблинов: 12+0
    order = combat.start(CHAT)
    assert [a["name"] for a in order] == ["Гарен", "Гоблин", "Гоблин 2"]
    assert order[1]["init"] == order[2]["init"] == 12       # одна проверка на группу (с. 72)
    assert combat.current_actor(CHAT)["name"] == "Гарен"


def test_turn_advances_and_round_counter(monkeypatch):
    make_world()
    make_hero()
    make_enemy()
    fixed_d20(monkeypatch, 10, 1)
    combat.start(CHAT)
    combat.advance(CHAT)
    assert combat.current_actor(CHAT)["type"] == "enemy"
    combat.advance(CHAT)
    state = db.get_combat(CHAT)
    assert state["round"] == 2 and state["turn_index"] == 0


def test_enemy_names_are_unique():
    make_world()
    a, b, c = make_enemy("Гоблин"), make_enemy("Гоблин"), make_enemy("Гоблин")
    assert [x["name"] for x in (a, b, c)] == ["Гоблин", "Гоблин 2", "Гоблин 3"]


# ---------------------------------------------------------------- атака персонажа

def test_hit_uses_weapon_dice_and_ability(monkeypatch):
    make_world()
    hero = make_hero()                            # Длинный меч, щит → 1d8 + СИЛ +3
    enemy = make_enemy(hp=30, ac=12)
    fixed_d20(monkeypatch, 15)                    # 15 + 5 = 20 ≥ 12
    fixed_dice(monkeypatch, 4)
    lines, defeated = combat.attack_action(CHAT, hero, enemy)
    assert not defeated
    assert db.get_enemy(enemy["id"])["hp"] == 30 - (4 + 3)
    assert "Попадание" in " ".join(lines)


def test_natural_one_always_misses_and_twenty_always_hits(monkeypatch):
    make_world()
    hero = make_hero()
    enemy = make_enemy(hp=30, ac=30)
    fixed_d20(monkeypatch, 1)
    lines, _ = combat.attack_action(CHAT, hero, enemy)
    assert db.get_enemy(enemy["id"])["hp"] == 30
    fixed_d20(monkeypatch, 20)
    fixed_dice(monkeypatch, 4)
    combat.attack_action(CHAT, hero, enemy)
    # крит: кубики ×2 → 2×4 + 3 = 11
    assert db.get_enemy(enemy["id"])["hp"] == 30 - 11


def test_champion_scores_critical_on_19(monkeypatch):
    make_world()
    hero = make_hero(level=3)
    enemy = make_enemy(hp=50, ac=30)              # без крита не попасть
    fixed_d20(monkeypatch, 19)
    fixed_dice(monkeypatch, 3)
    combat.attack_action(CHAT, hero, enemy)
    assert db.get_enemy(enemy["id"])["hp"] == 50 - (2 * 3 + 3)


def test_extra_attack_makes_two_attacks_and_retargets(monkeypatch):
    make_world()
    hero = make_hero(level=5)                     # 2 атаки за действие
    first = make_enemy("Гоблин", hp=3, ac=10)
    second = make_enemy("Орк", hp=30, ac=10)
    fixed_d20(monkeypatch, 15, 15)                # обе атаки попадают
    fixed_dice(monkeypatch, 5)
    lines, defeated = combat.attack_action(CHAT, hero, first)
    assert defeated
    assert not db.get_enemy(first["id"])["alive"]
    assert db.get_enemy(second["id"])["hp"] < 30    # вторая атака ушла в следующую цель
    assert any("следующая" in l for l in lines)


def test_advantage_from_paralyzed_and_unconscious_target_makes_melee_crit(monkeypatch):
    make_world()
    hero = make_hero()
    enemy = make_enemy(hp=100, ac=25)
    engine.add_enemy_condition(enemy, "парализован", rounds=5)
    enemy = db.get_enemy(enemy["id"])
    fixed_d20(monkeypatch, 13, 2)                 # преимущество: берётся 13; 13+5 = 18 < 25 — промах
    lines, _ = combat.attack_action(CHAT, hero, enemy)
    assert "преимущество" in " ".join(lines)
    fixed_d20(monkeypatch, 20, 20)                # нат. 20 попадает; критом и так; проверим удвоение
    fixed_dice(monkeypatch, 4)
    before = db.get_enemy(enemy["id"])["hp"]
    combat.attack_action(CHAT, hero, db.get_enemy(enemy["id"]))
    assert db.get_enemy(enemy["id"])["hp"] == before - (2 * 4 + 3)


def test_hit_on_paralyzed_target_within_reach_is_always_critical(monkeypatch):
    make_world()
    hero = make_hero()
    enemy = make_enemy(hp=100, ac=10)
    engine.add_enemy_condition(enemy, "парализован", rounds=5)
    fixed_d20(monkeypatch, 12, 12)                # преимущество, обычное попадание 12+5 ≥ 10
    fixed_dice(monkeypatch, 4)
    combat.attack_action(CHAT, hero, db.get_enemy(enemy["id"]))
    assert db.get_enemy(enemy["id"])["hp"] == 100 - (2 * 4 + 3)      # автоматический крит (с. 171)


def test_prone_target_melee_advantage_ranged_disadvantage():
    make_world()
    hero = make_hero()
    enemy = make_enemy()
    engine.add_enemy_condition(enemy, "сбит с ног", rounds=3)
    enemy = db.get_enemy(enemy["id"])
    g = engine.gear(CHAT, hero)
    assert engine.pc_attack_mode(hero, enemy, True, g)[0] == 1
    assert engine.pc_attack_mode(hero, enemy, False, g)[0] == -1


def test_poisoned_attacker_has_disadvantage_and_dodging_target_too():
    make_world()
    hero = make_hero()
    enemy = make_enemy()
    engine.add_pc_condition(CHAT, hero, "отравлен", rounds=5)
    g = engine.gear(CHAT, db.get_character(CHAT, PLAYER))
    assert engine.pc_attack_mode(hero, enemy, True, g)[0] == -1
    # преимущество и помеха одновременно → обычный бросок
    engine.add_enemy_condition(enemy, "ослеплён", rounds=3)
    g = engine.gear(CHAT, db.get_character(CHAT, PLAYER))
    assert engine.pc_attack_mode(hero, db.get_enemy(enemy["id"]), True, g)[0] == 0


def test_guiding_bolt_mark_gives_advantage_once(monkeypatch):
    make_world()
    hero = make_hero()
    enemy = make_enemy(hp=50, ac=12)
    engine.add_enemy_condition(enemy, "отмечен", rounds=3)
    fixed_d20(monkeypatch, 5, 18)                 # преимущество: берётся 18
    fixed_dice(monkeypatch, 2)
    combat.attack_action(CHAT, hero, db.get_enemy(enemy["id"]))
    assert "отмечен" not in rules.cond_names(engine.enemy_conditions(db.get_enemy(enemy["id"])))


# ---------------------------------------------------------------- скрытая атака (с. 29)

def rogue_setup():
    make_world()
    rogue = make_hero(PLAYER, "Тень", cls="Плут", level=3)     # 2d6 скрытой атаки
    return rogue


def test_sneak_attack_needs_advantage_or_ally(monkeypatch):
    rogue = rogue_setup()
    enemy = make_enemy(hp=100, ac=10)
    fixed_d20(monkeypatch, 15)
    fixed_dice(monkeypatch, 3)
    lines, _ = combat.attack_action(CHAT, rogue, enemy)          # союзников нет, преимущества нет
    assert "скрытая атака" not in " ".join(lines)
    make_hero(PLAYER2, "Лира")                                   # теперь есть союзник в сознании
    fixed_d20(monkeypatch, 15)
    lines, _ = combat.attack_action(CHAT, db.get_character(CHAT, PLAYER), db.get_enemy(enemy["id"]))
    assert "скрытая атака" in " ".join(lines)


def test_sneak_attack_once_per_turn_and_doubles_on_crit(monkeypatch):
    rogue = rogue_setup()
    make_hero(PLAYER2, "Лира")
    enemy = make_enemy(hp=200, ac=10)
    fixed_d20(monkeypatch, 15)
    fixed_dice(monkeypatch, 3)
    combat.start(CHAT)                                         # чтобы состояние хода существовало
    db.update_character(CHAT, PLAYER, hp=rogue["hp"])
    combat._save_turn(CHAT, combat._fresh_turn(PLAYER))
    before = db.get_enemy(enemy["id"])["hp"]
    combat.attack_action(CHAT, rogue, enemy)
    first = before - db.get_enemy(enemy["id"])["hp"]            # рапира 1d8 (3) + ЛОВ +3 + 2d6 (6) = 12
    assert first == 3 + 3 + 6
    before = db.get_enemy(enemy["id"])["hp"]
    fixed_d20(monkeypatch, 15)
    combat.attack_action(CHAT, db.get_character(CHAT, PLAYER), db.get_enemy(enemy["id"]))
    second = before - db.get_enemy(enemy["id"])["hp"]           # второй раз в ход — без скрытой атаки
    assert second == 3 + 3


def test_sneak_attack_not_with_heavy_weapon_and_not_with_disadvantage(monkeypatch):
    rogue = rogue_setup()
    make_hero(PLAYER2, "Лира")
    equip(PLAYER, "Дубинка")                                    # без finesse и не дальнобойное
    enemy = make_enemy(hp=100, ac=10)
    fixed_d20(monkeypatch, 15)
    lines, _ = combat.attack_action(CHAT, db.get_character(CHAT, PLAYER), enemy)
    assert "скрытая атака" not in " ".join(lines)
    equip(PLAYER, "Рапира")
    engine.add_pc_condition(CHAT, db.get_character(CHAT, PLAYER), "отравлен", rounds=5)
    fixed_d20(monkeypatch, 15, 15)
    lines, _ = combat.attack_action(CHAT, db.get_character(CHAT, PLAYER), db.get_enemy(enemy["id"]))
    assert "скрытая атака" not in " ".join(lines)               # помеха


# ---------------------------------------------------------------- урон персонажу и смерть

def test_damage_to_zero_makes_unconscious_and_prone():
    make_world()
    hero = make_hero()
    lines, hero = engine.pc_damage(CHAT, hero, hero["max_hp"] + 1)
    names = rules.cond_names(rules.conditions_of(hero))
    assert hero["hp"] == 0 and hero["alive"] == 1
    assert {"без сознания", "сбит с ног"} <= names
    assert any("без сознания" in l for l in lines)


def test_instant_death_by_massive_damage():
    make_world()
    hero = make_hero()
    _, hero = engine.pc_damage(CHAT, hero, hero["hp"] + hero["max_hp"])
    assert hero["alive"] == 0


def test_damage_while_unconscious_is_death_save_failure_and_crit_is_two():
    make_world()
    hero = make_hero()
    _, hero = engine.pc_damage(CHAT, hero, hero["max_hp"] + 2)
    _, hero = engine.pc_damage(CHAT, hero, 3)
    assert hero["death_failures"] == 1 and hero["alive"] == 1
    _, hero = engine.pc_damage(CHAT, hero, 3, crit=True)
    assert hero["alive"] == 0                                   # 1 + 2 = 3 провала


def test_temp_hp_absorb_damage():
    make_world()
    hero = make_hero()
    db.update_character(CHAT, PLAYER, temp_hp=5)
    _, hero = engine.pc_damage(CHAT, db.get_character(CHAT, PLAYER), 7)
    assert hero["temp_hp"] == 0 and hero["hp"] == hero["max_hp"] - 2


def test_healing_from_zero_wakes_and_resets_death_saves():
    make_world()
    hero = make_hero()
    _, hero = engine.pc_damage(CHAT, hero, hero["max_hp"] + 1)
    db.update_character(CHAT, PLAYER, death_failures=2, death_successes=1)
    gained, hero = engine.pc_heal(CHAT, db.get_character(CHAT, PLAYER), 4)
    assert hero["hp"] == 4 and hero["death_failures"] == 0 and hero["death_successes"] == 0
    assert "без сознания" not in rules.cond_names(rules.conditions_of(hero))


def test_healing_is_capped_at_maximum():
    make_world()
    hero = make_hero()
    db.update_character(CHAT, PLAYER, hp=hero["max_hp"] - 3)
    gained, hero = engine.pc_heal(CHAT, db.get_character(CHAT, PLAYER), 100)
    assert gained == 3 and hero["hp"] == hero["max_hp"]


def test_dwarf_resists_poison_damage_by_half():
    make_world()
    hero = make_hero(race="Дварф", subrace="Холмовой")
    lines, hero2 = engine.pc_damage(CHAT, hero, 10, dtype="яд")
    assert hero["max_hp"] - hero2["hp"] == 5


def test_concentration_check_on_damage(monkeypatch):
    make_world()
    wiz = make_hero(cls="Волшебник")
    db.update_character(CHAT, PLAYER, concentration="Благословение")
    engine.add_pc_condition(CHAT, db.get_character(CHAT, PLAYER), "благословлён", rounds=10,
                            src=PLAYER, spell="Благословение")
    fixed_d20(monkeypatch, 1)                                   # спасбросок ТЕЛ провален
    lines, wiz = engine.pc_damage(CHAT, db.get_character(CHAT, PLAYER), 3)
    assert wiz["concentration"] == ""
    assert "благословлён" not in rules.cond_names(rules.conditions_of(wiz))
    db.update_character(CHAT, PLAYER, concentration="Благословение")
    fixed_d20(monkeypatch, 20)
    _, wiz = engine.pc_damage(CHAT, db.get_character(CHAT, PLAYER), 3)
    assert wiz["concentration"] == "Благословение"


def test_unconscious_drops_concentration():
    make_world()
    wiz = make_hero(cls="Волшебник")
    db.update_character(CHAT, PLAYER, concentration="Паутина")
    _, wiz = engine.pc_damage(CHAT, db.get_character(CHAT, PLAYER), 100)
    assert wiz["concentration"] == ""


# ---------------------------------------------------------------- атаки противников

def test_enemy_hit_reduces_hp(monkeypatch):
    make_world()
    hero = make_hero()                            # КД 18 (кольчуга + щит)
    enemy = make_enemy(attack=8, damage="1d6")
    fixed_d20(monkeypatch, 15)                    # 15 + 8 = 23 ≥ 18
    fixed_dice(monkeypatch, 4)
    lines, hero2 = combat.enemy_attack(CHAT, enemy, hero)
    assert hero2["hp"] == hero["hp"] - 4


def test_enemy_misses_against_high_ac(monkeypatch):
    make_world()
    hero = make_hero()
    enemy = make_enemy(attack=0)
    fixed_d20(monkeypatch, 10)
    _, hero2 = combat.enemy_attack(CHAT, enemy, hero)
    assert hero2["hp"] == hero["hp"]


def test_enemy_natural_twenty_crits_and_doubles_dice(monkeypatch):
    make_world()
    hero = make_hero()
    enemy = make_enemy(attack=-20, damage="1d6")
    fixed_d20(monkeypatch, 20)
    fixed_dice(monkeypatch, 3)
    _, hero2 = combat.enemy_attack(CHAT, enemy, hero)
    assert hero["hp"] - hero2["hp"] == 6


def test_dodge_gives_disadvantage_to_attackers():
    make_world()
    hero = make_hero()
    engine.add_pc_condition(CHAT, hero, "уклоняется", rounds=1)
    enemy = make_enemy()
    assert engine.enemy_attack_mode(enemy, db.get_character(CHAT, PLAYER))[0] == -1


def test_attackers_have_advantage_against_unconscious_and_melee_crit(monkeypatch):
    make_world()
    hero = make_hero()
    _, hero = engine.pc_damage(CHAT, hero, hero["max_hp"] + 1)
    enemy = make_enemy(attack=10, damage="1d6")
    assert engine.enemy_attack_mode(enemy, hero)[0] == 1
    fixed_d20(monkeypatch, 12, 12)
    fixed_dice(monkeypatch, 3)
    _, hero2 = combat.enemy_attack(CHAT, enemy, hero)
    assert hero2["death_failures"] == 2               # удар по лежащему вблизи — критический (2 провала)


def test_uncanny_dodge_halves_damage_once_per_round(monkeypatch):
    make_world()
    rogue = make_hero(cls="Плут", level=5)
    make_hero(PLAYER2, "Лира")
    make_enemy(hp=50)
    fixed_d20(monkeypatch, 10, 10)
    combat.start(CHAT)
    enemy = db.list_enemies(CHAT)[0]
    db.update_enemy(enemy["id"], attack_bonus=20, damage_dice="10")
    fixed_d20(monkeypatch, 15, 15)
    _, r1 = combat.enemy_attack(CHAT, db.get_enemy(enemy["id"]), rogue)
    assert rogue["hp"] - r1["hp"] == 5                # 10 / 2
    fixed_d20(monkeypatch, 15)
    _, r2 = combat.enemy_attack(CHAT, db.get_enemy(enemy["id"]), db.get_character(CHAT, PLAYER))
    assert r1["hp"] - r2["hp"] == 10                  # реакция уже потрачена в этом раунде


def test_enemy_hit_effect_poisons_on_failed_save(monkeypatch):
    make_world()
    hero = make_hero()
    enemy = make_enemy(attack=20, damage="1", effect_condition="отравлен", effect_ability="Телосложение",
                       effect_dc=30)
    fixed_d20(monkeypatch, 10, 2)                     # попадание, спасбросок провален
    _, hero2 = combat.enemy_attack(CHAT, enemy, hero)
    assert "отравлен" in rules.cond_names(rules.conditions_of(hero2))


def test_multiattack_enemy_attacks_multiple_times(monkeypatch):
    make_world()
    make_hero()
    enemy = make_enemy(attack=-50, attacks=3)
    fixed_d20(monkeypatch, 5, 5, 5)
    lines = combat.enemy_turn(CHAT, enemy)
    assert sum("против КД" in l for l in lines) == 3


def test_enemy_does_not_target_charmer_and_sanctuary_blocks(monkeypatch):
    make_world()
    a = make_hero(PLAYER, "Гарен")
    b = make_hero(PLAYER2, "Лира")
    enemy = make_enemy(attack=-50)
    engine.add_enemy_condition(enemy, "очарован", rounds=None, src=PLAYER)
    lines: list[str] = []
    for _ in range(10):
        target = combat._pick_target(CHAT, db.get_enemy(enemy["id"]), lines)
        assert target["user_id"] == PLAYER2
    engine.add_pc_condition(CHAT, b, "убежище", rounds=10, data={"dc": 99})
    fixed_d20(monkeypatch, 1)
    assert combat._pick_target(CHAT, db.get_enemy(enemy["id"]), lines) is None    # спасбросок МДР провален


def test_paralyzed_enemy_skips_turn_and_can_save_at_end(monkeypatch):
    make_world()
    make_hero()
    enemy = make_enemy(hp=10)
    engine.add_enemy_condition(enemy, "парализован", rounds=5, save={"ability": "Мудрость", "dc": 5})
    fixed_d20(monkeypatch, 15)
    lines = combat.enemy_turn(CHAT, db.get_enemy(enemy["id"]))
    assert any("не может действовать" in l for l in lines)
    assert "парализован" not in rules.cond_names(engine.enemy_conditions(db.get_enemy(enemy["id"])))


def test_prone_enemy_stands_up_then_attacks(monkeypatch):
    make_world()
    make_hero()
    enemy = make_enemy(attack=-50)
    engine.add_enemy_condition(enemy, "сбит с ног", rounds=5)
    fixed_d20(monkeypatch, 5)
    lines = combat.enemy_turn(CHAT, db.get_enemy(enemy["id"]))
    assert any("поднимается" in l for l in lines)
    assert "сбит с ног" not in rules.cond_names(engine.enemy_conditions(db.get_enemy(enemy["id"])))


def test_restrained_enemy_spends_turn_breaking_free(monkeypatch):
    make_world()
    make_hero()
    enemy = make_enemy(save_bonus=0)
    engine.add_enemy_condition(enemy, "опутан", rounds=5, save={"ability": "Сила", "dc": 30})
    fixed_d20(monkeypatch, 5)
    lines = combat.enemy_turn(CHAT, db.get_enemy(enemy["id"]))
    assert "опутан" in rules.cond_names(engine.enemy_conditions(db.get_enemy(enemy["id"])))
    assert not any("против КД" in l for l in lines)


# ---------------------------------------------------------------- цикл боя, смерть, опыт

def test_run_until_player_processes_enemy_and_stops(monkeypatch):
    make_world()
    make_hero(max_hp=50) if False else make_hero()
    make_enemy(attack=0, damage="1")
    fixed_d20(monkeypatch, 1, 20)                     # игрок ходит вторым
    combat.start(CHAT)
    assert combat.current_actor(CHAT)["type"] == "enemy"
    fixed_d20(monkeypatch, 5, 5, 5)
    lines, over = combat.run_until_player(CHAT)
    assert not over and combat.current_actor(CHAT)["type"] == "pc"
    assert any("ход Гарен" in l for l in lines)


def test_unconscious_player_rolls_death_save_each_turn(monkeypatch):
    make_world()
    a = make_hero(PLAYER, "Гарен")
    b = make_hero(PLAYER2, "Лира")
    make_enemy(attack=-50)
    fixed_d20(monkeypatch, 20, 10, 1)                 # Гарен, Лира, гоблин
    combat.start(CHAT)
    engine.pc_damage(CHAT, a, a["max_hp"] + 1)
    fixed_d20(monkeypatch, 5)                         # провал спасброска от смерти
    lines, over = combat.run_until_player(CHAT)
    assert db.get_character(CHAT, PLAYER)["death_failures"] == 1
    assert combat.current_actor(CHAT)["name"] == "Лира"


def test_combat_ends_on_victory_and_splits_xp(monkeypatch):
    make_world()
    make_hero(PLAYER, "Гарен")
    make_hero(PLAYER2, "Лира")
    e1 = make_enemy("Гоблин", hp=1, cr=0.25)          # 50 XP
    e2 = make_enemy("Орк", hp=1, cr=0.5)              # 100 XP
    fixed_d20(monkeypatch, 15, 12, 1, 1)
    combat.start(CHAT)
    for e in (e1, e2):
        db.update_enemy(e["id"], hp=0, alive=0)
        combat.record_defeat(CHAT, e)
    lines, over = combat.run_until_player(CHAT)
    assert over and db.get_combat(CHAT) is None
    assert db.get_character(CHAT, PLAYER)["xp"] == 75          # 150 / 2
    assert db.get_character(CHAT, PLAYER2)["xp"] == 75
    assert any("Бой окончен" in l for l in lines)


def test_xp_outside_combat_is_split_immediately():
    make_world()
    make_hero(PLAYER, "Гарен")
    make_hero(PLAYER2, "Лира")
    enemy = make_enemy(hp=1, cr=1)                    # 200 XP
    lines = combat.record_defeat(CHAT, enemy)
    assert db.get_character(CHAT, PLAYER)["xp"] == 100 and db.get_character(CHAT, PLAYER2)["xp"] == 100
    assert lines


def test_level_up_from_xp_grants_hp_and_pending_asi():
    make_world()
    hero = make_hero()
    lines, hero = engine.grant_xp(CHAT, hero, 2700)   # уровень 4
    assert hero["level"] == 4 and hero["asi_pending"] == 1
    assert hero["max_hp"] == 12 + 3 * 8               # 10+2 на 1 ур. + три уровня по 6+2
    assert any("достигает 4 уровня" in l for l in lines)


def test_combat_ends_when_party_is_down(monkeypatch):
    make_world()
    hero = make_hero()
    make_enemy()
    fixed_d20(monkeypatch, 10, 1)
    combat.start(CHAT)
    engine.pc_damage(CHAT, hero, hero["max_hp"] + 1)
    lines, over = combat.run_until_player(CHAT)
    assert over and db.get_combat(CHAT) is None
    assert db.get_character(CHAT, PLAYER)["alive"] == 1


def test_short_conditions_end_with_combat(monkeypatch):
    make_world()
    hero = make_hero()
    engine.add_pc_condition(CHAT, hero, "благословлён", rounds=10, spell="Благословение")
    engine.add_pc_condition(CHAT, db.get_character(CHAT, PLAYER), "доспехи мага", rounds=None)
    db.update_character(CHAT, PLAYER, concentration="Благословение")
    fixed_d20(monkeypatch, 10)
    make_enemy()
    combat.start(CHAT)
    combat.end(CHAT, "тест")
    hero = db.get_character(CHAT, PLAYER)
    names = rules.cond_names(rules.conditions_of(hero))
    assert "благословлён" not in names and "доспехи мага" in names and hero["concentration"] == ""


# ---------------------------------------------------------------- экономика хода

def test_one_action_and_one_bonus_action_per_turn(monkeypatch):
    make_world()
    make_hero()
    make_enemy()
    fixed_d20(monkeypatch, 20, 1)
    combat.start(CHAT)
    combat._save_turn(CHAT, combat._fresh_turn(PLAYER))
    assert combat.use_action(CHAT, PLAYER) is None
    assert combat.use_action(CHAT, PLAYER) is not None
    assert combat.use_bonus(CHAT, PLAYER) is None
    assert combat.use_bonus(CHAT, PLAYER) is not None
    assert combat.use_action(CHAT, PLAYER2) is not None                 # чужой ход


def test_actions_are_free_outside_combat():
    make_world()
    make_hero()
    assert combat.use_action(CHAT, PLAYER) is None and combat.use_action(CHAT, PLAYER) is None


def test_one_leveled_spell_per_turn_rule(monkeypatch):
    make_world()
    make_hero()
    make_enemy()
    fixed_d20(monkeypatch, 20, 1)
    combat.start(CHAT)
    combat._save_turn(CHAT, combat._fresh_turn(PLAYER))
    combat.note_spell(CHAT, "bonus", True)                                # Лечащее слово
    assert combat.mark_spell(CHAT, PLAYER, "action", True) is not None    # заклинание с ячейкой действием — нельзя
    assert combat.mark_spell(CHAT, PLAYER, "action", False) is None       # заговор — можно


def test_bonus_options_by_class(monkeypatch):
    make_world()
    fighter = make_hero(PLAYER, "Гарен", level=2)
    rogue = make_hero(PLAYER2, "Тень", cls="Плут", level=2)
    make_enemy()
    fixed_d20(monkeypatch, 20, 19, 1)
    combat.start(CHAT)
    combat._save_turn(CHAT, {**combat._fresh_turn(PLAYER), "action": 1})
    db.update_character(CHAT, PLAYER, hp=fighter["max_hp"] - 3)
    opts = combat.bonus_options(CHAT, db.get_character(CHAT, PLAYER))
    assert "secondwind" in opts and "surge" in opts
    combat._save_turn(CHAT, combat._fresh_turn(PLAYER2))
    assert "cunning" in combat.bonus_options(CHAT, db.get_character(CHAT, PLAYER2))

