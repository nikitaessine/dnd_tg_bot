"""Генерация игрового контента через Claude API.

Числа (опыт за противника, бонус мастерства, пороги) берутся из таблиц правил, а не у модели:
модель придумывает образ и черновые характеристики, код приводит их к правилам.
"""

import contextvars
from dataclasses import dataclass, field

from anthropic import AsyncAnthropic
from pydantic import BaseModel

import db
import dice
import srd
from config import ANTHROPIC_API_KEY

MODEL = "claude-opus-5"

client = AsyncAnthropic(api_key=ANTHROPIC_API_KEY)

# Чат, для которого идёт генерация — чтобы вести учёт токенов по кампаниям
current_chat: contextvars.ContextVar[int | None] = contextvars.ContextVar(
    "current_chat", default=None
)

BASE_SYSTEM = (
    "Ты — мастер настольной ролевой игры по правилам D&D 5-й редакции (Basic Rules). "
    "Всегда отвечай на русском языке. Пиши простым разговорным языком: короткие предложения, "
    "обычные слова, без сложных метафор, редких слов и длинных описаний. Текст должен легко читаться "
    "с первого раза. Это сообщения для Telegram-чата — пиши кратко: только главное, без лишних "
    "подробностей и объяснений, но так, чтобы общая картина была понятна. Не используй markdown-разметку "
    "и HTML-теги — только обычный текст с абзацами."
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
    creature_type: str          # гуманоид, зверь, нежить, чудовище…
    cr: float                   # уровень опасности: 0, 0.125, 0.25, 0.5, 1, 2, 3…
    hp: int
    armor_class: int
    attack_bonus: int
    damage_dice: str            # NdM+K
    damage_type: str            # рубящий, колющий, огонь, яд…
    attacks: int                # число атак за ход
    save_bonus: int             # бонус к спасброскам и проверкам
    initiative_bonus: int
    effect_condition: str       # состояние при попадании: отравлен, парализован, испуган… или пусто
    effect_ability: str         # характеристика спасброска против эффекта
    effect_dc: int


class LootItem(BaseModel):
    name: str
    kind: str          # weapon | armor | shield | item
    base: str          # название базового предмета из правил (например «Длинный меч») или пусто
    bonus: int         # магический бонус: 0, 1, 2 или 3
    description: str


class LootList(BaseModel):
    items: list[LootItem]


class CheckRequest(BaseModel):
    character: str
    attribute: str     # характеристика или навык
    kind: str          # check — проверка, save — спасбросок
    difficulty: int
    reason: str


class NewNpc(BaseModel):
    name: str
    description: str


class SceneResult(BaseModel):
    text: str
    location: str
    new_facts: list[str]
    checks: list[CheckRequest]
    new_npcs: list[NewNpc] = []
    revealed_npcs: list[str] = []
    gm_enemies_appear: bool = False
    new_enemy: str = ""
    new_enemy_count: int = 0


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
    hidden_npcs: list[str] = field(default_factory=list)
    hidden_enemies: list[str] = field(default_factory=list)
    visible_enemies: list[str] = field(default_factory=list)
    facts: list[str] = field(default_factory=list)
    actions: list[str] = field(default_factory=list)
    events: list[str] = field(default_factory=list)


CR_VALUES = ", ".join(srd.cr_label(cr) for cr in srd.CR_TABLE if cr <= 8)

# Образцы из Basic Rules (гл. 12, с. 163–164) — чтобы модель держала правильный масштаб
ENEMY_EXAMPLES = (
    "Образцы масштаба из правил: Кобольд/Культист — уровень опасности 1/8, КД 12, 9 хитов, атака +3, урон 1d6+1. "
    "Стражник — 1/8, КД 16, 11 хитов, +3, 1d6+1. Головорез — 1/2, КД 11, 32 хита, две атаки +4 по 1d6+2. "
    "Жрец — 2, КД 13, 27 хитов, +2. Рыцарь — 3, КД 18, 52 хита, две атаки +5 по 2d6+3. Маг — 6, КД 12, 40 хитов."
)


# ---------------------------------------------------------------- генераторы

async def generate_world(theme: str, tone: str = "") -> str:
    return await _text(
        "world",
        f"Придумай игровой мир для кампании на тему: «{theme}».\n"
        "Опиши мир в 2 коротких абзацах: что это за место, главный конфликт и опасности. "
        "Не начинай приключение — только описание мира. Не больше 800 знаков.",
        tone,
    )


async def generate_character_options(
    theme: str, world_desc: str, race: str, subrace: str, class_name: str, background: str,
    taken_names: list[str], tone: str = "",
) -> list[CharacterOption]:
    taken = ", ".join(taken_names) if taken_names else "пока нет"
    race_text = f"{race} ({subrace})" if subrace else race
    result = await _parse(
        "hero",
        f"Мир кампании (тема «{theme}»):\n{world_desc}\n\n"
        f"Игрок создаёт персонажа: раса — {race_text}, класс — {class_name}, предыстория — «{background}».\n"
        f"Уже занятые персонажи (их имена и похожие образы использовать НЕЛЬЗЯ): {taken}.\n\n"
        "Предложи ровно 3 разных варианта персонажа, подходящих этому миру, расе, классу и предыстории. "
        "Имена должны звучать так, как принято у этой расы. Для каждого: имя (name), "
        "короткий образ или прозвище (archetype) и описание в 1–2 предложениях (description). "
        "Варианты должны заметно отличаться друг от друга.",
        CharacterOptions,
        tone,
    )
    return result.options[:3]


async def generate_npc(theme: str, world_desc: str, existing: list[str], tone: str = "", hint: str = "") -> str:
    existing_text = ", ".join(existing) if existing else "пока нет"
    hint_text = f"Пожелание мастера: «{hint}».\n\n" if hint else ""
    return await _text(
        "npc",
        f"Мир кампании (тема «{theme}»):\n{world_desc}\n\n"
        f"Уже существующие NPC: {existing_text}.\n\n{hint_text}"
        "Придумай одного нового NPC, не похожего на существующих. "
        "Первая строка — только имя NPC. Затем описание: кто он, характер, "
        "чего хочет и как может быть связан с приключением. 2–3 предложения.",
        tone,
    )


def normalize_enemy(block: EnemyBlock) -> dict:
    """Приводит черновик модели к правилам: опыт и бонус мастерства — из таблицы, разброс статов ограничен."""
    cr = srd.nearest_cr(block.cr)
    prof, xp = srd.CR_TABLE[cr]
    damage = block.damage_dice if dice.parse_notation(block.damage_dice) else "1d6"
    attacks = max(1, min(4, block.attacks))
    avg = dice.average_notation(damage) * attacks
    max_avg = 8 + 8 * cr
    if avg > max_avg:  # слишком сильный урон за ход — ослабляем кубик
        damage = "1d6" if cr < 1 else "2d6"
    effect = block.effect_condition.strip().casefold()
    if effect not in srd.CONDITIONS:
        effect = ""
    ability = dice.match_name(block.effect_ability, srd.ABILITIES) or srd.CON
    return {
        "name": block.name.strip()[:60] or "Противник",
        "description": block.description.strip(),
        "cr": cr, "xp": xp,
        "hp": max(1, min(block.hp, int(20 + 40 * cr))),
        "armor_class": max(10, min(20, block.armor_class)),
        "attack_bonus": max(prof, min(prof + 5, block.attack_bonus)),
        "damage_dice": damage.lower(), "dtype": block.damage_type.strip().casefold()[:20],
        "attacks": attacks,
        "save_bonus": max(-1, min(prof + 5, block.save_bonus)),
        "initiative_bonus": max(-3, min(6, block.initiative_bonus)),
        "etype": block.creature_type.strip().casefold()[:30],
        "effect_condition": effect,
        "effect_ability": ability if effect else "",
        "effect_dc": max(8, min(8 + prof + 4, block.effect_dc)) if effect else 0,
    }


async def generate_enemy(
    theme: str, world_desc: str, description: str, party_level: int, party_size: int,
    difficulty: str, tone: str = "",
) -> dict:
    block = await _parse(
        "enemy",
        f"Мир кампании (тема «{theme}»):\n{world_desc}\n\n"
        f"Отряд: {party_size} персонаж(ей) {party_level} уровня. Сложность кампании: {difficulty}.\n\n"
        f"Придумай ОДНОГО противника по описанию мастера: «{description}».\n"
        f"cr — уровень опасности по правилам, один из: {CR_VALUES}. Для одного противника против отряда "
        f"{party_level} уровня подойдёт cr от {max(0, party_level - 3)} до {party_level} "
        f"(для слабого — 1/8, 1/4, 1/2).\n"
        f"{ENEMY_EXAMPLES}\n"
        "Верни: name (до 3 слов), description (1–2 предложения), creature_type (гуманоид, зверь, нежить, "
        "чудовище, элементаль и т. п.), cr, hp, armor_class (10–20), attack_bonus (бонус мастерства + мод.), "
        "damage_dice в формате NdM+K, damage_type (рубящий, колющий, дробящий, огонь, холод, яд…), "
        "attacks (1–3 атаки за ход), save_bonus (бонус к спасброскам), initiative_bonus, "
        "effect_condition (состояние при попадании: отравлен, парализован, испуган, ослеплён, опутан — "
        "или пустая строка), effect_ability (характеристика спасброска против эффекта) и effect_dc (8–15).",
        EnemyBlock,
        tone,
    )
    return normalize_enemy(block)


async def generate_loot(
    theme: str, world_desc: str, context: str, tone: str = ""
) -> list[LootItem]:
    weapons = ", ".join(srd.WEAPONS)
    armors = ", ".join(srd.ARMORS)
    result = await _parse(
        "loot",
        f"Мир кампании (тема «{theme}»):\n{world_desc}\n\n"
        f"Контекст: {context}\n\n"
        "Придумай 1–3 предмета добычи, уместных в этой ситуации. Для каждого: name (название), "
        "kind — строго одно из: weapon, armor, shield, item; base — название базового предмета "
        f"из правил (для weapon одно из: {weapons}; для armor одно из: {armors}; для shield — «Щит»; "
        "для item — пустая строка); bonus — магический бонус 0, 1, 2 или 3 (для item — 0; обычно 0 или 1); "
        "description — одно предложение.",
        LootList,
        tone,
    )
    cleaned: list[LootItem] = []
    for item in result.items[:3]:
        kind = item.kind.strip().lower()
        pool = {"weapon": srd.WEAPONS, "armor": srd.ARMORS, "shield": [srd.SHIELD_NAME]}.get(kind)
        base = dice.match_name(item.base, pool) if pool and item.base else None
        if kind in ("weapon", "armor", "shield") and base is None:
            kind, base = "item", ""
        if kind not in ("weapon", "armor", "shield"):
            kind = "item"
        item.kind, item.base = kind, base or ""
        item.bonus = max(0, min(3, item.bonus)) if kind != "item" else 0
        cleaned.append(item)
    return cleaned


CHECKABLE_TEXT = ", ".join(srd.ABILITIES) + "; навыки: " + ", ".join(srd.SKILLS)
DC_TEXT = ", ".join(f"{name} — {dc}" for name, dc in srd.DIFFICULTY_CLASSES.items())


async def generate_scene(ctx: SceneContext) -> SceneResult:
    chars = "\n".join(f"- {c}" for c in ctx.characters) if ctx.characters else "- пока нет"
    npcs = "\n".join(f"- {n}" for n in ctx.npcs) if ctx.npcs else "- пока нет"
    facts = "\n".join(f"- {f}" for f in ctx.facts) if ctx.facts else "- пока нет"
    secret_block = ""
    if ctx.hidden_npcs:
        secret_block += (
            "NPC, которых мастер тайно подготовил (игроки о них ещё не знают). Введи их в сюжет, "
            "когда это логично, и перечисли имена введённых в revealed_npcs:\n"
            + "\n".join(f"- {n}" for n in ctx.hidden_npcs) + "\n\n"
        )
    if ctx.hidden_enemies:
        secret_block += (
            "Противники, которых мастер тайно подготовил: " + "; ".join(ctx.hidden_enemies)
            + ". Это следующая угроза. Приведи героев к ним в этой или следующей сцене. Когда они "
            "появляются в тексте, поставь gm_enemies_appear = true. Пока они не появились, не придумывай "
            "других противников (new_enemy пустой).\n\n"
        )
    if ctx.visible_enemies:
        secret_block += (
            "Противники уже здесь, бой ещё не начат: " + "; ".join(ctx.visible_enemies)
            + ". Новых противников не добавляй.\n\n"
        )

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
            "Игровые события после последней сцены (броски, бои, урон, заклинания — это ФАКТЫ, "
            "их исход уже определён кубиками и должен быть отражён в сцене):\n"
            + "\n".join(f"- {e}" for e in ctx.events)
            + "\n\n"
        )
    else:
        events_block = ""

    prompt = (
        f"Мир кампании (тема «{ctx.theme}»):\n{ctx.world_desc}\n\n"
        f"Сложность кампании: {ctx.difficulty}.\n\n"
        f"Персонажи игроков (раса, класс, уровень, здоровье, состояния):\n{chars}\n\n"
        f"Известные NPC:\n{npcs}\n\n"
        f"Важные факты и открытые сюжетные нити:\n{facts}\n\n"
        f"{secret_block}{location_block}{summary_block}"
        f"Последние сцены:\n{history}\n\n"
        f"{actions_block}{events_block}"
        "Сгенерируй СЛЕДУЮЩУЮ сцену приключения. Правила:\n"
        "1. Сцена — прямое следствие заявленных действий и произошедших событий. "
        "Не игнорируй ни одно заявленное действие. Успешные броски ведут к успеху, "
        "проваленные — к осложнениям.\n"
        "2. Не противоречь предыдущим сценам и фактам: учитывай, где герои, что уже случилось "
        "и какие нити открыты.\n"
        "3. Учитывай здоровье и состояния: раненый действует хуже, персонаж с 0 HP без сознания и не "
        "действует сам, погибший персонаж больше не участвует. Не наноси урон и не убивай персонажей "
        "текстом сцены — урон и смерть определяют кубики.\n"
        "4. Если действие игрока имеет неопределённый исход и для него ещё НЕТ броска среди "
        "событий, запроси проверку в поле checks (не больше трёх за сцену) и НЕ описывай "
        "исход этого действия в тексте — опиши напряжённый момент и остановись. "
        f"attribute — характеристика или навык, строго из списка: {CHECKABLE_TEXT}. "
        "kind — check (проверка) или save (спасбросок от опасности). "
        f"difficulty — сложность по шкале: {DC_TEXT}. "
        "character — точное имя персонажа игрока. reason — одна фраза, что проверяется.\n"
        "5. Темп: сюжет должен двигаться. Каждая сцена приносит что-то новое: зацепку, препятствие, "
        "встречу, опасность или решение. Не держи героев в одном месте дольше 2–3 сцен — веди их к "
        "следующей цели. Но не меняй место и ситуацию в каждой сцене без причины. Больше действия, "
        "меньше описаний.\n"
        "6. Противники. Если по логике сюжета сейчас начинается схватка и других противников нет, "
        "опиши их и заполни new_enemy (кто это, коротко) и new_enemy_count (1–6). Не устраивай схватку "
        "сразу после боя — дай героям хотя бы одну сцену передышки. Обычно схватка бывает раз в 3–5 "
        "сцен. Не разыгрывай бой в тексте — его ведёт бот.\n"
        "7. new_npcs: новые важные персонажи, которых ты ввёл в этой сцене (имя и одно предложение, "
        "кто это). Не повторяй уже известных NPC. Пустой список, если новых нет.\n"
        "8. text: один короткий абзац, не больше 600 знаков: что произошло и что героям видно сейчас, "
        "без подробных описаний. Заканчивается открытым вопросом к игрокам. "
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
        "где отряд сейчас и какие вопросы остались открытыми. Один короткий абзац.",
        tone,
    )
