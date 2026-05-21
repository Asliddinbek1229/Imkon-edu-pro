from aiogram import Router
from filters import ChatPrivateFilter
from .admin import router as admin_router
from .echo import router as echo_router
from .start import router as start_router
from .help import router as help_router
from handlers.users.courses import router as courses_router
from handlers.users.profile import router as profile_router
from handlers.users.purchases import router as purchases_router

def setup_core_routers() -> Router:
    main_router = Router()

    start_router.message.filter(ChatPrivateFilter(chat_type=["private"]))
    courses_router.message.filter(ChatPrivateFilter(chat_type=["private"]))
    profile_router.message.filter(ChatPrivateFilter(chat_type=["private"]))
    purchases_router.message.filter(ChatPrivateFilter(chat_type=["private"]))
    help_router.message.filter(ChatPrivateFilter(chat_type=["private"]))
    admin_router.message.filter(ChatPrivateFilter(chat_type=["private"]))
    # echo_router.message.filter(ChatPrivateFilter(chat_type=["private"]))

    main_router.include_routers(
        admin_router,
        start_router,
        courses_router,
        profile_router,
        purchases_router,
        help_router,
        # echo_router
    )

    return main_router
