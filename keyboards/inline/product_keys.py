from aiogram.enums import ButtonStyle
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


def build_keyboard(product_id: str):
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🛒 Xarid qilish", callback_data=f"product:{product_id}", style=ButtonStyle.PRIMARY)]
        ]
    )
