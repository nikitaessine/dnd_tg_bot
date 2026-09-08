"""Бой: инициатива, порядок ходов, атаки, спасброски от смерти.

Работает поверх db и rules, ничего не знает о Telegram. Все функции возвращают
готовые строки для чата, а важные события пишут в журнал сцены (kind='event'),
чтобы следующая сцена их учла.
"""

import html
import random

import db
import dice
import rules
from config import ATTR_DEX, UNARMED_DAMAGE


def esc(text) -> str:
    return html.escape(str(text), quote=False)


def log(chat_id: int, who: str, text: str) -> None:
    db.save_action(chat_id, who, text, kind="event")


# ---------------------------------------------------------------- инициатива и ходы

def start(chat_id: int) -> list[dict]:
    """Бросает инициативу всем живым участникам и сохраняет порядок ходов."""
    order = []
    for c in db.list_characters(chat_id, alive_only=True):
        init = dice.d20() + rules.modifier(rules.stats_of(c)[ATTR_DEX])
        order.append({"type": "pc", "user_id": c["user_id"], "name": c["name"], "init": init})
    for e in db.list_enemies(chat_id):
        init = dice.d20() + e["initiative_bonus"]
        order.append({"type": "enemy", "id": e["id"], "name": e["name"], "init": init})
    # При равной инициативе игроки ходят раньше противников
    order.sort(key=lambda x: (-x["init"], x["type"] == "enemy"))
    db.set_combat(chat_id, 1, 0, order)
    log(chat_id, "Бой", "Начался бой: " + ", ".join(x["name"] for x in order))
    return order


def current_actor(chat_id: int) -> dict | None:
    combat = db.get_combat(chat_id)
    if combat is None or not combat["order"]:
        return None
    return combat["order"][combat["turn_index"] % len(combat["order"])]


def advance(chat_id: int) -> None:
    combat = db.get_combat(chat_id)
    if combat is None:
        return
    index = combat["turn_index"] + 1
    round_ = combat["round"]
    if index >= len(combat["order"]):
        index = 0
        round_ += 1
    db.set_combat(chat_id, round_, index, combat["order"])


def end(chat_id: int, outcome: str) -> None:
    db.clear_combat(chat_id)
    db.clear_dead_enemies(chat_id)
    log(chat_id, "Бой", f"Бой окончен: {outcome}")


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


# ---------------------------------------------------------------- атаки

def player_attack(chat_id: int, character, enemy) -> tuple[list[str], bool]:
    """Атака персонажа по противнику. Возвращает (строки отчёта, противник повержен)."""
    stats = rules.stats_of(character)
    bonus, attr = rules.attack_bonus(character)
    weapon = db.equipped_item(chat_id, character["user_id"], "weapon")
    notation = weapon["value"] if weapon else UNARMED_DAMAGE
    weapon_name = weapon["name"] if weapon else "без оружия"

    d = dice.d20()
    total = d + bonus
    name, target = esc(character["name"]), esc(enemy["name"])
    lines = [
        f"⚔️ <b>{name}</b> атакует <b>{target}</b> ({esc(weapon_name)}): "
        f"d20 {d} {rules.format_modifier(bonus)} = <b>{total}</b> против КД {enemy['armor_class']}"
    ]
    crit = d == 20
    if d == 1:
        lines.append("💀 Критический промах!")
        log(chat_id, character["name"], f"атакует {enemy['name']} и критически промахивается")
        return lines, False
    if not crit and total < enemy["armor_class"]:
        lines.append("❌ Промах")
        log(chat_id, character["name"], f"атакует {enemy['name']} и промахивается")
        return lines, False

    damage, detail = rules.weapon_damage(notation, stats, crit=crit)
    new_hp = max(0, enemy["hp"] - damage)
    db.update_enemy(enemy["id"], hp=new_hp, alive=int(new_hp > 0))
    prefix = "💥 Критическое попадание! " if crit else "✅ Попадание! "
    lines.append(f"{prefix}Урон {esc(notation)} ({detail}) = <b>{damage}</b>")
    if new_hp == 0:
        lines.append(f"☠️ <b>{target}</b> повержен!")
        log(chat_id, character["name"], f"наносит {damage} урона и побеждает {enemy['name']}")
        return lines, True
    lines.append(f"👹 {target}: {new_hp}/{enemy['max_hp']} HP")
    log(chat_id, character["name"], f"наносит {enemy['name']} {damage} урона (осталось {new_hp} HP)")
    return lines, False


def enemy_attack(chat_id: int, enemy, target) -> list[str]:
    """Атака противника по персонажу игрока."""
    armor = db.equipped_item(chat_id, target["user_id"], "armor")
    armor_bonus = int(armor["value"]) if armor else 0
    ac = rules.armor_class(target, armor_bonus)
    d = dice.d20()
    total = d + enemy["attack_bonus"]
    attacker, name = esc(enemy["name"]), esc(target["name"])
    lines = [
        f"👹 <b>{attacker}</b> атакует <b>{name}</b>: "
        f"d20 {d} {rules.format_modifier(enemy['attack_bonus'])} = <b>{total}</b> против КД {ac}"
    ]
    crit = d == 20
    if d == 1 or (not crit and total < ac):
        lines.append("❌ Промах")
        log(chat_id, enemy["name"], f"атакует {target['name']} и промахивается")
        return lines
    rolled = dice.roll_notation(enemy["damage_dice"], double_dice=crit)
    damage = max(1, rolled[0]) if rolled else 1
    updated = db.adjust_hp(chat_id, target["user_id"], -damage)
    prefix = "💥 Критическое попадание! " if crit else "✅ Попадание! "
    lines.append(f"{prefix}Урон <b>{damage}</b> → {name}: {updated['hp']}/{updated['max_hp']} HP")
    if updated["hp"] == 0:
        lines.append(f"💀 <b>{name}</b> падает без сознания!")
        log(chat_id, enemy["name"], f"наносит {target['name']} {damage} урона, тот падает без сознания")
    else:
        log(chat_id, enemy["name"], f"наносит {target['name']} {damage} урона (осталось {updated['hp']} HP)")
    return lines


def award_xp(chat_id: int, enemy) -> list[str]:
    """Начисляет опыт за победу всем живым персонажам, сообщает о новых уровнях."""
    if enemy["xp"] <= 0:
        return []
    lines = [f"✨ Опыт за победу: +{enemy['xp']} каждому"]
    for c in db.list_characters(chat_id, alive_only=True):
        result = rules.apply_xp(c, enemy["xp"])
        db.update_character(
            chat_id, c["user_id"],
            level=result["level"], xp=result["xp"], max_hp=result["max_hp"], hp=result["hp"],
        )
        if result["gained"]:
            lines.append(
                f"🎉 <b>{esc(c['name'])}</b> достигает {result['level']} уровня! "
                f"Здоровье: {result['max_hp']} HP"
            )
            log(chat_id, c["name"], f"достигает {result['level']} уровня")
    return lines


# ---------------------------------------------------------------- спасброски

def death_save(chat_id: int, character) -> list[str]:
    name = esc(character["name"])
    if character["death_successes"] >= 3:
        return [f"😶 <b>{name}</b> стабилизирован и без сознания"]
    result = rules.death_save(character)
    fields = {
        "death_successes": result.get("successes", character["death_successes"]),
        "death_failures": result.get("failures", character["death_failures"]),
    }
    if result["revived"]:
        fields.update(hp=1, death_successes=0, death_failures=0)
        db.update_character(chat_id, character["user_id"], **fields)
        log(chat_id, character["name"], "приходит в себя с 1 HP")
        return [f"🌅 Спасбросок {name}: d20 = 20 — приходит в себя с 1 HP!"]
    if not result["alive"]:
        fields["alive"] = 0
        db.update_character(chat_id, character["user_id"], **fields)
        log(chat_id, character["name"], "ПОГИБАЕТ")
        return [f"⚰️ Спасбросок {name}: d20 = {result['roll']} — третий провал. <b>{name} погибает.</b>"]
    db.update_character(chat_id, character["user_id"], **fields)
    s, f = fields["death_successes"], fields["death_failures"]
    if result["stable"]:
        log(chat_id, character["name"], "стабилизирован, но без сознания")
        return [f"🕊 Спасбросок {name}: d20 = {result['roll']} — стабилизирован (без сознания)"]
    outcome = "успех" if result["roll"] >= 10 else "провал"
    return [f"🎲 Спасбросок {name}: d20 = {result['roll']} — {outcome} (успехов {s}/3, провалов {f}/3)"]


# ---------------------------------------------------------------- цикл боя

def run_until_player(chat_id: int) -> tuple[list[str], bool]:
    """Отыгрывает ходы противников и спасброски, пока не дойдёт до хода живого игрока
    или бой не закончится. Возвращает (строки отчёта, бой окончен)."""
    lines: list[str] = []
    combat = db.get_combat(chat_id)
    if combat is None:
        return lines, True
    for _ in range(len(combat["order"]) * 2 + 2):
        combat = db.get_combat(chat_id)
        if combat is None:
            return lines, True
        if not db.list_enemies(chat_id):
            end(chat_id, "победа отряда")
            lines.append("🏆 <b>Все противники повержены. Бой окончен!</b>")
            return lines, True
        conscious = [c for c in db.list_characters(chat_id, alive_only=True) if c["hp"] > 0]
        if not conscious:
            end(chat_id, "отряд повержен")
            lines.append("☠️ <b>Никто из отряда не может сражаться. Бой окончен.</b>")
            return lines, True

        actor = combat["order"][combat["turn_index"] % len(combat["order"])]
        if actor["type"] == "enemy":
            enemy = db.get_enemy(actor["id"])
            if enemy is None or not enemy["alive"]:
                advance(chat_id)
                continue
            target = random.choice(conscious)
            lines += enemy_attack(chat_id, enemy, target)
            advance(chat_id)
            continue

        character = db.get_character(chat_id, actor["user_id"])
        if character is None or not character["alive"]:
            advance(chat_id)
            continue
        if character["hp"] == 0:
            lines += death_save(chat_id, character)
            advance(chat_id)
            continue
        lines.append(f"▶️ <b>Раунд {combat['round']}: ход {esc(character['name'])}</b>")
        return lines, False
    return lines, False
