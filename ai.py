"""Генерация игрового контента через Claude API."""

import contextvars
from dataclasses import dataclass, field

from anthropic import AsyncAnthropic
from pydantic import BaseModel

import db
import dice
from config import ANTHROPIC_API_KEY, ATTRIBUTES

MODEL = "claude-opus-5"

client = AsyncAnthropic(api_key=ANTHROPIC_API_KEY)

# Чат, для которого идёт генерация — чтобы вести учёт токенов по кампаниям
current_chat: contextvars.ContextVar[int | None] = contextvars.ContextVar(
    "current_chat", default=None
)

BASE_SYSTEM = (
    "Ты — мастер настольной ролевой игры в духе D&D. Всегда отвечай на русском языке. "
    "Пиши ярко, атмосферно и достаточно кратко: это сообщения для Telegram-чата. "
    "Не используй markdown-разметку и HTML-теги — только обычный текст с абзацами."
)


def _system(tone: str = "") -> str:
    if tone:
        return f"{BASE_SYSTEM}\n\nСтиль и тон кампании, заданный мастером игры: {tone}"
    return BASE_SYSTEM


def _record(kind: str, response) -> None:
    db.record_usage(
        current_chat.get(), kind, response.usage.input_tokens, response.usage.output_tokens
    )


async def _text(kind: str, prompt: str, tone: str = "", max_tokens: int = 2000) -> str:
    response = await client.messages.create(
        model=MODEL,
        max_tokens=max_tokens,
        system=_system(tone),
        messages=[{"role": "user", "content": prompt}],
    )
    _record(kind, response)
    if response.stop_reason == "refusal":
        return "Не удалось сгенерировать ответ. Попробуйте переформулировать."
    return "".join(b.text for b in response.content if b.type == "text").strip()


async def _parse(kind: str, prompt: str, output_model, tone: str = "", max_tokens: int = 4000):
    response = await client.messages.parse(
        model=MODEL,
        max_tokens=max_tokens,
        system=_system(tone),
        messages=[{"role": "user", "content": prompt}],
        output_format=output_model,
    )
    _record(kind, response)
    if response.parsed_output is None:
        raise RuntimeError(f"{kind}: модель не вернула структурированный ответ")
    return response.parsed_output


# ---------------------------------------------------------------- структуры ответов

class CharacterOption(BaseModel):
    name: str
    archetype: str
    description: str


class CharacterOptions(BaseModel):
    options: list[CharacterOption]


class EnemyBlock(BaseModel):
    name: str
    description: str
    hp: int
    armor_class: int
    attack_bonus: int
    damage_dice: str
    initiative_bonus: int
    xp: int


class LootItem(BaseModel):
    name: str
    kind: str  # weapon | armor | item
    value: str  # кубик урона для оружия, бонус к КД для доспеха, иначе пусто
    description: str


class LootList(BaseModel):
    items: list[LootItem]


class CheckRequest(BaseModel):
    character: str
    attribute: str
    difficulty: int
    reason: str


class SceneResult(BaseModel):
    text: str
    location: str
    new_facts: list[str]
    checks: list[CheckRequest]


@dataclass
class SceneContext:
    theme: str
    world_desc: str
    tone: str = ""
    difficulty: str = "обычная"
    location: str = ""
    summary: str = ""
    recent_scenes: list[str] = field(default_factory=list)
    first_recent_number: int = 1
    characters: list[str] = field(default_factory=list)
    npcs: list[str] = field(default_factory=list)
    facts: list[str] = field(default_factory=list)
    actions: list[str] = field(default_factory=list)
    events: list[str] = field(default_factory=list)


# ---------------------------------------------------------------- генераторы

async def generate_world(theme: str, tone: str = "") -> str:
    return await _text(
        "world",
        f"Придумай игровой мир для кампании на тему: «{theme}».\n"
        "Опиши мир в 3–5 абзацах: атмосфера, ключевые места, конфликты и опасности. "
        "Не начинай приключение — только описание мира. Уложись примерно в 2500 знаков.",
        tone,
    )


async def generate_character_options(
    theme: str, world_desc: str, attributes: list[str], taken_names: list[str], tone: str = ""
) -> list[CharacterOption]:
    taken = ", ".join(taken_names) if taken_names else "пока нет"
    result = await _parse(
        "hero",
        f"Мир кампании (тема «{theme}»):\n{world_desc}\n\n"
        f"Игрок выбрал главные атрибуты своего персонажа: {', '.join(attributes)}.\n"
        f"Уже занятые персонажи (их имена и похожие образы использовать НЕЛЬЗЯ): {taken}.\n\n"
        "Предложи ровно 3 разных варианта персонажа, подходящих этому миру и этим атрибутам. "
        "Для каждого: имя (name), архетип/класс (archetype) и живое описание в 2–3 предложениях "
        "(description). Варианты должны заметно отличаться друг от друга.",
        CharacterOptions,
        tone,
    )
    return result.options[:3]


async def generate_npc(theme: str, world_desc: str, existing: list[str], tone: str = "") -> str:
    existing_text = ", ".join(existing) if existing else "пока нет"
    return await _text(
        "npc",
        f"Мир кампании (тема «{theme}»):\n{world_desc}\n\n"
        f"Уже существующие NPC: {existing_text}.\n\n"
        "Придумай одного нового NPC, не похожего на существующих. "
        "Первая строка — только имя NPC. Затем описание: кто он, характер, "
        "чего хочет и как может быть связан с приключением. 1–2 абзаца.",
        tone,
    )


async def generate_enemy(
    theme: str,
    world_desc: str,
    description: str,
    party_level: int,
    party_size: int,
    difficulty: str,
    tone: str = "",
) -> EnemyBlock:
    enemy = await _parse(
        "enemy",
        f"Мир кампании (тема «{theme}»):\n{world_desc}\n\n"
        f"Отряд: {party_size} персонаж(ей) {party_level} уровня. "
        f"Сложность кампании: {difficulty}.\n\n"
        f"Придумай ОДНОГО противника по описанию мастера: «{description}».\n"
        "Верни: name (короткое имя, до 3 слов), description (1–2 предложения), "
        "hp (здоровье: для отряда 1 уровня обычной сложности одиночный противник — 8–15, "
        "босс — 25–40; масштабируй по уровню и сложности), armor_class (10–17), "
        "attack_bonus (от +1 до +6), damage_dice в формате NdM+K, например 1d6+2, "
        "initiative_bonus (от -1 до +4), xp (награда за победу: слабый 10–25, "
        "обычный 30–60, босс 100–200).",
        EnemyBlock,
        tone,
    )
    # Модель может прислать некорректную запись кубиков — тогда безопасное значение
    if dice.parse_notation(enemy.damage_dice) is None:
        enemy.damage_dice = "1d6"
    enemy.hp = max(1, enemy.hp)
    enemy.armor_class = max(5, min(25, enemy.armor_class))
    enemy.attack_bonus = max(-2, min(10, enemy.attack_bonus))
    enemy.initiative_bonus = max(-3, min(6, enemy.initiative_bonus))
    enemy.xp = max(0, enemy.xp)
    return enemy


async def generate_loot(
    theme: str, world_desc: str, context: str, tone: str = ""
) -> list[LootItem]:
    result = await _parse(
        "loot",
        f"Мир кампании (тема «{theme}»):\n{world_desc}\n\n"
        f"Контекст: {context}\n\n"
        "Придумай 1–3 предмета добычи, уместных в этой ситуации. Для каждого: "
        "name (название), kind — строго одно из: weapon, armor, item; "
        "value — для weapon кубик урона в формате NdM или NdM+K (например 1d8 или 1d6+1), "
        "для armor бонус к классу доспеха числом от 1 до 4, для item пустая строка; "
        "description — одно предложение.",
        LootList,
        tone,
    )
    cleaned: list[LootItem] = []
    for item in result.items[:3]:
        kind = item.kind.strip().lower()
        if kind == "weapon":
            if dice.parse_notation(item.value) is None:
                item.value = "1d6"
        elif kind == "armor":
            digits = "".join(ch for ch in item.value if ch.isdigit())
            item.value = str(max(1, min(4, int(digits)))) if digits else "1"
        else:
            kind = "item"
            item.value = ""
        item.kind = kind
        cleaned.append(item)
    return cleaned


async def generate_scene(ctx: SceneContext) -> SceneResult:
    chars = "\n".join(f"- {c}" for c in ctx.characters) if ctx.characters else "- пока нет"
    npcs = "\n".join(f"- {n}" for n in ctx.npcs) if ctx.npcs else "- пока нет"
    facts = "\n".join(f"- {f}" for f in ctx.facts) if ctx.facts else "- пока нет"

    if ctx.recent_scenes:
        history = "\n\n".join(
            f"Сцена {ctx.first_recent_number + i}: {s}" for i, s in enumerate(ctx.recent_scenes)
        )
    else:
        history = "Это самая первая сцена приключения."
    summary_block = (
        f"Краткий пересказ более ранних событий:\n{ctx.summary}\n\n" if ctx.summary else ""
    )
    location_block = f"Текущее местоположение отряда: {ctx.location}\n\n" if ctx.location else ""

    if ctx.actions:
        actions_block = (
            "Действия, которые игроки заявили после последней сцены:\n"
            + "\n".join(f"- {a}" for a in ctx.actions)
            + "\n\n"
        )
    else:
        actions_block = "После последней сцены игроки не заявляли действий.\n\n"
    if ctx.events:
        events_block = (
            "Игровые события после последней сцены (броски, бои, урон — это ФАКТЫ, "
            "их исход уже определён кубиками и должен быть отражён в сцене):\n"
            + "\n".join(f"- {e}" for e in ctx.events)
            + "\n\n"
        )
    else:
        events_block = ""

    prompt = (
        f"Мир кампании (тема «{ctx.theme}»):\n{ctx.world_desc}\n\n"
        f"Сложность кампании: {ctx.difficulty}.\n\n"
        f"Персонажи игроков (с уровнем и здоровьем):\n{chars}\n\n"
        f"Известные NPC:\n{npcs}\n\n"
        f"Важные факты и открытые сюжетные нити:\n{facts}\n\n"
        f"{location_block}{summary_block}"
        f"Последние сцены:\n{history}\n\n"
        f"{actions_block}{events_block}"
        "Сгенерируй СЛЕДУЮЩУЮ сцену приключения. Правила:\n"
        "1. Сцена — прямое следствие заявленных действий и произошедших событий. "
        "Не игнорируй ни одно заявленное действие. Успешные броски ведут к успеху, "
        "проваленные — к осложнениям.\n"
        "2. Не противоречь предыдущим сценам и фактам: учитывай, где герои, что уже случилось "
        "и какие нити открыты.\n"
        "3. Учитывай здоровье: раненый действует хуже, персонаж с 0 HP без сознания и не "
        "действует сам, погибший персонаж больше не участвует.\n"
        "4. Если действие игрока имеет неопределённый исход и для него ещё НЕТ броска среди "
        "событий, запроси проверку в поле checks (не больше трёх за сцену) и НЕ описывай "
        "исход этого действия в тексте — опиши напряжённый момент и остановись. "
        f"attribute — строго одно из: {', '.join(ATTRIBUTES)}. difficulty — от 8 до 20. "
        "character — точное имя персонажа игрока. reason — одна фраза, что проверяется.\n"
        "5. text: 2–3 абзаца, заканчивается открытым вопросом к игрокам. "
        "location: где отряд находится к концу сцены, коротко. "
        "new_facts: 0–3 новых важных факта (найденные предметы, обещания, имена, зацепки), "
        "которые нужно помнить дальше; пустой список, если ничего важного."
    )
    return await _parse("scene", prompt, SceneResult, ctx.tone, max_tokens=6000)


async def summarize(previous_summary: str, scenes: list[str], tone: str = "") -> str:
    scenes_text = "\n\n".join(f"Сцена: {s}" for s in scenes)
    previous = previous_summary or "(пересказа ещё нет)"
    return await _text(
        "summary",
        f"Текущий краткий пересказ кампании:\n{previous}\n\n"
        f"Новые сцены, которые нужно добавить в пересказ:\n{scenes_text}\n\n"
        "Напиши обновлённый пересказ: 1–2 абзаца, не больше 1500 знаков. Сохрани имена, "
        "ключевые решения, найденные предметы и незакрытые сюжетные линии. "
        "Опусти второстепенные детали. Верни только текст пересказа.",
        tone,
    )


async def generate_recap(
    theme: str,
    summary: str,
    recent_scenes: list[str],
    facts: list[str],
    location: str,
    tone: str = "",
) -> str:
    recent = "\n\n".join(recent_scenes) if recent_scenes else "(сцен ещё не было)"
    facts_text = "\n".join(f"- {f}" for f in facts) if facts else "- пока нет"
    return await _text(
        "recap",
        f"Кампания на тему «{theme}».\n\n"
        f"Пересказ ранних событий:\n{summary or '(нет)'}\n\n"
        f"Последние сцены:\n{recent}\n\n"
        f"Важные факты:\n{facts_text}\n\n"
        f"Местоположение: {location or 'неизвестно'}\n\n"
        "Напиши для игроков краткое напоминание «В предыдущих сериях»: что произошло, "
        "где отряд сейчас и какие вопросы остались открытыми. 1–2 абзаца, живым языком.",
        tone,
    )
