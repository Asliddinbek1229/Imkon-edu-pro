import re

from aiogram import F, Router, html, types
from aiogram.client.session.middlewares.request_logging import logger
from aiogram.enums import ButtonStyle
from aiogram.filters import CommandStart, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import KeyboardButton, ReplyKeyboardMarkup, ReplyKeyboardRemove

from data.config import ADMINS
from loader import bot, db
from states import RegistrationState

router = Router()

REGISTER_TEXT = "🚀 Ro'yxatdan o'tish"
CANCEL_TEXT = "🔙 Bekor qilish"
PHONE_PATTERN = re.compile(r"^\+998\d{9}$")
NAME_PATTERN = re.compile(r"^[A-Za-zА-Яа-яЁёЎўҚқҒғҲҳʼʽ'`-]{2,50}$")


def record_get(record, key: str, default=None):
    if record is None:
        return default
    try:
        value = record[key]
    except (KeyError, IndexError, TypeError):
        return default
    return value if value not in (None, "") else default


def registration_intro_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=REGISTER_TEXT, style=ButtonStyle.SUCCESS)],
        ],
        resize_keyboard=True,
        is_persistent=True,
        input_field_placeholder="Ro'yxatdan o'tishni boshlang...",
    )


def main_menu_keyboard(user_id: int | None = None) -> ReplyKeyboardMarkup:
    keyboard = [
        [
            KeyboardButton(text="📚 Kurslar katalogi", style=ButtonStyle.PRIMARY),
            KeyboardButton(text="🛒 Mening sotib olganlarim", style=ButtonStyle.SUCCESS),
        ],
        [
            KeyboardButton(text="👤 Mening profilim", style=ButtonStyle.PRIMARY),
            KeyboardButton(text="❓ Yordam / FAQ", style=ButtonStyle.PRIMARY),
        ],
        [KeyboardButton(text="📞 Admin bilan bog'lanish", style=ButtonStyle.DANGER)],
    ]
    if user_id in ADMINS:
        keyboard.append([KeyboardButton(text="⚙️ Admin panel", style=ButtonStyle.PRIMARY)])

    return ReplyKeyboardMarkup(
        keyboard=keyboard,
        resize_keyboard=True,
        is_persistent=True,
        input_field_placeholder="Bo'limni tanlang...",
    )


def phone_request_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📱 Telefonni yuborish", request_contact=True, style=ButtonStyle.SUCCESS)],
            [KeyboardButton(text=CANCEL_TEXT, style=ButtonStyle.DANGER)],
        ],
        resize_keyboard=True,
        one_time_keyboard=True,
        input_field_placeholder="+998901234567",
    )


def onboarding_text() -> str:
    return (
        "🎓 <b>Imkon-edu Pro Kurslar</b>\n"
        "Biologiya bo'yicha video kurslar platformasi\n\n"
        "Bu bot orqali siz DTM, Milliy Sertifikat, Attestatsiya va Perevod "
        "imtihonlariga tayyorgarlik kurslarini tanlashingiz, xarid qilishingiz "
        "va tasdiqdan keyin yopiq Telegram guruhga kirish olishingiz mumkin.\n\n"
        "✨ <b>Ro'yxatdan o'tish 1 daqiqadan kam vaqt oladi</b>\n"
        "1. Ismingiz\n"
        "2. Familiyangiz\n"
        "3. Telefon raqamingiz\n\n"
        "Davom etish uchun pastdagi tugmani bosing."
    )


def main_menu_text(user, message: types.Message) -> str:
    first_name = record_get(user, "first_name") or message.from_user.first_name or message.from_user.full_name
    return (
        f"Assalomu alaykum, <b>{html.quote(first_name)}</b>!\n\n"
        "🎓 <b>Imkon-edu Pro Kurslar</b>\n"
        "Biologiya kurslari, xaridlaringiz va profilingiz bir joyda.\n\n"
        "🏠 <b>Asosiy menyu</b>\n"
        "Kerakli bo'limni pastdagi tugmalardan tanlang."
    )


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


async def notify_new_user_to_admins(message: types.Message) -> None:
    username = f"@{message.from_user.username}" if message.from_user.username else "yo'q"
    text = (
        "🆕 <b>Yangi foydalanuvchi botga kirdi</b>\n"
        f"👤 Ism: {html.quote(message.from_user.full_name)}\n"
        f"🔗 Username: {html.quote(username)}\n"
        f"🆔 Telegram ID: <code>{message.from_user.id}</code>"
    )
    for admin in ADMINS:
        try:
            await bot.send_message(chat_id=admin, text=text)
        except Exception as error:
            logger.info(f"Admin {admin} ga xabar yuborilmadi. Xato: {error}")


async def show_onboarding(message: types.Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer(
        onboarding_text(),
        reply_markup=registration_intro_keyboard(),
    )


async def start_registration(message: types.Message, state: FSMContext) -> None:
    await state.clear()
    await state.set_state(RegistrationState.first_name)
    await message.answer(
        "✅ <b>Ro'yxatdan o'tishni boshlaymiz</b>\n\n"
        "1/3 qadam\n"
        "👤 <b>Ismingizni kiriting</b>\n\n"
        "Misol: <code>Alisher</code>",
        reply_markup=ReplyKeyboardRemove(),
    )


@router.message(CommandStart())
async def do_start(message: types.Message, state: FSMContext):
    user = await db.add_user(
        telegram_id=message.from_user.id,
        full_name=message.from_user.full_name,
        username=message.from_user.username,
    )

    if user and not user["is_registered"]:
        await notify_new_user_to_admins(message)
        await show_onboarding(message, state)
        return

    await state.clear()
    await message.answer(
        main_menu_text(user, message),
        reply_markup=main_menu_keyboard(user_id=message.from_user.id),
    )


@router.message(StateFilter(None), F.text == REGISTER_TEXT)
async def registration_intro_clicked(message: types.Message, state: FSMContext):
    user = await db.add_user(
        telegram_id=message.from_user.id,
        full_name=message.from_user.full_name,
        username=message.from_user.username,
    )
    if user and user["is_registered"]:
        await message.answer(
            main_menu_text(user, message),
            reply_markup=main_menu_keyboard(user_id=message.from_user.id),
        )
        return

    await start_registration(message, state)


@router.message(RegistrationState.first_name, F.text == CANCEL_TEXT)
@router.message(RegistrationState.last_name, F.text == CANCEL_TEXT)
@router.message(RegistrationState.phone, F.text == CANCEL_TEXT)
async def cancel_registration(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer(
        "❌ Ro'yxatdan o'tish bekor qilindi.\n\n"
        "Davom ettirish uchun pastdagi tugmani bosing.",
        reply_markup=registration_intro_keyboard(),
    )


@router.message(RegistrationState.first_name, F.text)
async def registration_first_name(message: types.Message, state: FSMContext):
    first_name = normalize_name(message.text)
    await state.update_data(first_name=first_name)
    await state.set_state(RegistrationState.last_name)
    await message.answer(
        "2/3 qadam\n"
        "👤 <b>Familiyangizni kiriting</b>\n\n"
        "Misol: <code>Karimov</code>"
    )


@router.message(RegistrationState.last_name, F.text)
async def registration_last_name(message: types.Message, state: FSMContext):
    last_name = normalize_name(message.text)
    await state.update_data(last_name=last_name)
    await state.set_state(RegistrationState.phone)
    await message.answer(
        "3/3 qadam\n"
        "📞 <b>Telefon raqamingizni yuboring</b>\n\n"
        "Eng qulay usul: <b>Telefonni yuborish</b> tugmasi.\n"
        "Qo'lda kiritish ham mumkin: <code>+998901234567</code>",
        reply_markup=phone_request_keyboard(),
    )


async def finish_registration(message: types.Message, state: FSMContext, phone: str):
    data = await state.get_data()
    first_name = data.get("first_name")
    last_name = data.get("last_name")
    user = await db.update_user_registration(
        telegram_id=message.from_user.id,
        first_name=first_name,
        last_name=last_name,
        phone=phone,
    )
    await state.clear()
    await message.answer(
        "🎉 <b>Ro'yxatdan o'tish yakunlandi</b>\n\n"
        "Profil ma'lumotlaringiz:\n"
        f"👤 Ism: <b>{html.quote(user['first_name'])}</b>\n"
        f"👤 Familiya: <b>{html.quote(user['last_name'])}</b>\n"
        f"📞 Telefon: <code>{user['phone']}</code>\n\n"
        "Endi kurslar katalogini ko'rishingiz va xaridlarni boshqarishingiz mumkin.",
        reply_markup=main_menu_keyboard(user_id=message.from_user.id),
    )


@router.message(RegistrationState.phone, F.contact)
async def registration_phone_contact(message: types.Message, state: FSMContext):
    if not message.contact:
        await message.answer("❗ Kontakt topilmadi. Qayta yuboring.")
        return

    if message.contact.user_id and message.contact.user_id != message.from_user.id:
        await message.answer("❗ Faqat o'zingizning telefon raqamingizni yuboring.")
        return

    phone = normalize_phone(message.contact.phone_number)
    if not phone:
        await message.answer("❗ Telefon formati noto'g'ri. Masalan: +998901234567")
        return

    await finish_registration(message, state, phone)


@router.message(RegistrationState.phone, F.text)
async def registration_phone_manual(message: types.Message, state: FSMContext):
    phone = normalize_phone(message.text)
    if not phone:
        await message.answer(
            "❗ Telefon raqam noto'g'ri.\n"
            "To'g'ri format: <code>+998901234567</code>\n"
            "Yoki pastdagi tugma orqali yuboring.",
            reply_markup=phone_request_keyboard(),
        )
        return

    await finish_registration(message, state, phone)


@router.message(RegistrationState.phone)
async def registration_phone_invalid_type(message: types.Message):
    await message.answer("❗ Iltimos, telefon raqamini matn yoki kontakt sifatida yuboring.")
