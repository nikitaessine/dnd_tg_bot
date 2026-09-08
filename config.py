import os

from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.environ["BOT_TOKEN"]
ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]

DB_PATH = os.path.join(os.path.dirname(__file__), "game.db")

# Атрибуты, из которых игрок выбирает четыре главных
ATTRIBUTES = [
    "Сила",
    "Ловкость",
    "Телосложение",
    "Интеллект",
    "Мудрость",
    "Харизма",
    "Удача",
    "Воля",
]
ATTRIBUTES_TO_PICK = 4

# Какие атрибуты за что отвечают в бою
ATTR_STR = "Сила"          # атака и урон в ближнем бою
ATTR_DEX = "Ловкость"      # класс доспеха, инициатива, альтернатива Силе
ATTR_CON = "Телосложение"  # здоровье

# Здоровье и развитие
DEFAULT_HP = 20        # базовое здоровье на 1 уровне (+ модификатор Телосложения)
HP_PER_LEVEL = 5       # прирост максимума здоровья за уровень (+ модификатор Телосложения)
XP_PER_LEVEL = 100     # опыта до следующего уровня = XP_PER_LEVEL * текущий уровень
MAX_LEVEL = 20

# Бой
BASE_ARMOR_CLASS = 10
UNARMED_DAMAGE = "1d4"

DIFFICULTIES = ["лёгкая", "обычная", "сложная"]
DEFAULT_DIFFICULTY = "обычная"

# Генерация сцен
SCENE_COOLDOWN = 20    # секунд между двумя /scene в одном чате
RECENT_SCENES = 5      # сколько последних сцен передаётся модели дословно
SUMMARY_BATCH = 3      # сколько сцен должно выпасть из окна, прежде чем их сожмут в пересказ

TELEGRAM_MAX_LEN = 4000  # лимит Telegram — 4096, оставляем запас

# Цены claude-opus-5 за миллион токенов, для /usage
PRICE_INPUT_PER_M = 5.0
PRICE_OUTPUT_PER_M = 25.0
