from aiogram import Router

from filters import ChatPrivateFilter


def setup_routers() -> Router:
    from handlers.users.core import start
    from handlers.users.core import help
    from handlers.users.core import admin
    from .errors import error_handler

    router = Router()

    # Agar kerak bo'lsa, o'z filteringizni o'rnating
    start.router.message.filter(ChatPrivateFilter(chat_type=["private"]))

    router.include_routers(admin.router, start.router, help.router, error_handler.router)

    return router
