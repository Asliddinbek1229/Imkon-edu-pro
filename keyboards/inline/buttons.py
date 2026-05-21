from aiogram.enums import ButtonStyle
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


inline_keyboard = [[
    InlineKeyboardButton(text="✅ Tasdiqlash", callback_data="yes", style=ButtonStyle.SUCCESS),
    InlineKeyboardButton(text="❌ Bekor qilish", callback_data="no", style=ButtonStyle.DANGER),
]]
are_you_sure_markup = InlineKeyboardMarkup(inline_keyboard=inline_keyboard)
