from aiogram import Dispatcher
from bot.middlewares import VerifiedUserMiddleware

from handlers import admin_router, file_router, user_router


def build_dispatcher() -> Dispatcher:
    dp = Dispatcher()
    # Ensure signup gating and admin access checks are consistently applied.
    dp.update.middleware(VerifiedUserMiddleware())
    dp.include_router(user_router)
    dp.include_router(admin_router)
    dp.include_router(file_router)
    return dp
