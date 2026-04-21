from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

ADMIN_MENU_ITEMS = [
    ("stats", "📊 Statistics"),
    ("users", "👥 Users"),
    ("storage", "💾 Storage"),
    ("quality", "🎬 Quality Control"),
    ("files", "🗑 File Management"),
    ("settings", "⚙ Settings"),
]


def quality_keyboard(options: list[tuple[str, str]]) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for quality, label in options:
        kb.add(InlineKeyboardButton(text=label, callback_data=f"quality:{quality}"))
    return kb.adjust(2).as_markup()


def admin_menu_keyboard() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for action, text in ADMIN_MENU_ITEMS:
        kb.add(InlineKeyboardButton(text=text, callback_data=f"admin:{action}"))
    return kb.adjust(2).as_markup()
