from aiogram import Router

from .support import router as support_router


def setup_groups_routers() -> Router:
    main_router = Router()
    main_router.include_router(support_router)
    return main_router
