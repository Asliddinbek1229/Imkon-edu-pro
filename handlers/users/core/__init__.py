from aiogram import Router
from filters import ChatPrivateFilter
from .admin import router as admin_router
from .echo import router as echo_router
from .start import router as start_router
from .help import router as help_router

def setup_core_routers() -> Router:
    main_router = Router()

    start_router.message.filter(ChatPrivateFilter(chat_type=["private"]))
    help_router.message.filter(ChatPrivateFilter(chat_type=["private"]))
    admin_router.message.filter(ChatPrivateFilter(chat_type=["private"]))
    # echo_router.message.filter(ChatPrivateFilter(chat_type=["private"]))

    main_router.include_routers(
        admin_router,
        start_router,
        help_router,
        # echo_router
    )

    return main_router