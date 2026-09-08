"""Проверки вспомогательных функций обработчиков, не требующих Telegram."""

from types import SimpleNamespace

import db
from conftest import CHAT, GM, PLAYER, make_hero, make_world
from handlers.common import hp_line, is_gm, split_text
from handlers.hero import attr_keyboard, sheet_text
from handlers.story import _character_summaries, _check_buttons, party_card


def test_party_card_lists_living_heroes_with_players():
    make_world()
    make_hero(PLAYER, "Гарен")
    make_hero(12, "Лира")
    db.update_character(CHAT, 12, alive=0)
    card = party_card(CHAT)
    assert "Гарен" in card and "играет Игрок" in card
    assert "Лира" not in card
    db.reset_game(CHAT)
    assert party_card(CHAT) is None


def test_split_text_respects_limit_and_paragraphs():
    text = "\n\n".join(["абзац " * 100] * 10)
    chunks = split_text(text, limit=1500)
    assert all(len(c) <= 1500 for c in chunks)
    assert "".join(c.replace("\n", "").replace(" ", "") for c in chunks) == text.replace("\n", "").replace(" ", "")
    assert split_text("короткий") == ["короткий"]


def test_split_text_hard_cut_without_separators():
    chunks = split_text("x" * 9000, limit=4000)
    assert [len(c) for c in chunks] == [4000, 4000, 1000]


def _msg(chat_type: str, user_id: int):
    return SimpleNamespace(chat=SimpleNamespace(type=chat_type), from_user=SimpleNamespace(id=user_id))


def test_is_gm_rules():
    game = make_world(gm=GM)
    assert is_gm(_msg("private", PLAYER), game)
    assert is_gm(_msg("group", GM), game)
    assert not is_gm(_msg("group", PLAYER), game)
    db.update_game(CHAT, gm_user_id=None)
    assert is_gm(_msg("group", PLAYER), db.get_world(CHAT))


def test_hp_line_states():
    hero = dict(make_hero(max_hp=20))
    assert "здоров" in hp_line(hero)
    hero["hp"] = 15
    assert "ранен" in hp_line(hero)
    hero["hp"] = 5
    assert "тяжело" in hp_line(hero)
    hero["hp"] = 0
    assert "без сознания" in hp_line(hero)
    hero["alive"] = 0
    assert "погиб" in hp_line(hero)


def test_attr_keyboard_embeds_owner_and_done_button():
    kb = attr_keyboard(42, [])
    assert all(b.callback_data.startswith("attr:42:") for row in kb.inline_keyboard for b in row)
    assert not any(b.callback_data == "done:42" for row in kb.inline_keyboard for b in row)
    kb = attr_keyboard(42, ["Сила", "Ловкость", "Телосложение", "Воля"])
    assert kb.inline_keyboard[-1][0].callback_data == "done:42"


def test_sheet_text_contains_key_numbers():
    make_world()
    hero = make_hero()
    text = sheet_text(CHAT, hero)
    assert "Гарен" in text and "Класс доспеха: 13" in text and "+5 (Сила)" in text


def test_check_buttons_skip_unknown_and_unconscious():
    make_world()
    make_hero(PLAYER, "Гарен")
    make_hero(12, "Лира", max_hp=10)
    db.update_character(CHAT, 12, hp=0)
    checks = [
        SimpleNamespace(character="Гарен", attribute="ловкость", difficulty=15, reason="перепрыгнуть"),
        SimpleNamespace(character="Лира", attribute="Сила", difficulty=10, reason="без сознания"),
        SimpleNamespace(character="Никто", attribute="Сила", difficulty=10, reason="не существует"),
        SimpleNamespace(character="Гарен", attribute="Магия", difficulty=99, reason="нет такого атрибута"),
    ]
    lines, markup = _check_buttons(CHAT, checks)
    assert len(markup.inline_keyboard) == 1
    assert markup.inline_keyboard[0][0].callback_data == f"check:{PLAYER}:1:15"
    assert any("перепрыгнуть" in line for line in lines)


def test_character_summaries_mark_states():
    make_world()
    make_hero(PLAYER, "Гарен")
    make_hero(12, "Лира")
    db.update_character(CHAT, 12, alive=0)
    summaries = _character_summaries(CHAT)
    assert any("Гарен" in s and "1 ур." in s for s in summaries)
    assert any("Лира" in s and "ПОГИБ" in s for s in summaries)
