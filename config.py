import os

from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.environ["BOT_TOKEN"]
ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]

DB_PATH = os.path.join(os.path.dirname(__file__), "game.db")

# Атрибуты, из которых игрок выбирает четыре
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

# Бонус к d20 за атрибут, выбранный при создании персонажа
ATTRIBUTE_BONUS = 3
