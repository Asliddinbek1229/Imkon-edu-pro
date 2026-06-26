from aiogram import F, Router, html, types
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)

from handlers.users.core.start import main_menu_keyboard
from loader import bot, db
from states import SupportState

router = Router()

FAQ_TEXT = "❓ Yordam / FAQ"
CONTACT_TEXT = "📞 Admin bilan bog'lanish"
CANCEL_SUPPORT_TEXT = "❌ Bekor qilish"

_DEFAULT_FAQ = (
    "❓ <b>Yordam / FAQ</b>\n\n"
    "Savollaringiz bo'lsa admin bilan bog'laning."
)


def cancel_support_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=CANCEL_SUPPORT_TEXT)]],
        resize_keyboard=True,
        is_persistent=True,
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


async def send_contact_page(target: types.Message | types.CallbackQuery) -> None:
    admin_username = await db.get_admin_username()
    support_group_id = await db.get_support_group_id()

    row = await db.get_setting("contact")
    admin_line = f"\n\n👨‍💼 <b>Admin:</b> @{html.quote(admin_username)}"
    bot_line = "\n\nYoki pastdagi tugma orqali bot orqali xabar yuboring:" if support_group_id else ""

    markup = (
        InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="✍️ Bot orqali xabar yozish", callback_data="support_start")]
            ]
        )
        if support_group_id
        else None
    )

    if row and (row["text"] or row["photo_file_id"]):
        text = (row["text"] or "") + admin_line + bot_line
        photo = row["photo_file_id"]
        if isinstance(target, types.Message):
            if photo:
                await target.answer_photo(photo=photo, caption=text, reply_markup=markup)
            else:
                await target.answer(text, reply_markup=markup)
        else:
            await target.answer()
            if photo:
                await target.message.answer_photo(photo=photo, caption=text, reply_markup=markup)
            else:
                await target.message.answer(text, reply_markup=markup)
    else:
        text = "📞 <b>Admin bilan bog'lanish</b>" + admin_line + bot_line
        if isinstance(target, types.Message):
            await target.answer(text, reply_markup=markup)
        else:
            await target.answer()
            await target.message.answer(text, reply_markup=markup)


@router.message(F.text == FAQ_TEXT)
async def show_faq(message: types.Message):
    await send_setting(message.from_user.id, "faq", _DEFAULT_FAQ)


@router.message(F.text == CONTACT_TEXT)
async def show_contact(message: types.Message):
    await send_contact_page(message)


@router.message(Command("help"))
async def bot_help(message: types.Message):
    await send_setting(message.from_user.id, "faq", _DEFAULT_FAQ)


@router.callback_query(F.data == "support_start")
async def support_start(call: types.CallbackQuery, state: FSMContext):
    support_group_id = await db.get_support_group_id()
    if not support_group_id:
        await call.answer("Xizmat vaqtincha mavjud emas.", show_alert=True)
        return
    await call.answer()
    await state.clear()
    await state.set_state(SupportState.waiting_message)
    await call.message.answer(
        "✍️ <b>Adminga xabar yozing</b>\n\n"
        "Har qanday xabar yuboring: matn, rasm, ovoz yoki video.\n"
        "Bekor qilish uchun pastdagi tugmani bosing.",
        reply_markup=cancel_support_keyboard(),
    )


@router.message(SupportState.waiting_message, F.text == CANCEL_SUPPORT_TEXT)
async def support_cancel(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer(
        "❌ Bekor qilindi.",
        reply_markup=main_menu_keyboard(user_id=message.from_user.id),
    )


@router.message(SupportState.waiting_message)
async def support_forward_to_group(message: types.Message, state: FSMContext):
    support_group_id = await db.get_support_group_id()
    if not support_group_id:
        await state.clear()
        await message.answer(
            "⚠️ Xizmat vaqtincha mavjud emas.",
            reply_markup=main_menu_keyboard(user_id=message.from_user.id),
        )
        return

    admin_username = await db.get_admin_username()
    user = await db.select_user(telegram_id=message.from_user.id)
    full_name = (user and user["full_name"]) or message.from_user.full_name or "—"
    phone = (user and user["phone"]) or "—"
    username = f"@{message.from_user.username}" if message.from_user.username else "yo'q"

    header_text = (
        "📩 <b>Foydalanuvchi xabari</b>\n"
        f"👤 {html.quote(full_name)}\n"
        f"🔗 {html.quote(username)}\n"
        f"🆔 <code>{message.from_user.id}</code>\n"
        f"📱 {html.quote(phone)}"
    )

    try:
        header_msg = await bot.send_message(support_group_id, header_text)
        await db.save_support_message(header_msg.message_id, message.from_user.id)

        sent = await bot.copy_message(
            chat_id=support_group_id,
            from_chat_id=message.chat.id,
            message_id=message.message_id,
        )
        await db.save_support_message(sent.message_id, message.from_user.id)
    except Exception:
        await state.clear()
        await message.answer(
            f"⚠️ Xabar yuborishda xatolik. Adminга to'g'ridan-to'g'ri yozing: "
            f"@{html.quote(admin_username)}",
            reply_markup=main_menu_keyboard(user_id=message.from_user.id),
        )
        return

    await state.clear()
    await message.answer(
        "✅ <b>Xabaringiz adminga yuborildi.</b>\n\n"
        "Tez orada javob olasiz.",
        reply_markup=main_menu_keyboard(user_id=message.from_user.id),
    )
