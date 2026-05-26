from __future__ import annotations

from aiogram import F, Router, html, types
from aiogram.enums import ButtonStyle
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters.callback_data import CallbackData
from aiogram.fsm.context import FSMContext
from aiogram.types import CopyTextButton, InlineKeyboardButton, InlineKeyboardMarkup

from data import config
from data.config import ADMINS
from filters.admin import IsBotAdminFilter
from loader import bot, db
from states import PaymentReceiptState

payment_router = Router()


class PaymentActionCallback(CallbackData, prefix="pay"):
    action: str
    purchase_id: int = 0


class PaymentReviewCallback(CallbackData, prefix="payrev"):
    action: str
    purchase_id: int


def format_price(price: int) -> str:
    if price <= 0:
        return "BEPUL"
    return f"{price:,}".replace(",", " ") + " so'm"


def payment_settings_ready() -> bool:
    return bool(config.PAYMENT_CARD_NUMBER and config.PAYMENT_CARD_OWNER)


def payment_card_pretty() -> str:
    card = config.PAYMENT_CARD_NUMBER.replace(" ", "")
    if len(card) == 16 and card.isdigit():
        return " ".join(card[index:index + 4] for index in range(0, 16, 4))
    return config.PAYMENT_CARD_NUMBER


def user_display_name(purchase) -> str:
    username = f"@{purchase['username']}" if purchase["username"] else "username yo'q"
    phone = purchase["phone"] or "telefon yo'q"
    return f"{purchase['full_name'] or '-'} | {username} | {phone}"


def payment_instruction_text(purchase) -> str:
    bank_line = f"\n🏦 Bank: <b>{html.quote(config.PAYMENT_BANK_NAME)}</b>" if config.PAYMENT_BANK_NAME else ""
    support_line = (
        f"\n\nSavol tug'ilsa: {html.quote(config.PAYMENT_SUPPORT_USERNAME)}"
        if config.PAYMENT_SUPPORT_USERNAME
        else ""
    )
    receipt_line = (
        "\n\n📎 Avvalgi chek saqlangan. Yangi screenshot yuborsangiz, eski chek o'rniga yangisi ko'rib chiqiladi."
        if purchase["receipt_file_id"]
        else ""
    )
    payment_note = f"ImkonEdu #{purchase['id']}"

    return (
        "💳 <b>TO'LOV MA'LUMOTLARI</b>\n\n"
        f"📘 Kurs: <b>{html.quote(purchase['course_name'])}</b>\n"
        f"💰 To'lanadigan summa: <b>{format_price(purchase['amount'])}</b>\n"
        f"🧾 To'lov ID: <code>#{purchase['id']}</code>\n\n"
        "━━━━━━━━━━━━━━\n"
        f"💳 Karta: <code>{html.quote(payment_card_pretty())}</code>\n"
        f"👤 Karta egasi: <b>{html.quote(config.PAYMENT_CARD_OWNER)}</b>"
        f"{bank_line}\n"
        f"📝 Izoh uchun: <code>{payment_note}</code>\n"
        "━━━━━━━━━━━━━━\n\n"
        "✅ <b>Qanday to'lash kerak?</b>\n"
        "1. Yuqoridagi kartaga aynan ko'rsatilgan summani o'tkazing.\n"
        "2. To'lov amalga oshgach, chek/screenshotni saqlang.\n"
        "3. Chek rasmini shu chatga yuboring.\n"
        "4. Admin tasdiqlagach, kurs guruhi yoki kanal linki avtomatik keladi.\n\n"
        "Muhim: boshqa kurs yoki boshqa summa uchun shu chekni yubormang."
        f"{receipt_line}"
        f"{support_line}"
    )


def payment_instruction_keyboard(purchase) -> InlineKeyboardMarkup:
    amount_text = str(purchase["amount"])
    payment_note = f"ImkonEdu #{purchase['id']}"
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="📋 Kartani nusxalash",
                    copy_text=CopyTextButton(text=config.PAYMENT_CARD_NUMBER),
                    style=ButtonStyle.PRIMARY,
                )
            ],
            [
                InlineKeyboardButton(
                    text="📋 Summani nusxalash",
                    copy_text=CopyTextButton(text=amount_text),
                    style=ButtonStyle.PRIMARY,
                ),
                InlineKeyboardButton(
                    text="📋 Izohni nusxalash",
                    copy_text=CopyTextButton(text=payment_note),
                    style=ButtonStyle.PRIMARY,
                ),
            ],
            [
                InlineKeyboardButton(
                    text="📸 Chek yuboraman",
                    callback_data=PaymentActionCallback(action="await_receipt", purchase_id=purchase["id"]).pack(),
                    style=ButtonStyle.SUCCESS,
                ),
                InlineKeyboardButton(
                    text="❌ Bekor qilish",
                    callback_data=PaymentActionCallback(action="cancel", purchase_id=purchase["id"]).pack(),
                    style=ButtonStyle.DANGER,
                ),
            ],
        ]
    )


def payment_review_keyboard(purchase) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(
                text="✅ Tasdiqlash",
                callback_data=PaymentReviewCallback(action="approve", purchase_id=purchase["id"]).pack(),
                style=ButtonStyle.SUCCESS,
            ),
            InlineKeyboardButton(
                text="❌ Rad etish",
                callback_data=PaymentReviewCallback(action="reject", purchase_id=purchase["id"]).pack(),
                style=ButtonStyle.DANGER,
            ),
        ],
        [
            InlineKeyboardButton(
                text="👤 Userga yozish",
                url=f"tg://user?id={purchase['telegram_id']}",
                style=ButtonStyle.PRIMARY,
            )
        ],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def payment_review_text(purchase) -> str:
    return (
        f"🧾 <b>YANGI TO'LOV CHEKI #{purchase['id']}</b>\n\n"
        f"📘 Kurs: <b>{html.quote(purchase['course_name'])}</b>\n"
        f"💰 Summa: <b>{format_price(purchase['amount'])}</b>\n"
        f"💳 Karta: <code>{html.quote(payment_card_pretty())}</code>\n\n"
        f"👤 User: {html.quote(user_display_name(purchase))}\n"
        f"🆔 Telegram ID: <code>{purchase['telegram_id']}</code>\n\n"
        "Chekni tekshirib, to'lov tushgan bo'lsa tasdiqlang."
    )


def approved_user_text(purchase) -> str:
    access_link = purchase["invite_link"] or purchase["course_telegram_link"]
    link_line = f"\n\n🔗 Kursga kirish: {html.quote(access_link)}" if access_link else ""
    return (
        "✅ <b>To'lov tasdiqlandi!</b>\n\n"
        f"📘 Kurs: <b>{html.quote(purchase['course_name'])}</b>\n"
        f"💰 Summa: <b>{format_price(purchase['amount'])}</b>\n\n"
        "Kursga kirish huquqi berildi. Guruh yoki kanalga kirgach, pinned postni o'qing."
        f"{link_line}"
    )


def approved_user_keyboard(purchase) -> InlineKeyboardMarkup | None:
    access_link = purchase["invite_link"] or purchase["course_telegram_link"]
    if not access_link:
        return None
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🔗 Kursga kirish",
                    url=access_link,
                    style=ButtonStyle.SUCCESS,
                )
            ]
        ]
    )


def rejected_user_text(purchase) -> str:
    note = purchase["admin_note"] or "Chek tasdiqlanmadi. Iltimos, to'lov ma'lumotlarini tekshirib qayta yuboring."
    return (
        "❌ <b>To'lov rad etildi.</b>\n\n"
        f"📘 Kurs: <b>{html.quote(purchase['course_name'])}</b>\n"
        f"💰 Summa: <b>{format_price(purchase['amount'])}</b>\n"
        f"📝 Sabab: {html.quote(note)}\n\n"
        "Kursni qayta sotib olish orqali to'lov ma'lumotlarini qayta olishingiz mumkin."
    )


async def notify_payment_config_missing(user_id: int, course_name: str) -> None:
    text = (
        "⚠️ <b>To'lov sozlamalari to'liq emas</b>\n\n"
        f"User ID: <code>{user_id}</code>\n"
        f"Kurs: <b>{html.quote(course_name)}</b>\n\n"
        "`.env` ichida PAYMENT_CARD_NUMBER va PAYMENT_CARD_OWNER ni to'ldiring."
    )
    for admin_id in ADMINS:
        try:
            await bot.send_message(admin_id, text)
        except Exception:
            pass


async def render_payment_instructions(call: types.CallbackQuery, state: FSMContext, purchase) -> None:
    if not payment_settings_ready():
        await state.clear()
        await call.answer("To'lov sozlamalari hali kiritilmagan.", show_alert=True)
        await notify_payment_config_missing(call.from_user.id, purchase["course_name"])
        text = (
            "⚠️ <b>To'lov vaqtincha mavjud emas.</b>\n\n"
            "Admin to'lov kartasini sozlamagan. Iltimos, keyinroq urinib ko'ring yoki admin bilan bog'laning."
        )
        if call.message.photo:
            await call.message.delete()
            await call.message.answer(text)
            return
        await call.message.edit_text(text)
        return

    await state.clear()
    await state.update_data(purchase_id=purchase["id"])
    await state.set_state(PaymentReceiptState.awaiting_receipt)
    text = payment_instruction_text(purchase)
    markup = payment_instruction_keyboard(purchase)

    await call.answer("To'lov ma'lumotlari ochildi.")
    if call.message.photo:
        await call.message.delete()
        await call.message.answer(text, reply_markup=markup)
        return
    await call.message.edit_text(text, reply_markup=markup)


async def send_payment_review_message(source_message: types.Message, purchase, receipt_kind: str) -> int:
    targets = [config.PAYMENT_APPROVAL_CHAT_ID] if config.PAYMENT_APPROVAL_CHAT_ID else []
    fallback_targets = ADMINS if not targets else []
    sent_count = 0
    text = payment_review_text(purchase)
    markup = payment_review_keyboard(purchase)
    receipt_file_id = purchase["receipt_file_id"]

    for chat_id in [*targets, *fallback_targets]:
        try:
            if receipt_kind == "photo":
                await bot.send_photo(chat_id=chat_id, photo=receipt_file_id, caption=text, reply_markup=markup)
            else:
                await bot.send_document(chat_id=chat_id, document=receipt_file_id, caption=text, reply_markup=markup)
            sent_count += 1
        except Exception:
            if targets:
                for admin_id in ADMINS:
                    try:
                        if receipt_kind == "photo":
                            await bot.send_photo(
                                chat_id=admin_id,
                                photo=receipt_file_id,
                                caption=text,
                                reply_markup=markup,
                            )
                        else:
                            await bot.send_document(
                                chat_id=admin_id,
                                document=receipt_file_id,
                                caption=text,
                                reply_markup=markup,
                            )
                        sent_count += 1
                    except Exception:
                        pass
            else:
                pass

    if not sent_count:
        await source_message.answer(
            "⚠️ Chek saqlandi, lekin adminlarga yuborishda texnik xatolik bo'ldi. "
            "Admin bilan bog'laning."
        )
    return sent_count


def receipt_payload(message: types.Message) -> tuple[str | None, str | None]:
    if message.photo:
        return message.photo[-1].file_id, "photo"

    document = message.document
    if not document:
        return None, None

    mime_type = document.mime_type or ""
    if mime_type.startswith("image/") or mime_type == "application/pdf":
        return document.file_id, "document"
    return None, None


async def edit_review_message(call: types.CallbackQuery, text: str) -> None:
    try:
        if call.message.photo or call.message.document:
            await call.message.edit_caption(caption=text, reply_markup=None)
            return
        await call.message.edit_text(text, reply_markup=None)
    except TelegramBadRequest as error:
        if "message is not modified" in str(error):
            return
        raise


@payment_router.callback_query(PaymentActionCallback.filter(F.action == "await_receipt"))
async def await_receipt_from_button(
    call: types.CallbackQuery,
    callback_data: PaymentActionCallback,
    state: FSMContext,
):
    purchase = await db.select_user_purchase(call.from_user.id, callback_data.purchase_id)
    if not purchase:
        await call.answer("Xarid topilmadi.", show_alert=True)
        return
    if purchase["status"] == "approved":
        await call.answer("Bu xarid allaqachon tasdiqlangan.", show_alert=True)
        return

    await state.clear()
    await state.update_data(purchase_id=purchase["id"])
    await state.set_state(PaymentReceiptState.awaiting_receipt)
    await call.answer("Chek rasmini yuboring.")
    await call.message.answer(
        "📸 Chek screenshotini kutyapman.\n\n"
        "Rasm sifatida yuboring. Agar bank ilovasi PDF bergan bo'lsa, PDF hujjat ham qabul qilinadi."
    )


@payment_router.callback_query(PaymentActionCallback.filter(F.action == "instructions"))
async def show_payment_instructions_from_button(
    call: types.CallbackQuery,
    callback_data: PaymentActionCallback,
    state: FSMContext,
):
    purchase = await db.select_user_purchase(call.from_user.id, callback_data.purchase_id)
    if not purchase:
        await call.answer("Xarid topilmadi.", show_alert=True)
        return
    if purchase["status"] == "approved":
        await call.answer("Bu xarid allaqachon tasdiqlangan.", show_alert=True)
        return
    await render_payment_instructions(call=call, state=state, purchase=purchase)


@payment_router.callback_query(PaymentActionCallback.filter(F.action == "cancel"))
async def cancel_payment_waiting(call: types.CallbackQuery, state: FSMContext):
    await state.clear()
    await call.answer("Bekor qilindi.")
    if call.message.photo:
        await call.message.delete()
        return
    await call.message.edit_text("❌ To'lov jarayoni bekor qilindi.")


@payment_router.message(PaymentReceiptState.awaiting_receipt, F.photo)
@payment_router.message(PaymentReceiptState.awaiting_receipt, F.document)
async def receive_payment_receipt(message: types.Message, state: FSMContext):
    data = await state.get_data()
    purchase_id = data.get("purchase_id")
    if not purchase_id:
        await state.clear()
        await message.answer("To'lov sessiyasi topilmadi. Kursni qayta tanlab, sotib olish tugmasini bosing.")
        return

    receipt_file_id, receipt_kind = receipt_payload(message)
    if not receipt_file_id or not receipt_kind:
        await message.answer("Chekni rasm, image-hujjat yoki PDF shaklida yuboring.")
        return

    purchase = await db.submit_purchase_receipt(
        purchase_id=purchase_id,
        telegram_id=message.from_user.id,
        receipt_file_id=receipt_file_id,
        card_number_used=config.PAYMENT_CARD_NUMBER,
    )
    if not purchase:
        await state.clear()
        await message.answer("Xarid topilmadi yoki allaqachon tasdiqlangan. /start orqali qayta tekshiring.")
        return

    await send_payment_review_message(message, purchase, receipt_kind)
    await state.clear()
    await message.answer(
        "✅ <b>Chek qabul qilindi.</b>\n\n"
        f"📘 Kurs: <b>{html.quote(purchase['course_name'])}</b>\n"
        f"💰 Summa: <b>{format_price(purchase['amount'])}</b>\n"
        f"🧾 To'lov ID: <code>#{purchase['id']}</code>\n\n"
        "Admin to'lovni tekshiradi. Tasdiqlangach kurs guruhi yoki kanal linki avtomatik yuboriladi."
    )


@payment_router.message(PaymentReceiptState.awaiting_receipt)
async def receive_payment_receipt_invalid(message: types.Message):
    await message.answer(
        "📸 Iltimos, to'lov chekini rasm sifatida yuboring.\n"
        "PDF yoki image-hujjat ham qabul qilinadi."
    )


@payment_router.callback_query(PaymentReviewCallback.filter(F.action == "approve"), IsBotAdminFilter(ADMINS))
async def approve_payment(call: types.CallbackQuery, callback_data: PaymentReviewCallback):
    purchase = await db.select_purchase_by_id(callback_data.purchase_id)
    if not purchase:
        await call.answer("Xarid topilmadi.", show_alert=True)
        return
    if purchase["status"] == "approved":
        await call.answer("Allaqachon tasdiqlangan.", show_alert=True)
        return

    invite_link = purchase["course_telegram_link"]
    if not invite_link:
        await call.answer("Kursda guruh/kanal linki yo'q. Avval kurs linkini kiriting.", show_alert=True)
        return

    purchase = await db.approve_purchase(
        purchase_id=purchase["id"],
        approved_by=call.from_user.id,
        invite_link=invite_link,
        admin_note="To'lov tasdiqlandi.",
    )
    await call.answer("To'lov tasdiqlandi.")

    try:
        await bot.send_message(
            chat_id=purchase["telegram_id"],
            text=approved_user_text(purchase),
            reply_markup=approved_user_keyboard(purchase),
        )
    except Exception:
        pass

    admin_name = call.from_user.full_name
    await edit_review_message(
        call,
        payment_review_text(purchase)
        + f"\n\n✅ <b>TASDIQLANDI</b>\nAdmin: {html.quote(admin_name)}",
    )


@payment_router.callback_query(PaymentReviewCallback.filter(F.action == "reject"), IsBotAdminFilter(ADMINS))
async def reject_payment(call: types.CallbackQuery, callback_data: PaymentReviewCallback):
    purchase = await db.select_purchase_by_id(callback_data.purchase_id)
    if not purchase:
        await call.answer("Xarid topilmadi.", show_alert=True)
        return
    if purchase["status"] == "approved":
        await call.answer("Tasdiqlangan xaridni rad etib bo'lmaydi.", show_alert=True)
        return

    note = "Chek tasdiqlanmadi. To'lov summasi, karta yoki chek rasmini tekshirib qayta yuboring."
    purchase = await db.reject_purchase(
        purchase_id=purchase["id"],
        rejected_by=call.from_user.id,
        admin_note=note,
    )
    await call.answer("To'lov rad etildi.")

    try:
        await bot.send_message(chat_id=purchase["telegram_id"], text=rejected_user_text(purchase))
    except Exception:
        pass

    admin_name = call.from_user.full_name
    await edit_review_message(
        call,
        payment_review_text(purchase)
        + f"\n\n❌ <b>RAD ETILDI</b>\nAdmin: {html.quote(admin_name)}",
    )

