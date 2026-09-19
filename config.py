import os

from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.environ["BOT_TOKEN"]
ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]

DB_PATH = os.path.join(os.path.dirname(__file__), "game.db")

# Правила (характеристики, классы, таблицы опыта) живут в srd.py и rules.py.
# Здесь — только настраиваемое поведение бота.

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
