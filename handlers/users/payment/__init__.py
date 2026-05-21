from aiogram import Router
from filters import ChatPrivateFilter
from .main import payment_router

def setup_payment_routers() -> Router:
    main_router = Router()

    payment_router.message.filter(ChatPrivateFilter(chat_type=["private"]))

    main_router.include_routers(
        payment_router
    )

    return main_router