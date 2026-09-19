"""Бой (гл. 9): инициатива, ходы с действием и бонусным действием, атаки, ходы противников,
спасброски от смерти, опыт.

Работает поверх db, rules и engine, ничего не знает о Telegram. Функции возвращают строки
для чата (HTML); важные события пишутся в журнал сцены, чтобы следующая сцена их учла.
"""

import random

import db
import dice
import engine
import rules
import srd
from engine import esc, log
from srd import CON, DEX, STR, WIS

# ---------------------------------------------------------------- состояние хода


def _fresh_turn(uid: int) -> dict:
    return {"uid": uid, "action": 0, "bonus": 0, "surge": 0, "bonus_spell": 0, "leveled_spell": 0,
            "sneak": 0, "divine_strike": 0, "haste_action": 0, "attacks_left": 0}


def in_combat(chat_id: int) -> bool:
    return db.get_combat(chat_id) is not None


def current_actor(chat_id: int) -> dict | None:
    combat = db.get_combat(chat_id)
    if combat is None or not combat["order"]:
        return None
    return combat["order"][combat["turn_index"] % len(combat["order"])]


def turn_state(chat_id: int) -> dict:
    combat = db.get_combat(chat_id)
    return dict(combat["state"].get("turn", {})) if combat else {}


def _save_turn(chat_id: int, turn: dict) -> None:
    combat = db.get_combat(chat_id)
    if combat is None:
        return
    state = combat["state"]
    state["turn"] = turn
    db.set_combat_state(chat_id, state)


def turn_error(chat_id: int, user_id: int) -> str | None:
    """None — вне боя или сейчас ход этого игрока; иначе текст отказа."""
    if not in_combat(chat_id):
        return None
    actor = current_actor(chat_id)
    if actor and actor["type"] == "pc" and actor["user_id"] == user_id:
        return None
    return f"⏳ Сейчас ход: {esc(actor['name']) if actor else '…'}"


def use_action(chat_id: int, user_id: int, haste_ok: bool = False) -> str | None:
    """Тратит действие хода. Вне боя ограничений нет. Возвращает текст отказа или None.
    haste_ok — действие подходит для дополнительного действия Ускорения (только одна атака)."""
    if not in_combat(chat_id):
        return None
    error = turn_error(chat_id, user_id)
    if error:
        return error
    turn = turn_state(chat_id)
    if not turn.get("action"):
        turn["action"] = 1
        _save_turn(chat_id, turn)
        return None
    if haste_ok and turn.get("haste_action"):
        turn["haste_action"] = 0
        _save_turn(chat_id, turn)
        return None
    return "Действие в этом ходу уже потрачено. Осталось бонусное действие или /endturn."


def use_bonus(chat_id: int, user_id: int) -> str | None:
    if not in_combat(chat_id):
        return None
    error = turn_error(chat_id, user_id)
    if error:
        return error
    turn = turn_state(chat_id)
    if turn.get("bonus"):
        return "Бонусное действие в этом ходу уже потрачено."
    turn["bonus"] = 1
    _save_turn(chat_id, turn)
    return None


def mark_spell(chat_id: int, user_id: int, time_: str, leveled: bool) -> str | None:
    """Правило одного заклинания за ход (с. 83): после заклинания бонусным действием — только заговор."""
    if not in_combat(chat_id):
        return None
    turn = turn_state(chat_id)
    if leveled:
        if time_ == "action" and turn.get("bonus_spell"):
            return "Вы колдовали заклинанием бонусным действием — в этот ход действием можно только заговор."
        if time_ == "bonus" and turn.get("leveled_spell"):
            return "Вы уже колдовали заклинанием с ячейкой — бонусным действием можно только заговор."
    return None


def note_spell(chat_id: int, time_: str, leveled: bool) -> None:
    if not in_combat(chat_id):
        return
    turn = turn_state(chat_id)
    if leveled:
        turn["leveled_spell"] = 1
        if time_ == "bonus":
            turn["bonus_spell"] = 1
    _save_turn(chat_id, turn)


def reaction_used(chat_id: int, uid: int) -> bool:
    combat = db.get_combat(chat_id)
    return bool(combat and combat["state"].get("reactions", {}).get(str(uid)) == combat["round"])


def use_reaction(chat_id: int, uid: int) -> bool:
    """True, если реакция свободна (и теперь потрачена до конца раунда)."""
    combat = db.get_combat(chat_id)
    if combat is None:
        return True
    state = combat["state"]
    reactions = state.setdefault("reactions", {})
    if reactions.get(str(uid)) == combat["round"]:
        return False
    reactions[str(uid)] = combat["round"]
    db.set_combat_state(chat_id, state)
    return True


# ---------------------------------------------------------------- инициатива и порядок ходов

def _base_name(name: str) -> str:
    parts = name.rsplit(" ", 1)
    return parts[0] if len(parts) == 2 and parts[1].isdigit() else name


def start(chat_id: int) -> list[dict]:
    """Бросает инициативу (проверка ЛОВ). Одинаковые противники ходят вместе (с. 72)."""
    order = []
    for c in db.list_characters(chat_id, alive_only=True):
        conds = rules.cond_names(rules.conditions_of(c))
        disadvs = []
        if rules.exhaustion_of(c) >= 1:
            disadvs.append("истощение")
        if conds & srd.CHECK_DISADV:
            disadvs.append("состояние")
        mode, _ = rules.combine_mode([], disadvs)
        _, total, _ = dice.d20_check(rules.initiative_bonus(c), mode, lucky=rules.race_info(c)["lucky"])
        order.append({"type": "pc", "user_id": c["user_id"], "name": c["name"], "init": total,
                      "dex": rules.mod_of(c, DEX)})
    group_rolls: dict[str, int] = {}
    for e in db.list_enemies(chat_id):
        base = _base_name(e["name"])
        if base not in group_rolls:
            group_rolls[base] = dice.d20()
        order.append({"type": "enemy", "id": e["id"], "name": e["name"],
                      "init": group_rolls[base] + e["initiative_bonus"], "dex": e["initiative_bonus"]})
    # При равной инициативе игроки ходят раньше противников; далее по ЛОВ (с. 72)
    order.sort(key=lambda x: (-x["init"], x["type"] == "enemy", -x["dex"]))
    db.set_combat(chat_id, 1, 0, order, {"turn": {}, "reactions": {}, "xp_pool": 0, "defeated": []})
    log(chat_id, "Бой", "Начался бой: " + ", ".join(x["name"] for x in order))
    return order


def advance(chat_id: int) -> None:
    combat = db.get_combat(chat_id)
    if combat is None:
        return
    index = combat["turn_index"] + 1
    round_ = combat["round"]
    if index >= len(combat["order"]):
        index = 0
        round_ += 1
    state = combat["state"]
    state["turn"] = {}
    db.set_combat(chat_id, round_, index, combat["order"], state)


def format_order(chat_id: int) -> str:
    combat = db.get_combat(chat_id)
    if combat is None:
        return ""
    current = combat["turn_index"] % len(combat["order"])
    lines = [f"⚔️ <b>Раунд {combat['round']}</b> — порядок ходов:"]
    for i, actor in enumerate(combat["order"]):
        icon = "🧝" if actor["type"] == "pc" else "👹"
        marker = "▶️ " if i == current else "   "
        lines.append(f"{marker}{icon} {esc(actor['name'])} ({actor['init']})")
    return "\n".join(lines)


def record_defeat(chat_id: int, enemy) -> list[str]:
    """Учитывает победу над противником: в бою опыт копится до конца боя, вне боя выдаётся сразу."""
    combat = db.get_combat(chat_id)
    if combat is None:
        return engine.split_xp(chat_id, enemy["xp"], enemy["name"])
    state = combat["state"]
    state["xp_pool"] = state.get("xp_pool", 0) + enemy["xp"]
    state.setdefault("defeated", []).append(enemy["name"])
    db.set_combat_state(chat_id, state)
    return []


def cleanup_after_combat(chat_id: int) -> None:
    """Короткие эффекты (до минуты) заканчиваются вместе с боем."""
    for c in db.list_characters(chat_id):
        conds = rules.conditions_of(c)
        kept = [x for x in conds if x["rounds"] is None or x["rounds"] > 10]
        fields: dict = {}
        if len(kept) != len(conds):
            fields["conditions"] = kept
        if c["concentration"] and not any(x.get("spell") == c["concentration"] for x in kept):
            fields["concentration"] = ""
        if fields:
            db.update_character(chat_id, c["user_id"], **fields)


def end(chat_id: int, outcome: str) -> list[str]:
    combat = db.get_combat(chat_id)
    pool = combat["state"].get("xp_pool", 0) if combat else 0
    lines: list[str] = []
    db.clear_combat(chat_id)
    db.clear_dead_enemies(chat_id)
    cleanup_after_combat(chat_id)
    log(chat_id, "Бой", f"Бой окончен: {outcome}")
    if pool:
        lines += engine.split_xp(chat_id, pool, "победу в бою")
    return lines


# ---------------------------------------------------------------- атака персонажа

def _other_ally_conscious(chat_id: int, character) -> bool:
    return any(c["user_id"] != character["user_id"] and c["hp"] > 0
               for c in db.list_characters(chat_id, alive_only=True))


def attack_action(chat_id: int, character, enemy) -> tuple[list[str], bool]:
    """Действие Атака: одна атака или несколько (Дополнительная атака воина, с. 27).
    Возвращает (строки отчёта, был ли повержен хоть один противник)."""
    lines: list[str] = []
    any_defeated = False
    attacks = rules.attacks_per_action(character)
    target = enemy
    first = True
    for i in range(attacks):
        character = engine.refresh(chat_id, character)
        if target is None or not db.get_enemy(target["id"])["alive"]:
            alive = db.list_enemies(chat_id)
            if not alive:
                break
            target = alive[0]
            lines.append(f"↪️ Цель повержена — следующая: <b>{esc(target['name'])}</b>")
        target = db.get_enemy(target["id"])
        attack_lines, defeated = _single_attack(chat_id, character, target, first)
        lines += attack_lines
        any_defeated |= defeated
        if defeated:
            lines += record_defeat(chat_id, target)
        first = False
    if attacks > 1 and not any(l for l in lines):
        lines.append("Атаковать некого.")
    return lines, any_defeated


def _single_attack(chat_id: int, character, enemy, first_attack: bool) -> tuple[list[str], bool]:
    g = engine.gear(chat_id, character)
    profile = g["profile"]
    melee = not profile["ranged"]
    mode, reason = engine.pc_attack_mode(character, enemy, melee, g)
    info = rules.race_info(character)
    d, total, all_dice = dice.d20_check(profile["attack"], mode, lucky=info["lucky"])
    extra_bonus = ""
    names = rules.cond_names(g["conds"])
    if "благословлён" in names:
        bless = dice.roll(1, 4)[0]
        total += bless
        extra_bonus = f" +{bless} (Благословение)"
    name, target = esc(character["name"]), esc(enemy["name"])
    weapon_name = profile["weapon"]["name"]
    rolls = f"[{'/'.join(map(str, all_dice))}] " if len(all_dice) > 1 else ""
    header = (
        f"⚔️ <b>{name}</b> → <b>{target}</b> ({esc(weapon_name)}): d20 {rolls}{d} "
        f"{rules.format_modifier(profile['attack'])}{extra_bonus} = <b>{total}</b> против КД {enemy['armor_class']}"
        f"{engine.describe_mode(mode, reason)}"
    )
    lines = [header]
    theirs = rules.cond_names(engine.enemy_conditions(enemy))
    crit_by_state = melee and bool(theirs & srd.MELEE_AUTO_CRIT)
    natural_crit = d >= profile["crit_range"]
    hit = natural_crit or (d != 1 and total >= enemy["armor_class"])

    # Одноразовые эффекты расходуются на броске атаки
    engine.consume_pc_flags(chat_id, character)
    if "отмечен" in theirs:
        engine.remove_enemy_condition(enemy, "отмечен")

    if not hit:
        lines.append("💀 Критический промах!" if d == 1 else "❌ Промах")
        log(chat_id, character["name"], f"атакует {enemy['name']} и промахивается")
        return lines, False

    crit = natural_crit or crit_by_state
    extra: list[str] = []
    turn = turn_state(chat_id)
    sneak_note = ""
    dice_count = rules.sneak_dice(character)
    if dice_count and profile["sneak_ok"] and not turn.get("sneak"):
        allowed = mode > 0 or (mode == 0 and _other_ally_conscious(chat_id, character))
        if allowed:
            extra.append(f"{dice_count}d6")
            sneak_note = " (скрытая атака)"
            if in_combat(chat_id):
                turn["sneak"] = 1
    if character["char_class"] == "Жрец" and character["level"] >= 8 and not turn.get("divine_strike"):
        extra.append("2d8" if character["level"] >= 14 else "1d8")
        sneak_note += " (божественный удар)"
        if in_combat(chat_id):
            turn["divine_strike"] = 1
    if in_combat(chat_id):
        _save_turn(chat_id, turn)
    damage, detail = rules.roll_weapon_damage(profile, crit, extra)
    _, updated, defeated = engine.enemy_damage(chat_id, enemy, damage)
    prefix = "💥 Критическое попадание!" if crit else "✅ Попадание!"
    dtype = f" {esc(profile['dtype'])}" if profile["dtype"] else ""
    lines.append(f"{prefix} Урон{sneak_note}: {detail} = <b>{damage}</b>{dtype}")
    if defeated:
        lines.append(f"☠️ <b>{target}</b> повержен!")
        log(chat_id, character["name"], f"наносит {damage} урона и побеждает {enemy['name']}")
    else:
        lines.append(f"👹 {target}: {updated['hp']}/{updated['max_hp']} HP")
        log(chat_id, character["name"], f"наносит {enemy['name']} {damage} урона (осталось {updated['hp']} HP)")
    return lines, defeated


# ---------------------------------------------------------------- атака противника

def _roll_enemy_damage(notation: str, crit: bool) -> tuple[int, str]:
    rolled = dice.roll_notation(notation, double_dice=crit)
    if rolled is None:
        try:
            value = int(notation)
        except ValueError:
            value = 1
        return max(1, value), str(value)
    total, results, mod = rolled
    detail = " + ".join(map(str, results)) + (f" {rules.format_modifier(mod)}" if mod else "")
    return max(1, total), detail


def enemy_attack(chat_id: int, enemy, target) -> tuple[list[str], object]:
    """Одна атака противника по персонажу. Возвращает (строки, обновлённый персонаж)."""
    g = engine.gear(chat_id, target)
    mode, reason = engine.enemy_attack_mode(enemy, target, melee=True)
    d, total, all_dice = dice.d20_check(enemy["attack_bonus"], mode)
    attacker, name = esc(enemy["name"]), esc(target["name"])
    rolls = f"[{'/'.join(map(str, all_dice))}] " if len(all_dice) > 1 else ""
    lines = [
        f"👹 <b>{attacker}</b> → <b>{name}</b>: d20 {rolls}{d} {rules.format_modifier(enemy['attack_bonus'])} = "
        f"<b>{total}</b> против КД {g['ac']}{engine.describe_mode(mode, reason)}"
    ]
    theirs = rules.cond_names(g["conds"])
    natural_crit = d == 20
    crit = natural_crit or (bool(theirs & srd.MELEE_AUTO_CRIT) and total >= g["ac"])
    hit = natural_crit or (d != 1 and total >= g["ac"])
    if not hit:
        lines.append("❌ Промах")
        log(chat_id, enemy["name"], f"атакует {target['name']} и промахивается")
        return lines, target
    damage, detail = _roll_enemy_damage(enemy["damage_dice"], crit)
    prefix = "💥 Критическое попадание!" if crit else "✅ Попадание!"
    # Невероятное уклонение плута (с. 30): реакция, половина урона
    if (target["char_class"] == "Плут" and target["level"] >= 5 and target["hp"] > 0
            and not (theirs & srd.INCAPACITATED)):
        if use_reaction(chat_id, target["user_id"]):
            damage = max(1, damage // 2)
            lines.append(f"🌀 Невероятное уклонение: урон вдвое")
    dtype = f" {esc(enemy['dtype'])}" if enemy["dtype"] else ""
    lines.append(f"{prefix} Урон: {detail} = <b>{damage}</b>{dtype}")
    more, updated = engine.pc_damage(chat_id, target, damage, enemy["dtype"], crit, enemy["name"])
    lines += more
    if updated["alive"] and updated["hp"] > 0:
        log(chat_id, enemy["name"], f"наносит {target['name']} {damage} урона (осталось {updated['hp']} HP)")
    else:
        log(chat_id, enemy["name"], f"наносит {target['name']} {damage} урона")
    # Эффект попадания (яд, паралич…) — спасбросок
    if enemy["effect_condition"] and updated["alive"]:
        result = engine.pc_save(chat_id, updated, enemy["effect_ability"] or CON, enemy["effect_dc"] or 11,
                                against=enemy["effect_condition"])
        lines.append(result["text"])
        if not result["success"]:
            updated = engine.add_pc_condition(chat_id, updated, enemy["effect_condition"], rounds=10,
                                              save={"ability": enemy["effect_ability"] or CON,
                                                    "dc": enemy["effect_dc"] or 11})
            lines.append(f"☣️ {name} — {esc(enemy['effect_condition'])}")
            log(chat_id, enemy["name"], f"{target['name']} получает состояние «{enemy['effect_condition']}»")
    return lines, updated


def _pick_target(chat_id: int, enemy, lines: list[str]):
    """Случайная цель среди персонажей в сознании; учитывает Убежище и очарование."""
    conscious = [c for c in db.list_characters(chat_id, alive_only=True) if c["hp"] > 0]
    conds = engine.enemy_conditions(enemy)
    charm = rules.find_condition(conds, "очарован")
    if charm and charm.get("src"):
        conscious = [c for c in conscious if c["user_id"] != charm["src"]] or []
    random.shuffle(conscious)
    for candidate in conscious:
        sanctuary = rules.find_condition(rules.conditions_of(candidate), "убежище")
        if sanctuary:
            dc = sanctuary["data"].get("dc", 13)
            result = engine.enemy_save(enemy, WIS, dc)
            lines.append(f"🕊 Убежище на {esc(candidate['name'])}: " + result["text"])
            if not result["success"]:
                continue
        return candidate
    return None


def enemy_turn(chat_id: int, enemy) -> list[str]:
    """Полный ход противника: длительности, ауры, состояния, атаки."""
    lines: list[str] = []
    name = esc(enemy["name"])
    conds, expired = rules.tick_conditions(engine.enemy_conditions(enemy))
    if expired:
        lines.append(f"⏱ {name}: закончилось — {', '.join(esc(x) for x in expired)}")
    enemy = db.update_enemy(enemy["id"], conditions=conds)

    # Духовные стражи (с. 88): урон в начале хода противника
    for c in db.list_characters(chat_id, alive_only=True):
        aura = rules.find_condition(rules.conditions_of(c), "духовные стражи")
        if aura and c["hp"] > 0 and enemy["alive"]:
            data = aura["data"]
            total, _, _ = dice.roll_notation(data["dice"]) or (0, [], 0)
            result = engine.enemy_save(enemy, WIS, data["dc"])
            dmg = total // 2 if result["success"] else total
            lines.append(f"✨ Духовные стражи {esc(c['name'])}: " + result["text"])
            more, enemy_after, defeated = engine.enemy_damage(chat_id, enemy, dmg)
            lines.append(f"   урон излучением {dmg}")
            lines += more
            enemy = enemy_after
            if defeated:
                lines += record_defeat(chat_id, enemy)
                return lines
            break

    conds = engine.enemy_conditions(enemy)
    names = rules.cond_names(conds)
    skipped = names & srd.INCAPACITATED or names & {"приказ", "внушение"}
    if "сбит с ног" in names:
        engine.remove_enemy_condition(enemy, "сбит с ног")
        enemy = db.get_enemy(enemy["id"])
        lines.append(f"🧎 {name} поднимается на ноги")
        names = rules.cond_names(engine.enemy_conditions(enemy))
    if "опутан" in names:
        entry = rules.find_condition(engine.enemy_conditions(enemy), "опутан")
        dc = (entry["save"] or {}).get("dc", 12) if entry else 12
        value, total, _ = dice.d20_check(enemy["save_bonus"])
        if total >= dc:
            engine.remove_enemy_condition(enemy, "опутан")
            lines.append(f"🕸 {name} вырывается из пут (проверка СИЛ {total} против {dc})")
        else:
            lines.append(f"🕸 {name} пытается освободиться и не может (СИЛ {total} против {dc})")
        return lines
    if skipped:
        lines.append(f"😶 {name} не может действовать ({esc(sorted(skipped)[0])})")
        # Повторный спасбросок в конце хода (с. 87: Удержание личности)
        for entry in engine.enemy_conditions(enemy):
            save = entry.get("save")
            if save and entry["name"] in ("парализован",):
                result = engine.enemy_save(enemy, save["ability"], save["dc"])
                lines.append(result["text"])
                if result["success"]:
                    engine.remove_enemy_condition(enemy, entry["name"])
                    lines.append(f"✅ {name} освобождается")
        return lines

    for _ in range(max(1, enemy["attacks"])):
        target = _pick_target(chat_id, enemy, lines)
        if target is None:
            lines.append(f"👹 {name} не находит, кого атаковать")
            break
        attack_lines, _ = enemy_attack(chat_id, enemy, target)
        lines += attack_lines
    return lines


# ---------------------------------------------------------------- начало хода персонажа

def death_save_turn(chat_id: int, character) -> list[str]:
    """Спасбросок от смерти в начале хода при 0 хитов (с. 79)."""
    name = esc(character["name"])
    if character["death_successes"] >= 3:
        return [f"😶 <b>{name}</b> стабилен и без сознания"]
    names = rules.cond_names(rules.conditions_of(character))
    result = rules.death_save(character["death_successes"], character["death_failures"],
                              advantage="маяк надежды" in names, lucky=rules.race_info(character)["lucky"])
    if result["revived"]:
        conds = rules.remove_condition(rules.conditions_of(character), "без сознания")
        db.update_character(chat_id, character["user_id"], hp=1, death_successes=0, death_failures=0,
                            conditions=conds)
        log(chat_id, character["name"], "приходит в себя с 1 HP")
        return [f"🌅 Спасбросок {name}: d20 = 20 — приходит в себя с 1 HP!"]
    fields = {"death_successes": result.get("successes", 0), "death_failures": result.get("failures", 0)}
    if result["dead"]:
        fields.update(alive=0, died_scene=db.current_situation_number(chat_id))
        db.update_character(chat_id, character["user_id"], **fields)
        log(chat_id, character["name"], "ПОГИБАЕТ")
        return [f"⚰️ Спасбросок {name}: d20 = {result['roll']} — <b>{name} погибает.</b>"]
    db.update_character(chat_id, character["user_id"], **fields)
    s, f = fields["death_successes"], fields["death_failures"]
    if result["stable"]:
        log(chat_id, character["name"], "стабилизирован, но без сознания")
        return [f"🕊 Спасбросок {name}: d20 = {result['roll']} — стабилизирован (без сознания)"]
    outcome = "успех" if result["roll"] >= 10 else "провал" + (" ×2" if result["roll"] == 1 else "")
    return [f"🎲 Спасбросок от смерти {name}: d20 = {result['roll']} — {outcome} (успехов {s}/3, провалов {f}/3)"]


def begin_player_turn(chat_id: int, character) -> list[str]:
    """Начало хода: длительности, Выживший чемпиона, сброс состояния хода."""
    lines: list[str] = []
    conds, expired = rules.tick_conditions(rules.conditions_of(character))
    if expired:
        lines.append(f"⏱ {esc(character['name'])}: закончилось — {', '.join(esc(x) for x in expired)}")
    db.update_character(chat_id, character["user_id"], conditions=conds)
    character = engine.refresh(chat_id, character)
    if character["char_class"] == "Воин" and character["level"] >= 18 and 0 < character["hp"] <= character["max_hp"] // 2:
        heal = 5 + rules.mod_of(character, CON)
        gained, character = engine.pc_heal(chat_id, character, max(1, heal))
        lines.append(f"💪 Выживший: {esc(character['name'])} восстанавливает {gained} хитов")
    turn = _fresh_turn(character["user_id"])
    if "ускорен" in rules.cond_names(rules.conditions_of(character)):
        turn["haste_action"] = 1
    _save_turn(chat_id, turn)
    return lines


# ---------------------------------------------------------------- бонусные действия: что доступно

def bonus_options(chat_id: int, character) -> list[str]:
    """Доступные бонусные и дополнительные действия персонажа сейчас."""
    from spelldata import SPELLS

    options: list[str] = []
    uses = rules.jload(character, "uses", {})
    turn = turn_state(chat_id)
    cls, lvl = character["char_class"], character["level"]
    if cls == "Воин":
        if not turn.get("bonus") and uses.get("second_wind", 0) < 1 and character["hp"] < character["max_hp"]:
            options.append("secondwind")
        if turn.get("action") and not turn.get("surge") and uses.get("action_surge", 0) < srd.action_surge_uses(lvl):
            options.append("surge")
    if cls == "Плут" and lvl >= 2 and not turn.get("bonus"):
        options.append("cunning")
    if not turn.get("bonus") and rules.is_caster(character):
        left = rules.slots_left(character)
        for name in rules.castable_spells(character):
            spell = SPELLS.get(name)
            if not spell or spell.get("time") != "bonus":
                continue
            names = rules.cond_names(rules.conditions_of(character))
            if spell["kind"] == "persistent" and spell["effect"] in names:
                options.append("cast_bonus")
                break
            if spell["level"] == 0 or (any(left.get(l, 0) > 0 for l in range(spell["level"], 10)) and not turn.get("leveled_spell")):
                options.append("cast_bonus")
                break
    if turn.get("haste_action"):
        options.append("haste")
    return options


def run_until_player(chat_id: int) -> tuple[list[str], bool]:
    """Отыгрывает ходы противников и спасброски от смерти до хода живого игрока.
    Возвращает (строки отчёта, бой окончен)."""
    lines: list[str] = []
    combat = db.get_combat(chat_id)
    if combat is None:
        return lines, True
    for _ in range(len(combat["order"]) * 3 + 3):
        combat = db.get_combat(chat_id)
        if combat is None:
            return lines, True
        if not db.list_enemies(chat_id):
            lines += end(chat_id, "победа отряда")
            lines.append("🏆 <b>Все противники повержены. Бой окончен!</b>")
            return lines, True
        able = [c for c in db.list_characters(chat_id, alive_only=True)
                if c["hp"] > 0]
        if not able:
            lines += end(chat_id, "отряд повержен")
            lines.append("☠️ <b>Никто из отряда не может сражаться. Бой окончен.</b>")
            return lines, True

        actor = combat["order"][combat["turn_index"] % len(combat["order"])]
        if actor["type"] == "enemy":
            enemy = db.get_enemy(actor["id"])
            if enemy is None or not enemy["alive"]:
                advance(chat_id)
                continue
            lines += enemy_turn(chat_id, enemy)
            advance(chat_id)
            continue

        character = db.get_character(chat_id, actor["user_id"])
        if character is None or not character["alive"]:
            advance(chat_id)
            continue
        if character["hp"] == 0:
            lines += death_save_turn(chat_id, character)
            advance(chat_id)
            continue
        lines += begin_player_turn(chat_id, character)
        lines.append(f"▶️ <b>Раунд {combat['round']}: ход {esc(character['name'])}</b>")
        return lines, False
    return lines, False


def end_turn(chat_id: int) -> tuple[list[str], bool]:
    """Завершает ход текущего персонажа и доигрывает до следующего игрока."""
    advance(chat_id)
    return run_until_player(chat_id)
