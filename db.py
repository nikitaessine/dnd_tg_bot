"""SQLite-хранилище: мир, персонажи, NPC, сцены и действия игроков.
Одна игра = один чат Telegram."""

import sqlite3

from config import DB_PATH, DEFAULT_HP

_conn: sqlite3.Connection | None = None


def _migrate(c: sqlite3.Connection) -> None:
    """Добавляет колонки, появившиеся после первой версии, не теряя данные."""
    existing = {row["name"] for row in c.execute("PRAGMA table_info(characters)")}
    if "max_hp" not in existing:
        c.execute(f"ALTER TABLE characters ADD COLUMN max_hp INTEGER NOT NULL DEFAULT {DEFAULT_HP}")
    if "hp" not in existing:
        c.execute(f"ALTER TABLE characters ADD COLUMN hp INTEGER NOT NULL DEFAULT {DEFAULT_HP}")
    c.commit()


def conn() -> sqlite3.Connection:
    global _conn
    if _conn is None:
        _conn = sqlite3.connect(DB_PATH)
        _conn.row_factory = sqlite3.Row
        _conn.executescript(
            f"""
            CREATE TABLE IF NOT EXISTS games (
                chat_id INTEGER PRIMARY KEY,
                theme TEXT NOT NULL,
                world_desc TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS characters (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                user_name TEXT NOT NULL,
                name TEXT NOT NULL,
                description TEXT NOT NULL,
                attributes TEXT NOT NULL,
                hp INTEGER NOT NULL DEFAULT {DEFAULT_HP},
                max_hp INTEGER NOT NULL DEFAULT {DEFAULT_HP},
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
                text TEXT NOT NULL
            );
            """
        )
        _migrate(_conn)
    return _conn


def set_world(chat_id: int, theme: str, world_desc: str) -> None:
    c = conn()
    c.execute(
        "INSERT INTO games (chat_id, theme, world_desc) VALUES (?, ?, ?) "
        "ON CONFLICT(chat_id) DO UPDATE SET theme = excluded.theme, world_desc = excluded.world_desc",
        (chat_id, theme, world_desc),
    )
    c.commit()


def get_world(chat_id: int) -> sqlite3.Row | None:
    return conn().execute("SELECT * FROM games WHERE chat_id = ?", (chat_id,)).fetchone()


def get_character(chat_id: int, user_id: int) -> sqlite3.Row | None:
    return conn().execute(
        "SELECT * FROM characters WHERE chat_id = ? AND user_id = ?", (chat_id, user_id)
    ).fetchone()


def list_characters(chat_id: int) -> list[sqlite3.Row]:
    return conn().execute("SELECT * FROM characters WHERE chat_id = ?", (chat_id,)).fetchall()


def taken_character_names(chat_id: int) -> list[str]:
    rows = conn().execute("SELECT name FROM characters WHERE chat_id = ?", (chat_id,)).fetchall()
    return [r["name"] for r in rows]


def save_character(
    chat_id: int, user_id: int, user_name: str, name: str, description: str, attributes: str
) -> bool:
    """True = сохранено, False = имя уже занято или у игрока уже есть персонаж."""
    c = conn()
    try:
        c.execute(
            "INSERT INTO characters (chat_id, user_id, user_name, name, description, attributes) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (chat_id, user_id, user_name, name, description, attributes),
        )
        c.commit()
        return True
    except sqlite3.IntegrityError:
        return False


def delete_character(chat_id: int, user_id: int) -> None:
    c = conn()
    c.execute("DELETE FROM characters WHERE chat_id = ? AND user_id = ?", (chat_id, user_id))
    c.commit()


def save_npc(chat_id: int, name: str, description: str) -> None:
    c = conn()
    c.execute(
        "INSERT INTO npcs (chat_id, name, description) VALUES (?, ?, ?)",
        (chat_id, name, description),
    )
    c.commit()


def list_npcs(chat_id: int) -> list[sqlite3.Row]:
    return conn().execute("SELECT * FROM npcs WHERE chat_id = ?", (chat_id,)).fetchall()


def save_situation(chat_id: int, text: str) -> int:
    c = conn()
    row = c.execute(
        "SELECT COALESCE(MAX(number), 0) + 1 AS n FROM situations WHERE chat_id = ?", (chat_id,)
    ).fetchone()
    number = row["n"]
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


def current_situation_number(chat_id: int) -> int:
    """Номер последней сгенерированной сцены, 0 — если сцен ещё не было."""
    row = conn().execute(
        "SELECT COALESCE(MAX(number), 0) AS n FROM situations WHERE chat_id = ?", (chat_id,)
    ).fetchone()
    return row["n"]


def save_action(chat_id: int, character_name: str, text: str) -> None:
    """Записывает действие игрока, привязанное к текущей сцене."""
    c = conn()
    c.execute(
        "INSERT INTO actions (chat_id, after_situation, character_name, text) VALUES (?, ?, ?, ?)",
        (chat_id, current_situation_number(chat_id), character_name, text),
    )
    c.commit()


def pending_actions(chat_id: int) -> list[sqlite3.Row]:
    """Действия, заявленные после последней сцены и ещё не отыгранные."""
    return conn().execute(
        "SELECT * FROM actions WHERE chat_id = ? AND after_situation = ? ORDER BY id",
        (chat_id, current_situation_number(chat_id)),
    ).fetchall()


def adjust_hp(chat_id: int, user_id: int, delta: int) -> sqlite3.Row | None:
    """Меняет здоровье на delta, ограничивая диапазоном 0..max_hp."""
    character = get_character(chat_id, user_id)
    if character is None:
        return None
    new_hp = max(0, min(character["max_hp"], character["hp"] + delta))
    c = conn()
    c.execute(
        "UPDATE characters SET hp = ? WHERE chat_id = ? AND user_id = ?",
        (new_hp, chat_id, user_id),
    )
    c.commit()
    return get_character(chat_id, user_id)


def reset_game(chat_id: int) -> None:
    c = conn()
    for table in ("games", "characters", "npcs", "situations", "actions"):
        c.execute(f"DELETE FROM {table} WHERE chat_id = ?", (chat_id,))
    c.commit()
