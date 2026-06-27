import asyncio
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.middlewares.request_logging import logger
from loader import db


def setup_handlers(dispatcher: Dispatcher) -> None:
    """HANDLERS"""
    from handlers.users.core import setup_core_routers
    from handlers.users.payment import setup_payment_routers
    from handlers.groups import setup_groups_routers

    dispatcher.include_router(setup_core_routers())
    dispatcher.include_router(setup_payment_routers())
    dispatcher.include_router(setup_groups_routers())


def setup_middlewares(dispatcher: Dispatcher, bot: Bot) -> None:
    """MIDDLEWARE"""
    from middlewares.throttling import ThrottlingMiddleware

    # Spamdan himoya qilish uchun o’rta dastur
    dispatcher.message.middleware(ThrottlingMiddleware(slow_mode_delay=0.5))


async def setup_aiogram(dispatcher: Dispatcher, bot: Bot) -> None:
    logger.info("Configuring aiogram")
    setup_handlers(dispatcher=dispatcher)
    setup_middlewares(dispatcher=dispatcher, bot=bot)
    logger.info("Configured aiogram")


async def database_connected():
    # Ma'lumotlar bazasiga ulanish va jadvallarni yaratish
    await db.create()
    await db.initialize_tables()


async def start_payment_server() -> None:
    from aiohttp import web
    from utils.misc.payment_server import make_payment_app
    from data.config import BOT_PAYMENT_SERVER_PORT

    app = make_payment_app()
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", BOT_PAYMENT_SERVER_PORT)
    await site.start()
    logger.info("Payment server started on port %s", BOT_PAYMENT_SERVER_PORT)


def _validate_config() -> None:
    from data.config import BOT_PAYMENT_SERVER_SECRET, COURSE_INTEGRATION_KEY
    if not BOT_PAYMENT_SERVER_SECRET:
        logger.warning(
            "OGOHLANTIRISH: BOT_PAYMENT_SERVER_SECRET o'rnatilmagan! "
            "Webhook endpoint autentifikatsiyasiz ishlaydi."
        )
    if not COURSE_INTEGRATION_KEY:
        logger.warning("OGOHLANTIRISH: COURSE_INTEGRATION_KEY o'rnatilmagan!")


async def aiogram_on_startup_polling(dispatcher: Dispatcher, bot: Bot) -> None:
    from utils.set_bot_commands import set_default_commands
    from utils.notify_admins import on_startup_notify

    _validate_config()
    logger.info("Database connected")
    await database_connected()

    asyncio.create_task(start_payment_server())

    from utils.scheduler import start_notification_scheduler
    asyncio.create_task(start_notification_scheduler(bot, db))

    logger.info("Starting polling")
    await bot.delete_webhook(drop_pending_updates=True)
    await setup_aiogram(bot=bot, dispatcher=dispatcher)
    await on_startup_notify(bot=bot)
    await set_default_commands(bot=bot)


async def aiogram_on_shutdown_polling(dispatcher: Dispatcher, bot: Bot):
    logger.info("Stopping polling")
    await bot.session.close()
    await dispatcher.storage.close()


def main():
    """CONFIG"""
    from data.config import BOT_TOKEN
    from aiogram.enums import ParseMode
    from aiogram.fsm.storage.memory import MemoryStorage

    # Bot va Dispatcher obyektlarini yaratish
    bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    storage = MemoryStorage()
    dispatcher = Dispatcher(storage=storage)

    # Startup va shutdown funksiyalarini ro‘yxatga olish
    dispatcher.startup.register(aiogram_on_startup_polling)
    dispatcher.shutdown.register(aiogram_on_shutdown_polling)

    # Pollingni boshlash
    asyncio.run(dispatcher.start_polling(bot, close_bot_session=True))


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        logger.info("Bot stopped!")
