"""SQLite-хранилище. Одна игра = один чат Telegram.

Схема создаётся при первом подключении; колонки, добавленные позже, дописываются
миграцией, так что старые базы продолжают работать без потери кампании.
"""

import json
import sqlite3
import time

import srd
from config import DB_PATH, DEFAULT_DIFFICULTY

_conn: sqlite3.Connection | None = None
SCHEMA_VERSION = 3  # 2: опыт хранится суммарно (таблица правил); 3: правила Basic Rules

_SCHEMA = f"""
CREATE TABLE IF NOT EXISTS games (
    chat_id INTEGER PRIMARY KEY,
    theme TEXT NOT NULL,
    world_desc TEXT NOT NULL,
    gm_user_id INTEGER,
    tone TEXT NOT NULL DEFAULT '',
    difficulty TEXT NOT NULL DEFAULT '{DEFAULT_DIFFICULTY}',
    summary TEXT NOT NULL DEFAULT '',
    summary_upto INTEGER NOT NULL DEFAULT 0,
    location TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS characters (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    user_name TEXT NOT NULL,
    name TEXT NOT NULL,
    description TEXT NOT NULL,
    attributes TEXT NOT NULL DEFAULT '',
    hp INTEGER NOT NULL DEFAULT 10,
    max_hp INTEGER NOT NULL DEFAULT 10,
    stats TEXT,
    level INTEGER NOT NULL DEFAULT 1,
    xp INTEGER NOT NULL DEFAULT 0,
    alive INTEGER NOT NULL DEFAULT 1,
    death_successes INTEGER NOT NULL DEFAULT 0,
    death_failures INTEGER NOT NULL DEFAULT 0,
    race TEXT NOT NULL DEFAULT '',
    subrace TEXT NOT NULL DEFAULT '',
    char_class TEXT NOT NULL DEFAULT '',
    background TEXT NOT NULL DEFAULT '',
    skills TEXT NOT NULL DEFAULT '[]',
    expertise TEXT NOT NULL DEFAULT '[]',
    fighting_style TEXT NOT NULL DEFAULT '',
    temp_hp INTEGER NOT NULL DEFAULT 0,
    exhaustion INTEGER NOT NULL DEFAULT 0,
    inspiration INTEGER NOT NULL DEFAULT 0,
    hit_dice_used INTEGER NOT NULL DEFAULT 0,
    slots_used TEXT NOT NULL DEFAULT '{{}}',
    cantrips TEXT NOT NULL DEFAULT '[]',
    spellbook TEXT NOT NULL DEFAULT '[]',
    prepared TEXT NOT NULL DEFAULT '[]',
    uses TEXT NOT NULL DEFAULT '{{}}',
    conditions TEXT NOT NULL DEFAULT '[]',
    concentration TEXT NOT NULL DEFAULT '',
    asi_pending INTEGER NOT NULL DEFAULT 0,
    learn_pending INTEGER NOT NULL DEFAULT 0,
    cantrip_pending INTEGER NOT NULL DEFAULT 0,
    expertise_pending INTEGER NOT NULL DEFAULT 0,
    died_scene INTEGER NOT NULL DEFAULT 0,
    UNIQUE (chat_id, user_id),
    UNIQUE (chat_id, name)
);
CREATE TABLE IF NOT EXISTS npcs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id INTEGER NOT NULL,
    name TEXT NOT NULL,
    description TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS situations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id INTEGER NOT NULL,
    number INTEGER NOT NULL,
    text TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS actions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id INTEGER NOT NULL,
    after_situation INTEGER NOT NULL,
    character_name TEXT NOT NULL,
    text TEXT NOT NULL,
    kind TEXT NOT NULL DEFAULT 'action'
);
CREATE TABLE IF NOT EXISTS facts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id INTEGER NOT NULL,
    situation INTEGER NOT NULL,
    text TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS enemies (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id INTEGER NOT NULL,
    name TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    hp INTEGER NOT NULL,
    max_hp INTEGER NOT NULL,
    armor_class INTEGER NOT NULL,
    attack_bonus INTEGER NOT NULL,
    damage_dice TEXT NOT NULL,
    initiative_bonus INTEGER NOT NULL DEFAULT 0,
    xp INTEGER NOT NULL DEFAULT 0,
    alive INTEGER NOT NULL DEFAULT 1,
    save_bonus INTEGER NOT NULL DEFAULT 1,
    cr REAL NOT NULL DEFAULT 0.25,
    conditions TEXT NOT NULL DEFAULT '[]',
    attacks INTEGER NOT NULL DEFAULT 1,
    dtype TEXT NOT NULL DEFAULT '',
    etype TEXT NOT NULL DEFAULT '',
    effect_condition TEXT NOT NULL DEFAULT '',
    effect_ability TEXT NOT NULL DEFAULT '',
    effect_dc INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    name TEXT NOT NULL,
    kind TEXT NOT NULL,
    value TEXT NOT NULL DEFAULT '',
    equipped INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS combat (
    chat_id INTEGER PRIMARY KEY,
    round INTEGER NOT NULL,
    turn_index INTEGER NOT NULL,
    order_json TEXT NOT NULL,
    state TEXT NOT NULL DEFAULT '{{}}'
);
CREATE TABLE IF NOT EXISTS drafts (
    chat_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    stage TEXT NOT NULL,
    selected TEXT NOT NULL DEFAULT '[]',
    options TEXT NOT NULL DEFAULT '[]',
    PRIMARY KEY (chat_id, user_id)
);
CREATE TABLE IF NOT EXISTS usage (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id INTEGER,
    kind TEXT NOT NULL,
    input_tokens INTEGER NOT NULL,
    output_tokens INTEGER NOT NULL,
    created_at INTEGER NOT NULL
);
"""

# (таблица, колонка, объявление) — колонки, которых нет в базах старых версий
_MIGRATIONS = [
    ("characters", "hp", "INTEGER NOT NULL DEFAULT 10"),
    ("characters", "max_hp", "INTEGER NOT NULL DEFAULT 10"),
    ("characters", "stats", "TEXT"),
    ("characters", "level", "INTEGER NOT NULL DEFAULT 1"),
    ("characters", "xp", "INTEGER NOT NULL DEFAULT 0"),
    ("characters", "alive", "INTEGER NOT NULL DEFAULT 1"),
    ("characters", "death_successes", "INTEGER NOT NULL DEFAULT 0"),
    ("characters", "death_failures", "INTEGER NOT NULL DEFAULT 0"),
    ("characters", "race", "TEXT NOT NULL DEFAULT ''"),
    ("characters", "subrace", "TEXT NOT NULL DEFAULT ''"),
    ("characters", "char_class", "TEXT NOT NULL DEFAULT ''"),
    ("characters", "background", "TEXT NOT NULL DEFAULT ''"),
    ("characters", "skills", "TEXT NOT NULL DEFAULT '[]'"),
    ("characters", "expertise", "TEXT NOT NULL DEFAULT '[]'"),
    ("characters", "fighting_style", "TEXT NOT NULL DEFAULT ''"),
    ("characters", "temp_hp", "INTEGER NOT NULL DEFAULT 0"),
    ("characters", "exhaustion", "INTEGER NOT NULL DEFAULT 0"),
    ("characters", "inspiration", "INTEGER NOT NULL DEFAULT 0"),
    ("characters", "hit_dice_used", "INTEGER NOT NULL DEFAULT 0"),
    ("characters", "slots_used", "TEXT NOT NULL DEFAULT '{}'"),
    ("characters", "cantrips", "TEXT NOT NULL DEFAULT '[]'"),
    ("characters", "spellbook", "TEXT NOT NULL DEFAULT '[]'"),
    ("characters", "prepared", "TEXT NOT NULL DEFAULT '[]'"),
    ("characters", "uses", "TEXT NOT NULL DEFAULT '{}'"),
    ("characters", "conditions", "TEXT NOT NULL DEFAULT '[]'"),
    ("characters", "concentration", "TEXT NOT NULL DEFAULT ''"),
    ("characters", "asi_pending", "INTEGER NOT NULL DEFAULT 0"),
    ("characters", "learn_pending", "INTEGER NOT NULL DEFAULT 0"),
    ("characters", "cantrip_pending", "INTEGER NOT NULL DEFAULT 0"),
    ("characters", "expertise_pending", "INTEGER NOT NULL DEFAULT 0"),
    ("characters", "died_scene", "INTEGER NOT NULL DEFAULT 0"),
    ("games", "gm_user_id", "INTEGER"),
    ("games", "tone", "TEXT NOT NULL DEFAULT ''"),
    ("games", "difficulty", f"TEXT NOT NULL DEFAULT '{DEFAULT_DIFFICULTY}'"),
    ("games", "summary", "TEXT NOT NULL DEFAULT ''"),
    ("games", "summary_upto", "INTEGER NOT NULL DEFAULT 0"),
    ("games", "location", "TEXT NOT NULL DEFAULT ''"),
    ("actions", "kind", "TEXT NOT NULL DEFAULT 'action'"),
    ("enemies", "save_bonus", "INTEGER NOT NULL DEFAULT 1"),
    ("enemies", "cr", "REAL NOT NULL DEFAULT 0.25"),
    ("enemies", "conditions", "TEXT NOT NULL DEFAULT '[]'"),
    ("enemies", "attacks", "INTEGER NOT NULL DEFAULT 1"),
    ("enemies", "dtype", "TEXT NOT NULL DEFAULT ''"),
    ("enemies", "etype", "TEXT NOT NULL DEFAULT ''"),
    ("enemies", "effect_condition", "TEXT NOT NULL DEFAULT ''"),
    ("enemies", "effect_ability", "TEXT NOT NULL DEFAULT ''"),
    ("enemies", "effect_dc", "INTEGER NOT NULL DEFAULT 0"),
    ("combat", "state", "TEXT NOT NULL DEFAULT '{}'"),
]

_ALL_TABLES = (
    "games", "characters", "npcs", "situations", "actions",
    "facts", "enemies", "items", "combat", "drafts",
)


def _migrate(c: sqlite3.Connection) -> None:
    for table, column, declaration in _MIGRATIONS:
        existing = {row["name"] for row in c.execute(f"PRAGMA table_info({table})")}
        if column not in existing:
            c.execute(f"ALTER TABLE {table} ADD COLUMN {column} {declaration}")
    version = c.execute("PRAGMA user_version").fetchone()[0]
    if version < 2:
        # Раньше xp — прогресс внутри уровня; теперь суммарный опыт по таблице правил.
        for row in c.execute("SELECT id, level, xp FROM characters").fetchall():
            total = srd.XP_FOR_LEVEL[max(1, min(row["level"], srd.MAX_LEVEL)) - 1] + row["xp"]
            c.execute("UPDATE characters SET xp = ? WHERE id = ?", (total, row["id"]))
    c.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
    c.commit()


def conn() -> sqlite3.Connection:
    global _conn
    if _conn is None:
        _conn = sqlite3.connect(DB_PATH, check_same_thread=False)
        _conn.row_factory = sqlite3.Row
        _conn.execute("PRAGMA journal_mode=WAL")
        _conn.executescript(_SCHEMA)
        _migrate(_conn)
    return _conn


def _encode(value):
    """Списки и словари хранятся как JSON."""
    if isinstance(value, (list, dict, set, tuple)):
        return json.dumps(sorted(value) if isinstance(value, set) else value, ensure_ascii=False)
    return value


def _update(table: str, where: dict, fields: dict) -> None:
    if not fields:
        return
    c = conn()
    set_sql = ", ".join(f"{k} = ?" for k in fields)
    where_sql = " AND ".join(f"{k} = ?" for k in where)
    c.execute(
        f"UPDATE {table} SET {set_sql} WHERE {where_sql}",
        ([_encode(v) for v in fields.values()] + list(where.values())),
    )
    c.commit()


# ---------------------------------------------------------------- игра / мир

def set_world(chat_id: int, theme: str, world_desc: str, gm_user_id: int) -> None:
    c = conn()
    c.execute(
        "INSERT INTO games (chat_id, theme, world_desc, gm_user_id) VALUES (?, ?, ?, ?) "
        "ON CONFLICT(chat_id) DO UPDATE SET theme = excluded.theme, "
        "world_desc = excluded.world_desc, gm_user_id = excluded.gm_user_id",
        (chat_id, theme, world_desc, gm_user_id),
    )
    c.commit()


def get_world(chat_id: int) -> sqlite3.Row | None:
    return conn().execute("SELECT * FROM games WHERE chat_id = ?", (chat_id,)).fetchone()


def update_game(chat_id: int, **fields) -> None:
    _update("games", {"chat_id": chat_id}, fields)


# ---------------------------------------------------------------- персонажи

def get_character(chat_id: int, user_id: int) -> sqlite3.Row | None:
    return conn().execute(
        "SELECT * FROM characters WHERE chat_id = ? AND user_id = ?", (chat_id, user_id)
    ).fetchone()


def find_character(chat_id: int, query: str) -> sqlite3.Row | None:
    """Персонаж по началу имени, без учёта регистра и «ё»."""
    q = query.strip().casefold().replace("ё", "е")
    if not q:
        return None
    rows = list_characters(chat_id)
    for row in rows:
        if row["name"].casefold().replace("ё", "е") == q:
            return row
    for row in rows:
        if row["name"].casefold().replace("ё", "е").startswith(q):
            return row
    return None


def list_characters(chat_id: int, alive_only: bool = False) -> list[sqlite3.Row]:
    sql = "SELECT * FROM characters WHERE chat_id = ?"
    if alive_only:
        sql += " AND alive = 1"
    return conn().execute(sql + " ORDER BY id", (chat_id,)).fetchall()


def taken_character_names(chat_id: int) -> list[str]:
    rows = conn().execute("SELECT name FROM characters WHERE chat_id = ?", (chat_id,)).fetchall()
    return [r["name"] for r in rows]


def save_character(chat_id: int, user_id: int, user_name: str, name: str, description: str,
                   **fields) -> bool:
    """True = сохранено, False = имя уже занято или у игрока уже есть персонаж.
    Остальные поля (race, char_class, stats, hp, …) — именованными аргументами."""
    # В базах, созданных старой версией, столбец attributes обязателен и без значения по умолчанию
    fields.setdefault("attributes", "")
    columns = ["chat_id", "user_id", "user_name", "name", "description"] + list(fields)
    values = [chat_id, user_id, user_name, name, description] + [_encode(v) for v in fields.values()]
    c = conn()
    try:
        c.execute(
            f"INSERT INTO characters ({', '.join(columns)}) VALUES ({', '.join('?' * len(columns))})",
            values,
        )
        c.commit()
        return True
    except sqlite3.IntegrityError as e:
        if "UNIQUE" not in str(e):
            raise  # не «имя занято», а настоящая ошибка — пусть попадёт в журнал
        return False


def update_character(chat_id: int, user_id: int, **fields) -> sqlite3.Row | None:
    _update("characters", {"chat_id": chat_id, "user_id": user_id}, fields)
    return get_character(chat_id, user_id)


def delete_character(chat_id: int, user_id: int) -> None:
    c = conn()
    c.execute("DELETE FROM characters WHERE chat_id = ? AND user_id = ?", (chat_id, user_id))
    c.execute("DELETE FROM items WHERE chat_id = ? AND user_id = ?", (chat_id, user_id))
    c.commit()


# ---------------------------------------------------------------- черновики создания героя

def get_draft(chat_id: int, user_id: int) -> dict | None:
    row = conn().execute(
        "SELECT * FROM drafts WHERE chat_id = ? AND user_id = ?", (chat_id, user_id)
    ).fetchone()
    if row is None:
        return None
    return {
        "stage": row["stage"],
        "selected": json.loads(row["selected"]),
        "options": json.loads(row["options"]),
    }


def set_draft(chat_id: int, user_id: int, stage: str, selected, options) -> None:
    """selected — данные шага создания (список или словарь), options — предложенные варианты."""
    c = conn()
    c.execute(
        "INSERT INTO drafts (chat_id, user_id, stage, selected, options) VALUES (?, ?, ?, ?, ?) "
        "ON CONFLICT(chat_id, user_id) DO UPDATE SET stage = excluded.stage, "
        "selected = excluded.selected, options = excluded.options",
        (chat_id, user_id, stage, json.dumps(selected, ensure_ascii=False),
         json.dumps(options, ensure_ascii=False)),
    )
    c.commit()


def delete_draft(chat_id: int, user_id: int) -> None:
    c = conn()
    c.execute("DELETE FROM drafts WHERE chat_id = ? AND user_id = ?", (chat_id, user_id))
    c.commit()


# ---------------------------------------------------------------- NPC

def save_npc(chat_id: int, name: str, description: str) -> None:
    c = conn()
    c.execute(
        "INSERT INTO npcs (chat_id, name, description) VALUES (?, ?, ?)",
        (chat_id, name, description),
    )
    c.commit()


def list_npcs(chat_id: int) -> list[sqlite3.Row]:
    return conn().execute("SELECT * FROM npcs WHERE chat_id = ? ORDER BY id", (chat_id,)).fetchall()


# ---------------------------------------------------------------- сцены

def current_situation_number(chat_id: int) -> int:
    row = conn().execute(
        "SELECT COALESCE(MAX(number), 0) AS n FROM situations WHERE chat_id = ?", (chat_id,)
    ).fetchone()
    return row["n"]


def save_situation(chat_id: int, text: str) -> int:
    c = conn()
    number = current_situation_number(chat_id) + 1
    c.execute(
        "INSERT INTO situations (chat_id, number, text) VALUES (?, ?, ?)", (chat_id, number, text)
    )
    c.commit()
    return number


def list_situations(chat_id: int, limit: int = 10) -> list[sqlite3.Row]:
    """Последние сцены в хронологическом порядке."""
    rows = conn().execute(
        "SELECT * FROM situations WHERE chat_id = ? ORDER BY number DESC LIMIT ?",
        (chat_id, limit),
    ).fetchall()
    return list(reversed(rows))


def situations_between(chat_id: int, first: int, last: int) -> list[sqlite3.Row]:
    return conn().execute(
        "SELECT * FROM situations WHERE chat_id = ? AND number BETWEEN ? AND ? ORDER BY number",
        (chat_id, first, last),
    ).fetchall()


# ---------------------------------------------------------------- действия и события

def save_action(chat_id: int, character_name: str, text: str, kind: str = "action") -> None:
    """Запись, привязанная к текущей сцене: заявка игрока или игровое событие."""
    c = conn()
    c.execute(
        "INSERT INTO actions (chat_id, after_situation, character_name, text, kind) "
        "VALUES (?, ?, ?, ?, ?)",
        (chat_id, current_situation_number(chat_id), character_name, text, kind),
    )
    c.commit()


def pending_actions(chat_id: int, kind: str | None = None) -> list[sqlite3.Row]:
    """Всё, что случилось после последней сцены и ещё не отыграно."""
    sql = "SELECT * FROM actions WHERE chat_id = ? AND after_situation = ?"
    params: list = [chat_id, current_situation_number(chat_id)]
    if kind is not None:
        sql += " AND kind = ?"
        params.append(kind)
    return conn().execute(sql + " ORDER BY id", params).fetchall()


# ---------------------------------------------------------------- факты / журнал

def add_fact(chat_id: int, situation: int, text: str) -> None:
    c = conn()
    c.execute(
        "INSERT INTO facts (chat_id, situation, text) VALUES (?, ?, ?)", (chat_id, situation, text)
    )
    c.commit()


def list_facts(chat_id: int, limit: int = 30) -> list[sqlite3.Row]:
    rows = conn().execute(
        "SELECT * FROM facts WHERE chat_id = ? ORDER BY id DESC LIMIT ?", (chat_id, limit)
    ).fetchall()
    return list(reversed(rows))


# ---------------------------------------------------------------- противники

def _unique_enemy_name(chat_id: int, name: str) -> str:
    """Имена живых противников уникальны: «Гоблин», «Гоблин 2», «Гоблин 3»."""
    taken = {r["name"] for r in list_enemies(chat_id)}
    if name not in taken:
        return name
    n = 2
    while f"{name} {n}" in taken:
        n += 1
    return f"{name} {n}"


def save_enemy(chat_id: int, **fields) -> sqlite3.Row:
    data = {
        "description": "", "initiative_bonus": 0, "xp": 0, "save_bonus": 1, "cr": 0.25,
        "attacks": 1, "dtype": "", "etype": "", "effect_condition": "", "effect_ability": "", "effect_dc": 0,
    }
    data.update(fields)
    data["name"] = _unique_enemy_name(chat_id, data["name"])
    data["max_hp"] = data["hp"]
    columns = ["chat_id"] + list(data)
    c = conn()
    cur = c.execute(
        f"INSERT INTO enemies ({', '.join(columns)}) VALUES ({', '.join('?' * len(columns))})",
        [chat_id] + [_encode(v) for v in data.values()],
    )
    c.commit()
    return get_enemy(cur.lastrowid)


def get_enemy(enemy_id: int) -> sqlite3.Row | None:
    return conn().execute("SELECT * FROM enemies WHERE id = ?", (enemy_id,)).fetchone()


def list_enemies(chat_id: int, alive_only: bool = True) -> list[sqlite3.Row]:
    sql = "SELECT * FROM enemies WHERE chat_id = ?"
    if alive_only:
        sql += " AND alive = 1"
    return conn().execute(sql + " ORDER BY id", (chat_id,)).fetchall()


def find_enemy(chat_id: int, query: str) -> sqlite3.Row | None:
    q = query.strip().casefold().replace("ё", "е")
    if not q:
        return None
    rows = list_enemies(chat_id)
    for row in rows:
        if row["name"].casefold().replace("ё", "е") == q:
            return row
    for row in rows:
        if row["name"].casefold().replace("ё", "е").startswith(q):
            return row
    return None


def update_enemy(enemy_id: int, **fields) -> sqlite3.Row | None:
    _update("enemies", {"id": enemy_id}, fields)
    return get_enemy(enemy_id)


def clear_dead_enemies(chat_id: int) -> None:
    c = conn()
    c.execute("DELETE FROM enemies WHERE chat_id = ? AND alive = 0", (chat_id,))
    c.commit()


# ---------------------------------------------------------------- предметы

def add_item(chat_id: int, user_id: int, name: str, kind: str, value="") -> sqlite3.Row:
    c = conn()
    cur = c.execute(
        "INSERT INTO items (chat_id, user_id, name, kind, value) VALUES (?, ?, ?, ?, ?)",
        (chat_id, user_id, name, kind, _encode(value) if not isinstance(value, str) else value),
    )
    c.commit()
    return conn().execute("SELECT * FROM items WHERE id = ?", (cur.lastrowid,)).fetchone()


def list_items(chat_id: int, user_id: int) -> list[sqlite3.Row]:
    return conn().execute(
        "SELECT * FROM items WHERE chat_id = ? AND user_id = ? ORDER BY equipped DESC, id",
        (chat_id, user_id),
    ).fetchall()


def find_item(chat_id: int, user_id: int, query: str) -> sqlite3.Row | None:
    q = query.strip().casefold().replace("ё", "е")
    if not q:
        return None
    rows = list_items(chat_id, user_id)
    for row in rows:
        if row["name"].casefold().replace("ё", "е") == q:
            return row
    for row in rows:
        if row["name"].casefold().replace("ё", "е").startswith(q):
            return row
    return None


def delete_item(item_id: int) -> None:
    c = conn()
    c.execute("DELETE FROM items WHERE id = ?", (item_id,))
    c.commit()


def equip_item(chat_id: int, user_id: int, item_id: int, kind: str) -> None:
    """Экипирует предмет; другой предмет того же типа снимается."""
    c = conn()
    c.execute(
        "UPDATE items SET equipped = 0 WHERE chat_id = ? AND user_id = ? AND kind = ?",
        (chat_id, user_id, kind),
    )
    c.execute("UPDATE items SET equipped = 1 WHERE id = ?", (item_id,))
    c.commit()


def unequip_item(item_id: int) -> None:
    c = conn()
    c.execute("UPDATE items SET equipped = 0 WHERE id = ?", (item_id,))
    c.commit()


def equipped_item(chat_id: int, user_id: int, kind: str) -> sqlite3.Row | None:
    return conn().execute(
        "SELECT * FROM items WHERE chat_id = ? AND user_id = ? AND kind = ? AND equipped = 1",
        (chat_id, user_id, kind),
    ).fetchone()


# ---------------------------------------------------------------- бой

def get_combat(chat_id: int) -> dict | None:
    row = conn().execute("SELECT * FROM combat WHERE chat_id = ?", (chat_id,)).fetchone()
    if row is None:
        return None
    return {
        "round": row["round"],
        "turn_index": row["turn_index"],
        "order": json.loads(row["order_json"]),
        "state": json.loads(row["state"] or "{}"),
    }


def set_combat(chat_id: int, round_: int, turn_index: int, order: list[dict], state: dict | None = None) -> None:
    c = conn()
    existing = c.execute("SELECT state FROM combat WHERE chat_id = ?", (chat_id,)).fetchone()
    state_json = json.dumps(state if state is not None else
                            (json.loads(existing["state"]) if existing else {}), ensure_ascii=False)
    c.execute(
        "INSERT INTO combat (chat_id, round, turn_index, order_json, state) VALUES (?, ?, ?, ?, ?) "
        "ON CONFLICT(chat_id) DO UPDATE SET round = excluded.round, "
        "turn_index = excluded.turn_index, order_json = excluded.order_json, state = excluded.state",
        (chat_id, round_, turn_index, json.dumps(order, ensure_ascii=False), state_json),
    )
    c.commit()


def set_combat_state(chat_id: int, state: dict) -> None:
    c = conn()
    c.execute("UPDATE combat SET state = ? WHERE chat_id = ?", (json.dumps(state, ensure_ascii=False), chat_id))
    c.commit()


def clear_combat(chat_id: int) -> None:
    c = conn()
    c.execute("DELETE FROM combat WHERE chat_id = ?", (chat_id,))
    c.commit()


# ---------------------------------------------------------------- расход токенов

def record_usage(chat_id: int | None, kind: str, input_tokens: int, output_tokens: int) -> None:
    c = conn()
    c.execute(
        "INSERT INTO usage (chat_id, kind, input_tokens, output_tokens, created_at) "
        "VALUES (?, ?, ?, ?, ?)",
        (chat_id, kind, input_tokens, output_tokens, int(time.time())),
    )
    c.commit()


def usage_totals(chat_id: int) -> dict:
    row = conn().execute(
        "SELECT COUNT(*) AS calls, COALESCE(SUM(input_tokens), 0) AS input_tokens, "
        "COALESCE(SUM(output_tokens), 0) AS output_tokens FROM usage WHERE chat_id = ?",
        (chat_id,),
    ).fetchone()
    return dict(row)


# ---------------------------------------------------------------- резервная копия

def backup_to(path: str) -> None:
    """Целостная копия базы (учитывает WAL-журнал, в отличие от копирования файла)."""
    target = sqlite3.connect(path)
    try:
        conn().backup(target)
    finally:
        target.close()


# ---------------------------------------------------------------- сброс

def reset_game(chat_id: int) -> None:
    c = conn()
    for table in _ALL_TABLES:
        c.execute(f"DELETE FROM {table} WHERE chat_id = ?", (chat_id,))
    c.commit()
