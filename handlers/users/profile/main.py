from __future__ import annotations

import re
from datetime import datetime

from aiogram import F, Router, html, types
from aiogram.enums import ButtonStyle
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters.callback_data import CallbackData
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
)

from loader import db
from states import ProfileEditState

router = Router()

PROFILE_BUTTON_TEXT = "👤 Mening profilim"
PROFILE_CANCEL_TEXT = "🔙 Bekor qilish"
PHONE_PATTERN = re.compile(r"^\+998\d{9}$")
NAME_PATTERN = re.compile(r"^[A-Za-zА-Яа-яЁёЎўҚқҒғҲҳʻʼ'`-]{2,50}$")


class ProfileCallback(CallbackData, prefix="profile"):
    action: str
    field: str = "-"


def normalize_name(raw: str) -> str:
    return " ".join(raw.strip().split())


def is_valid_name(name: str) -> bool:
    return bool(NAME_PATTERN.fullmatch(name))


def normalize_phone(raw_phone: str) -> str | None:
    raw_phone = raw_phone.strip()
    compact = re.sub(r"[^\d+]", "", raw_phone)

    if compact.startswith("+998") and len(compact) == 13:
        phone = compact
    elif compact.startswith("998") and len(compact) == 12:
        phone = f"+{compact}"
    elif compact.startswith("0") and len(compact) == 10:
        phone = f"+998{compact[1:]}"
    elif len(compact) == 9 and compact.isdigit():
        phone = f"+998{compact}"
    else:
        return None

    if not PHONE_PATTERN.fullmatch(phone):
        return None
    return phone


def format_date(value) -> str:
    if not value:
        return "-"
    if isinstance(value, datetime):
        return value.strftime("%d.%m.%Y %H:%M")
    return str(value)


def phone_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📱 Telefonni yuborish", request_contact=True, style=ButtonStyle.SUCCESS)],
            [KeyboardButton(text=PROFILE_CANCEL_TEXT, style=ButtonStyle.DANGER)],
        ],
        resize_keyboard=True,
        one_time_keyboard=True,
        input_field_placeholder="+998901234567",
    )


def profile_text(user, total_purchases: int, active_purchases: int) -> str:
    username = f"@{user['username']}" if user["username"] else "yo'q"
    return (
        "👤 <b>MENING PROFILIM</b>\n\n"
        f"Ism: <b>{html.quote(user['first_name'] or '-')}</b>\n"
        f"Familiya: <b>{html.quote(user['last_name'] or '-')}</b>\n"
        f"Telefon: <code>{html.quote(user['phone'] or '-')}</code>\n"
        f"Telegram: {html.quote(username)}\n"
        f"Telegram ID: <code>{user['telegram_id']}</code>\n"
        f"Ro'yxatdan o'tgan: {format_date(user['created_at'])}\n"
        f"Sotib olgan kurslar: <b>{active_purchases} ta faol</b> / {total_purchases} ta jami"
    )


def profile_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✏️ Ism",
                    callback_data=ProfileCallback(action="edit", field="first_name").pack(),
                    style=ButtonStyle.PRIMARY,
                ),
                InlineKeyboardButton(
                    text="✏️ Familiya",
                    callback_data=ProfileCallback(action="edit", field="last_name").pack(),
                    style=ButtonStyle.PRIMARY,
                ),
            ],
            [
                InlineKeyboardButton(
                    text="📞 Telefon",
                    callback_data=ProfileCallback(action="edit", field="phone").pack(),
                    style=ButtonStyle.SUCCESS,
                )
            ],
            [
                InlineKeyboardButton(
                    text="🔄 Yangilash",
                    callback_data=ProfileCallback(action="refresh").pack(),
                    style=ButtonStyle.PRIMARY,
                ),
                InlineKeyboardButton(
                    text="❌ Yopish",
                    callback_data=ProfileCallback(action="close").pack(),
                    style=ButtonStyle.DANGER,
                ),
            ],
        ]
    )


async def get_profile_payload(telegram_id: int):
    user = await db.select_user(telegram_id=telegram_id)
    if not user:
        return None, 0, 0
    total = await db.count_user_purchases(telegram_id)
    active = await db.count_user_purchases_by_status(telegram_id, "approved")
    return user, total, active


async def render_profile_message(message: types.Message) -> None:
    user, total, active = await get_profile_payload(message.from_user.id)
    if not user or not user["is_registered"]:
        await message.answer("Avval ro'yxatdan o'ting. Boshlash uchun /start ni bosing.")
        return

    await message.answer(
        profile_text(user=user, total_purchases=total, active_purchases=active),
        reply_markup=profile_keyboard(),
    )


async def edit_profile_message(call: types.CallbackQuery, answer: bool = True) -> None:
    user, total, active = await get_profile_payload(call.from_user.id)
    if answer:
        await call.answer()
    if not user or not user["is_registered"]:
        await call.message.answer("Avval ro'yxatdan o'ting. Boshlash uchun /start ni bosing.")
        return

    if call.message.photo:
        await call.message.delete()
        await call.message.answer(
            profile_text(user=user, total_purchases=total, active_purchases=active),
            reply_markup=profile_keyboard(),
        )
        return
    try:
        await call.message.edit_text(
            profile_text(user=user, total_purchases=total, active_purchases=active),
            reply_markup=profile_keyboard(),
        )
    except TelegramBadRequest as error:
        if "message is not modified" in str(error):
            return
        raise


@router.message(F.text == PROFILE_BUTTON_TEXT)
async def show_profile(message: types.Message):
    await render_profile_message(message)


@router.callback_query(ProfileCallback.filter(F.action == "refresh"))
async def refresh_profile(call: types.CallbackQuery):
    await edit_profile_message(call)


@router.callback_query(ProfileCallback.filter(F.action == "close"))
async def close_profile(call: types.CallbackQuery, state: FSMContext):
    await state.clear()
    await call.answer("Yopildi.")
    await call.message.delete()


@router.callback_query(ProfileCallback.filter(F.action == "edit"))
async def start_profile_edit(call: types.CallbackQuery, callback_data: ProfileCallback, state: FSMContext):
    user = await db.select_user(telegram_id=call.from_user.id)
    if not user or not user["is_registered"]:
        await call.answer("Avval ro'yxatdan o'ting.", show_alert=True)
        return

    await state.clear()
    await state.update_data(field=callback_data.field)
    await state.set_state(ProfileEditState.value)
    await call.answer()

    if callback_data.field == "first_name":
        await call.message.answer("👤 Yangi ismingizni kiriting:", reply_markup=ReplyKeyboardRemove())
    elif callback_data.field == "last_name":
        await call.message.answer("👤 Yangi familiyangizni kiriting:", reply_markup=ReplyKeyboardRemove())
    elif callback_data.field == "phone":
        await call.message.answer(
            "📞 Yangi telefon raqamingizni yuboring.\n"
            "Tugma orqali yuboring yoki qo'lda kiriting:\n"
            "<code>+998901234567</code>",
            reply_markup=phone_keyboard(),
        )


@router.message(ProfileEditState.value, F.text == PROFILE_CANCEL_TEXT)
async def cancel_profile_edit(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer("❌ Tahrirlash bekor qilindi.", reply_markup=ReplyKeyboardRemove())
    await render_profile_message(message)


async def finish_profile_edit(message: types.Message, state: FSMContext, value: str) -> None:
    data = await state.get_data()
    field = data.get("field")
    if field not in {"first_name", "last_name", "phone"}:
        await state.clear()
        await message.answer("Tahrirlash holati eskirgan. Qayta urinib ko'ring.")
        return

    await db.update_user_profile_field(message.from_user.id, field, value)
    await state.clear()
    await message.answer("✅ Profil ma'lumoti yangilandi.", reply_markup=ReplyKeyboardRemove())
    await render_profile_message(message)


@router.message(ProfileEditState.value, F.contact)
async def edit_profile_contact(message: types.Message, state: FSMContext):
    data = await state.get_data()
    if data.get("field") != "phone":
        await message.answer("Bu qadamda kontakt qabul qilinmaydi. Matn kiriting.")
        return

    if message.contact.user_id and message.contact.user_id != message.from_user.id:
        await message.answer("❗ Faqat o'zingizning telefon raqamingizni yuboring.")
        return

    phone = normalize_phone(message.contact.phone_number)
    if not phone:
        await message.answer("❗ Telefon formati noto'g'ri. Masalan: +998901234567")
        return

    await finish_profile_edit(message, state, phone)


@router.message(ProfileEditState.value, F.text)
async def edit_profile_value(message: types.Message, state: FSMContext):
    data = await state.get_data()
    field = data.get("field")
    raw_value = message.text or ""

    if field in {"first_name", "last_name"}:
        value = normalize_name(raw_value)
    elif field == "phone":
        value = normalize_phone(raw_value)
        if not value:
            await message.answer(
                "❗ Telefon raqam noto'g'ri.\n"
                "To'g'ri format: <code>+998901234567</code>",
                reply_markup=phone_keyboard(),
            )
            return
    else:
        await state.clear()
        await message.answer("Tahrirlash holati eskirgan. Qayta urinib ko'ring.")
        return

    await finish_profile_edit(message, state, value)


@router.message(ProfileEditState.value)
async def edit_profile_invalid_type(message: types.Message):
    await message.answer("Iltimos, matn yoki telefon uchun kontakt yuboring.")
