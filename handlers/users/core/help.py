from aiogram import F, Router, types
from aiogram.filters import Command

from loader import bot, db

router = Router()

FAQ_TEXT = "❓ Yordam / FAQ"
CONTACT_TEXT = "📞 Admin bilan bog'lanish"

_DEFAULT_FAQ = (
    "❓ <b>Yordam / FAQ</b>\n\n"
    "Savollaringiz bo'lsa admin bilan bog'laning."
)
_DEFAULT_CONTACT = (
    "📞 <b>Admin bilan bog'lanish</b>\n\n"
    "Admin hali bog'lanish ma'lumotlarini kiritмagan."
)


async def send_setting(chat_id: int, key: str, default_text: str) -> None:
    row = await db.get_setting(key)
    if row and (row["text"] or row["photo_file_id"]):
        text = row["text"] or ""
        photo = row["photo_file_id"]
        if photo:
            await bot.send_photo(chat_id=chat_id, photo=photo, caption=text or None, parse_mode="HTML")
        else:
            await bot.send_message(chat_id=chat_id, text=text, parse_mode="HTML")
    else:
        await bot.send_message(chat_id=chat_id, text=default_text, parse_mode="HTML")


@router.message(F.text == FAQ_TEXT)
async def show_faq(message: types.Message):
    await send_setting(message.from_user.id, "faq", _DEFAULT_FAQ)


@router.message(F.text == CONTACT_TEXT)
async def show_contact(message: types.Message):
    await send_setting(message.from_user.id, "contact", _DEFAULT_CONTACT)


@router.message(Command("help"))
async def bot_help(message: types.Message):
    await send_setting(message.from_user.id, "faq", _DEFAULT_FAQ)
