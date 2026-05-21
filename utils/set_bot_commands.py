from aiogram import Bot
from aiogram.client.session.middlewares.request_logging import logger
from aiogram.types import BotCommand, BotCommandScopeAllPrivateChats, BotCommandScopeChat

from data.config import ADMINS


async def set_default_commands(bot: Bot):
    public_commands = [
        BotCommand(command="start", description="Botni ishga tushirish"),
        BotCommand(command="help", description="Yordam"),
    ]
    admin_commands = [
        *public_commands,
        BotCommand(command="admin", description="Admin panel"),
    ]

    await bot.set_my_commands(commands=public_commands, scope=BotCommandScopeAllPrivateChats())
    for admin_id in ADMINS:
        try:
            await bot.set_my_commands(commands=admin_commands, scope=BotCommandScopeChat(chat_id=admin_id))
        except Exception as error:
            logger.info(f"Admin command scope o'rnatilmadi: {admin_id}. Xato: {error}")
