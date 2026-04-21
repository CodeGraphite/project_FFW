from .admin import router as admin_router
from .file_management import router as file_router
from .user import router as user_router

__all__ = ["user_router", "admin_router", "file_router"]