"""Генерация игрового контента через Claude API."""

from anthropic import AsyncAnthropic
from pydantic import BaseModel

from config import ANTHROPIC_API_KEY

MODEL = "claude-opus-5"

client = AsyncAnthropic(api_key=ANTHROPIC_API_KEY)

SYSTEM = (
    "Ты — мастер настольной ролевой игры в духе D&D. Всегда отвечай на русском языке. "
    "Пиши ярко, атмосферно и достаточно кратко: это сообщения для Telegram-чата."
)


class CharacterOption(BaseModel):
    name: str
    archetype: str
    description: str


class CharacterOptions(BaseModel):
    options: list[CharacterOption]


async def _text(prompt: str, max_tokens: int = 2000) -> str:
    response = await client.messages.create(
        model=MODEL,
        max_tokens=max_tokens,
        system=SYSTEM,
        messages=[{"role": "user", "content": prompt}],
    )
    if response.stop_reason == "refusal":
        return "Не удалось сгенерировать ответ. Попробуйте ещё раз."
    return "".join(b.text for b in response.content if b.type == "text").strip()


async def generate_world(theme: str) -> str:
    return await _text(
        f"Придумай игровой мир для кампании на тему: «{theme}».\n"
        "Опиши мир в 3–5 абзацах: атмосфера, ключевые места, конфликты и опасности. "
        "Не начинай приключение — только описание мира."
    )


async def generate_character_options(
    theme: str, world_desc: str, attributes: list[str], taken_names: list[str]
) -> list[CharacterOption]:
    taken = ", ".join(taken_names) if taken_names else "пока нет"
    prompt = (
        f"Мир кампании (тема «{theme}»):\n{world_desc}\n\n"
        f"Игрок выбрал главные атрибуты своего персонажа: {', '.join(attributes)}.\n"
        f"Уже занятые персонажи (их имена и похожие образы использовать НЕЛЬЗЯ): {taken}.\n\n"
        "Предложи ровно 3 разных варианта персонажа, подходящих этому миру и этим атрибутам. "
        "Для каждого: имя (name), архетип/класс (archetype) и живое описание в 2–3 предложениях "
        "(description). Варианты должны заметно отличаться друг от друга."
    )
    response = await client.messages.parse(
        model=MODEL,
        max_tokens=4000,
        system=SYSTEM,
        messages=[{"role": "user", "content": prompt}],
        output_format=CharacterOptions,
    )
    parsed = response.parsed_output
    if parsed is None:
        raise RuntimeError("Character generation returned no parseable output")
    return parsed.options[:3]


async def generate_npc(theme: str, world_desc: str, existing_npcs: list[str]) -> str:
    existing = ", ".join(existing_npcs) if existing_npcs else "пока нет"
    return await _text(
        f"Мир кампании (тема «{theme}»):\n{world_desc}\n\n"
        f"Уже существующие NPC: {existing}.\n\n"
        "Придумай одного нового NPC, не похожего на существующих. "
        "Первая строка — только имя NPC. Затем описание: кто он, характер, "
        "чего хочет и как может быть связан с приключением. 1–2 абзаца."
    )


async def generate_situation(
    theme: str,
    world_desc: str,
    characters: list[str],
    npcs: list[str],
    previous_situations: list[str],
) -> str:
    chars = "\n".join(f"- {c}" for c in characters) if characters else "- пока нет персонажей"
    npc_list = "\n".join(f"- {n}" for n in npcs) if npcs else "- пока нет"
    if previous_situations:
        history = "\n\n".join(
            f"Сцена {i + 1}: {s}" for i, s in enumerate(previous_situations)
        )
    else:
        history = "Это самая первая сцена приключения."
    return await _text(
        f"Мир кампании (тема «{theme}»):\n{world_desc}\n\n"
        f"Персонажи игроков:\n{chars}\n\n"
        f"Известные NPC:\n{npc_list}\n\n"
        f"История предыдущих сцен:\n{history}\n\n"
        "Сгенерируй СЛЕДУЮЩУЮ сцену приключения. Она обязана логично продолжать "
        "предыдущие сцены и не противоречить им: учитывай, где находятся герои, "
        "что уже произошло и какие сюжетные нити открыты. Опиши обстановку, что происходит, "
        "и закончи открытым вопросом к игрокам: что они будут делать? 2–3 абзаца.",
        max_tokens=3000,
    )
