"""Telegram-бот для D&D-кампании: мир, персонажи, NPC, сцены и бои."""

import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import BotCommand

from config import BOT_TOKEN
from handlers import checks, fight, hero, items, magic, setup, story
from handlers.common import gm_commands_middleware

logging.basicConfig(level=logging.INFO)

# Меню команд Telegram (кнопка «/» рядом с полем ввода)
COMMANDS = [
    BotCommand(command="scene", description="Следующая сцена"),
    BotCommand(command="do", description="Заявить действие героя"),
    BotCommand(command="say", description="Реплика героя"),
    BotCommand(command="party", description="Кто есть кто"),
    BotCommand(command="roll", description="Бросок кубика / проверка"),
    BotCommand(command="attack", description="Атаковать противника"),
    BotCommand(command="cast", description="Колдовать заклинание"),
    BotCommand(command="spells", description="Мои заклинания"),
    BotCommand(command="endturn", description="Закончить ход"),
    BotCommand(command="hp", description="Здоровье отряда"),
    BotCommand(command="sheet", description="Лист персонажа"),
    BotCommand(command="inventory", description="Инвентарь"),
    BotCommand(command="status", description="Обзор кампании"),
    BotCommand(command="recap", description="В предыдущих сериях"),
    BotCommand(command="journal", description="Журнал: место и факты"),
    BotCommand(command="hero", description="Создать персонажа"),
    BotCommand(command="help", description="Все команды"),
]


async def main() -> None:
    bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher()
    dp.message.outer_middleware(gm_commands_middleware)
    dp.include_routers(
        setup.router, hero.router, checks.router, items.router, magic.router, fight.router, story.router
    )
    await bot.set_my_commands(COMMANDS)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
