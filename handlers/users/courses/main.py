from __future__ import annotations

import math
from math import ceil

from aiogram import F, Router, html, types
from aiogram.enums import ButtonStyle
from aiogram.filters import StateFilter
from aiogram.filters.callback_data import CallbackData
from aiogram.fsm.context import FSMContext
from aiogram.types import CopyTextButton, InlineKeyboardButton, InlineKeyboardMarkup

from handlers.users.purchases.main import MyPurchaseDetailCallback, MyPurchasesPageCallback
from loader import bot, db
from states import CouponState
from utils.misc.api.course_payment import create_course_payment

router = Router()

COURSES_PER_PAGE = 5
CATALOG_BUTTON_TEXT = "📚 Kurslar katalogi"
TELEGRAM_CAPTION_LIMIT = 1024


class CatalogPageCallback(CallbackData, prefix="cat_page"):
    page: int


class CatalogDetailCallback(CallbackData, prefix="cat_detail"):
    course_id: int
    page: int


class CatalogActionCallback(CallbackData, prefix="cat_action"):
    action: str  # menu | cancel | buy | free_join
    page: int = 1
    course_id: int = 0


class BuyFlowCallback(CallbackData, prefix="buyf"):
    action: str  # coupon_enter | coupon_skip | pay_full | pay_inst2 | pay_inst3 | cancel
    course_id: int
    coupon_id: int = 0
    page: int = 1


def format_price(price: int) -> str:
    if price <= 0:
        return "BEPUL"
    return f"{price:,}".replace(",", " ") + " so'm"


def fit_caption(text: str) -> str:
    if len(text) <= TELEGRAM_CAPTION_LIMIT:
        return text
    suffix = "\n\n…\nTo'liq tavsif uchun admin bilan bog'laning."
    return text[: TELEGRAM_CAPTION_LIMIT - len(suffix)].rstrip() + suffix


def course_catalog_text(courses: list, page: int, total: int) -> str:
    if not courses:
        return (
            "💎 <b>IMKON-EDU PRO KURSLAR</b>\n\n"
            "Hozircha faol kurslar mavjud emas.\n"
            "Keyinroq qayta tekshirib ko'ring."
        )

    total_pages = max(ceil(total / COURSES_PER_PAGE), 1)
    lines = [
        "💎 <b>IMKON-EDU PRO KURSLAR</b>",
        "Saralangan video kurslar",
        "",
        f"📄 Sahifa: <b>{page}/{total_pages}</b>",
        "",
    ]
    for index, course in enumerate(courses, start=1):
        status = "🎁" if course["price"] <= 0 else "💎"
        lines.append(f"{index}. {status} <b>{html.quote(course['name'])}</b>")

    lines.extend(
        [
            "",
            "Kurs haqida premium taqdimotni ko'rish uchun raqamni tanlang.",
        ]
    )
    return "\n".join(lines)


def catalog_keyboard(courses: list, page: int, total: int) -> InlineKeyboardMarkup:
    total_pages = max(ceil(total / COURSES_PER_PAGE), 1)
    rows: list[list[InlineKeyboardButton]] = []

    if courses:
        rows.append(
            [
                InlineKeyboardButton(
                    text=str(index),
                    callback_data=CatalogDetailCallback(course_id=course["id"], page=page).pack(),
                    style=ButtonStyle.PRIMARY,
                )
                for index, course in enumerate(courses, start=1)
            ]
        )

    nav_row: list[InlineKeyboardButton] = []
    if page > 1:
        nav_row.append(
            InlineKeyboardButton(
                text="⬅️ Oldingi",
                callback_data=CatalogPageCallback(page=page - 1).pack(),
                style=ButtonStyle.PRIMARY,
            )
        )
    if page < total_pages:
        nav_row.append(
            InlineKeyboardButton(
                text="Keyingi ➡️",
                callback_data=CatalogPageCallback(page=page + 1).pack(),
                style=ButtonStyle.PRIMARY,
            )
        )
    if nav_row:
        rows.append(nav_row)

    rows.append(
        [
            InlineKeyboardButton(
                text="🏠 Asosiy menyu",
                callback_data=CatalogActionCallback(action="menu").pack(),
                style=ButtonStyle.SUCCESS,
            ),
            InlineKeyboardButton(
                text="❌ Bekor qilish",
                callback_data=CatalogActionCallback(action="cancel").pack(),
                style=ButtonStyle.DANGER,
            ),
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def course_detail_text(course) -> str:
    includes = course["includes"] or "Video darslar, chizmalar, testlar va tahlillar"
    target_exam = course["target_exam"] or "DTM, Milliy Sertifikat, Attestatsiya"
    duration = course["duration"] or "Admin tomonidan belgilanadi"
    price_badge = "🎁 <b>BEPUL KURS</b>" if course["price"] <= 0 else "💎 <b>PREMIUM KURS</b>"
    price_line = f"💰 Narx: <b>{format_price(course['price'])}</b>\n" if course["show_price"] else ""

    return (
        "✨ <b>IMKON-EDU PRO</b>\n"
        f"{price_badge}\n\n"
        f"📘 <b>{html.quote(course['name'])}</b>\n"
        f"👨‍🏫 <b>Muallif:</b> {html.quote(course['author'])}\n\n"
        "━━━━━━━━━━━━━━\n"
        "📌 <b>Kurs paketi</b>\n"
        f"{price_line}"
        f"🎬 Video: <b>{course['video_count']} ta dars</b>\n"
        f"⏱ Davomiylik: <b>{html.quote(duration)}</b>\n"
        f"♾ Kirish: <b>{html.quote(course['access_type'])}</b>\n\n"
        "🎯 <b>Imtihonlar</b>\n"
        f"{html.quote(target_exam)}\n\n"
        "✨ <b>Ichida nimalar bor</b>\n"
        f"{html.quote(includes)}\n\n"
        "📝 <b>Tavsif</b>\n"
        f"{html.quote(course['description'])}\n\n"
        "⚡️ Joyingizni band qilish uchun pastdagi tugmani bosing."
    )


def course_detail_keyboard(course, page: int, pending_purchase=None, has_approved=False) -> InlineKeyboardMarkup:
    course_id = course["id"]
    show_free = course["show_free_button"] and bool(course["free_telegram_link"])
    show_paid = course["show_paid_button"] and course["price"] > 0

    action_rows: list[list[InlineKeyboardButton]] = []

    if show_free:
        action_rows.append([
            InlineKeyboardButton(
                text="🎁 Bepul kirish",
                callback_data=CatalogActionCallback(action="free_join", course_id=course_id, page=page).pack(),
                style=ButtonStyle.SUCCESS,
            )
        ])

    if show_paid and not has_approved:
        if pending_purchase:
            paid_btn_text = "⚡ To'lovni davom ettirish"
            btn_style = ButtonStyle.PRIMARY
        elif course["show_price"]:
            paid_btn_text = f"💎 {format_price(course['price'])} | Sotib olish"
            btn_style = ButtonStyle.SUCCESS
        else:
            paid_btn_text = "💎 Sotib olish"
            btn_style = ButtonStyle.SUCCESS
        action_rows.append([
            InlineKeyboardButton(
                text=paid_btn_text,
                callback_data=CatalogActionCallback(action="buy", course_id=course_id, page=page).pack(),
                style=btn_style,
            )
        ])

    if not show_free and not show_paid and course["price"] <= 0:
        # Narxi 0, show_free_button o'chirilgan — eski bepul olish xatti-harakati
        action_rows.append([
            InlineKeyboardButton(
                text="🎁 Bepul olish",
                callback_data=CatalogActionCallback(action="buy", course_id=course_id, page=page).pack(),
                style=ButtonStyle.SUCCESS,
            )
        ])

    return InlineKeyboardMarkup(
        inline_keyboard=[
            *action_rows,
            [
                InlineKeyboardButton(
                    text="📋 Kurs nomini nusxalash",
                    copy_text=CopyTextButton(text=course["name"][:256]),
                    style=ButtonStyle.PRIMARY,
                )
            ],
            [
                InlineKeyboardButton(
                    text="↩️ Orqaga",
                    callback_data=CatalogPageCallback(page=page).pack(),
                    style=ButtonStyle.PRIMARY,
                ),
                InlineKeyboardButton(
                    text="❌ Bekor qilish",
                    callback_data=CatalogActionCallback(action="cancel").pack(),
                    style=ButtonStyle.DANGER,
                ),
            ],
        ]
    )


async def render_catalog(message: types.Message, page: int = 1) -> None:
    total = await db.count_active_courses()
    total_pages = max(ceil(total / COURSES_PER_PAGE), 1)
    page = min(max(page, 1), total_pages)
    offset = (page - 1) * COURSES_PER_PAGE
    courses = await db.select_active_courses_page(limit=COURSES_PER_PAGE, offset=offset)

    await message.answer(
        course_catalog_text(courses=courses, page=page, total=total),
        reply_markup=catalog_keyboard(courses=courses, page=page, total=total),
    )


async def edit_or_send_catalog(call: types.CallbackQuery, page: int = 1, answer: bool = True) -> None:
    total = await db.count_active_courses()
    total_pages = max(ceil(total / COURSES_PER_PAGE), 1)
    page = min(max(page, 1), total_pages)
    offset = (page - 1) * COURSES_PER_PAGE
    courses = await db.select_active_courses_page(limit=COURSES_PER_PAGE, offset=offset)
    text = course_catalog_text(courses=courses, page=page, total=total)
    markup = catalog_keyboard(courses=courses, page=page, total=total)

    if answer:
        await call.answer()
    if call.message.photo or call.message.video:
        await call.message.delete()
        await call.message.answer(text, reply_markup=markup)
        return
    await call.message.edit_text(text, reply_markup=markup)


async def render_course_detail(call: types.CallbackQuery, course_id: int, page: int) -> None:
    course = await db.select_course(course_id)
    if not course or not course["is_active"]:
        await call.answer("Kurs topilmadi yoki vaqtincha yopilgan.", show_alert=True)
        await edit_or_send_catalog(call, page=page, answer=False)
        return

    await call.answer()
    text = course_detail_text(course)

    pending_purchase = None
    has_approved = False
    if course["price"] > 0:
        user = await db.select_user(telegram_id=call.from_user.id)
        if user:
            approved = await db.select_active_purchase_for_course(user["id"], course["id"])
            if approved and approved["status"] == "approved":
                has_approved = True
            elif not approved:
                pending_purchase = await db.get_pending_course_purchase(call.from_user.id, course["id"])
            elif approved and approved["status"] == "pending":
                pending_purchase = approved

    markup = course_detail_keyboard(course=course, page=page, pending_purchase=pending_purchase, has_approved=has_approved)
    caption = fit_caption(text)

    if course.get("video_file_id"):
        if call.message.video:
            await call.message.edit_caption(caption=caption, reply_markup=markup)
            return
        await call.message.delete()
        await call.message.answer_video(
            video=course["video_file_id"], caption=caption, reply_markup=markup
        )
        return

    if course["thumbnail"]:
        if call.message.photo:
            await call.message.edit_caption(caption=caption, reply_markup=markup)
            return
        await call.message.delete()
        await call.message.answer_photo(photo=course["thumbnail"], caption=caption, reply_markup=markup)
        return

    if call.message.photo or call.message.video:
        await call.message.delete()
        await call.message.answer(text, reply_markup=markup)
        return
    await call.message.edit_text(text, reply_markup=markup)


@router.message(F.text == CATALOG_BUTTON_TEXT)
async def show_catalog(message: types.Message):
    await render_catalog(message=message, page=1)


@router.callback_query(CatalogPageCallback.filter())
async def paginate_catalog(call: types.CallbackQuery, callback_data: CatalogPageCallback):
    await edit_or_send_catalog(call=call, page=callback_data.page)


@router.callback_query(CatalogDetailCallback.filter())
async def show_course_detail(call: types.CallbackQuery, callback_data: CatalogDetailCallback):
    await render_course_detail(
        call=call,
        course_id=callback_data.course_id,
        page=callback_data.page,
    )


@router.callback_query(CatalogActionCallback.filter(F.action == "menu"))
async def catalog_back_to_menu(call: types.CallbackQuery):
    await call.answer("Asosiy menyu ochiq.")
    await call.message.delete()


@router.callback_query(CatalogActionCallback.filter(F.action == "cancel"))
async def catalog_cancel(call: types.CallbackQuery):
    await call.answer("Bekor qilindi.")
    await call.message.delete()


@router.callback_query(CatalogActionCallback.filter(F.action == "free_join"))
async def catalog_free_join(call: types.CallbackQuery, callback_data: CatalogActionCallback):
    course = await db.select_course(callback_data.course_id)
    if not course or not course["is_active"]:
        await call.answer("Kurs topilmadi yoki vaqtincha yopilgan.", show_alert=True)
        return
    if not course["show_free_button"] or not course["free_telegram_link"]:
        await call.answer("Bepul kirish hozir mavjud emas.", show_alert=True)
        return

    purchase = await db.create_free_purchase(call.from_user.id, course["id"])
    if not purchase:
        await call.answer("Avval ro'yxatdan o'ting: /start", show_alert=True)
        return

    access_link = purchase["invite_link"] or course["free_telegram_link"]
    text = (
        "🎁 <b>Bepul kirish tasdiqlandi!</b>\n\n"
        f"📘 Kurs: <b>{html.quote(course['name'])}</b>\n\n"
        "Pastdagi tugmani bosib bepul kanalga kirish mumkin."
    )
    markup = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🔗 Bepul kanalga kirish",
                    url=access_link,
                    style=ButtonStyle.SUCCESS,
                )
            ],
            [
                InlineKeyboardButton(
                    text="📚 Katalogga qaytish",
                    callback_data=CatalogPageCallback(page=callback_data.page).pack(),
                    style=ButtonStyle.PRIMARY,
                )
            ],
        ]
    )
    await call.answer("Bepul kirish linki yuborildi.")
    if call.message.photo or call.message.video:
        await call.message.delete()
        await call.message.answer(text, reply_markup=markup)
        return
    await call.message.edit_text(text, reply_markup=markup)


def _coupon_keyboard(course_id: int, page: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🎟 Kupon kodim bor",
                    callback_data=BuyFlowCallback(action="coupon_enter", course_id=course_id, page=page).pack(),
                    style=ButtonStyle.PRIMARY,
                )
            ],
            [
                InlineKeyboardButton(
                    text="⏭️ Kuponsiz davom etish",
                    callback_data=BuyFlowCallback(action="coupon_skip", course_id=course_id, page=page).pack(),
                    style=ButtonStyle.SUCCESS,
                )
            ],
            [
                InlineKeyboardButton(
                    text="❌ Bekor qilish",
                    callback_data=BuyFlowCallback(action="cancel", course_id=course_id, page=page).pack(),
                    style=ButtonStyle.DANGER,
                )
            ],
        ]
    )


def _payment_method_keyboard(course, discounted_price: int, coupon_id: int, page: int) -> InlineKeyboardMarkup:
    course_id = course["id"]
    rows: list[list[InlineKeyboardButton]] = [
        [
            InlineKeyboardButton(
                text=f"💳 To'liq to'lash – {format_price(discounted_price)}",
                callback_data=BuyFlowCallback(
                    action="pay_full", course_id=course_id, coupon_id=coupon_id, page=page
                ).pack(),
                style=ButtonStyle.SUCCESS,
            )
        ]
    ]
    if course.get("installment_available"):
        inst2 = math.ceil(discounted_price / 2)
        inst3 = math.ceil(discounted_price / 3)
        rows.append([
            InlineKeyboardButton(
                text=f"📅 2 oyga – {format_price(inst2)} × 2",
                callback_data=BuyFlowCallback(
                    action="pay_inst2", course_id=course_id, coupon_id=coupon_id, page=page
                ).pack(),
                style=ButtonStyle.PRIMARY,
            )
        ])
        rows.append([
            InlineKeyboardButton(
                text=f"📅 3 oyga – {format_price(inst3)} × 3",
                callback_data=BuyFlowCallback(
                    action="pay_inst3", course_id=course_id, coupon_id=coupon_id, page=page
                ).pack(),
                style=ButtonStyle.PRIMARY,
            )
        ])
    rows.append([
        InlineKeyboardButton(
            text="❌ Bekor qilish",
            callback_data=BuyFlowCallback(action="cancel", course_id=course_id, page=page).pack(),
            style=ButtonStyle.DANGER,
        )
    ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def _send_or_edit(call: types.CallbackQuery, text: str, markup=None) -> types.Message:
    if call.message.photo or call.message.video:
        await call.message.delete()
        return await call.message.answer(text, reply_markup=markup)
    await call.message.edit_text(text, reply_markup=markup)
    return call.message


async def _show_payment_methods(chat_id: int, msg_id: int, course, discounted_price: int, coupon, page: int):
    original = course["price"]
    course_line = f"📚 <b>{html.quote(course['name'])}</b>"
    if coupon:
        discount_display = (
            f"{coupon['discount_percent']}%"
            if coupon["discount_percent"]
            else format_price(coupon["discount_amount"])
        )
        price_line = (
            f"\n💰 Narx: <s>{format_price(original)}</s> → <b>{format_price(discounted_price)}</b>"
            f"\n🎟 Kupon chegirmasi: <b>-{discount_display}</b>"
        )
    else:
        price_line = f"\n💰 Narx: <b>{format_price(discounted_price)}</b>"
    coupon_id = coupon["id"] if coupon else 0
    text = (
        "💳 <b>TO'LOV USULINI TANLANG</b>\n\n"
        f"{course_line}"
        f"{price_line}\n\n"
        "Quyidagi to'lov usullaridan birini tanlang:"
    )
    markup = _payment_method_keyboard(course, discounted_price, coupon_id, page)
    await bot.edit_message_text(chat_id=chat_id, message_id=msg_id, text=text, reply_markup=markup)


@router.callback_query(CatalogActionCallback.filter(F.action == "buy"))
async def catalog_buy(call: types.CallbackQuery, callback_data: CatalogActionCallback, state: FSMContext):
    course = await db.select_course(callback_data.course_id)
    if not course or not course["is_active"]:
        await call.answer("Kurs topilmadi yoki vaqtincha yopilgan.", show_alert=True)
        return

    await state.clear()
    await db.cancel_pending_purchases_for_course(call.from_user.id, callback_data.course_id)

    if course["price"] <= 0:
        purchase = await db.create_pending_purchase(call.from_user.id, course["id"])
        if not purchase:
            await call.answer("Avval ro'yxatdan o'ting: /start", show_alert=True)
            return
        await call.answer("Kurs biriktirildi.")
        text = (
            "✅ <b>Kurs sizga biriktirildi.</b>\n\n"
            f"📚 Kurs: <b>{html.quote(purchase['course_name'])}</b>\n"
            "Holat: ✅ Faol\n\n"
            "Kursni 'Mening sotib olganlarim' bo'limidan ko'rishingiz mumkin."
        )
        markup = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(
                    text="🛒 Xaridni ko'rish",
                    callback_data=MyPurchaseDetailCallback(purchase_id=purchase["id"], page=1).pack(),
                    style=ButtonStyle.SUCCESS,
                )],
                [InlineKeyboardButton(
                    text="📚 Katalogga qaytish",
                    callback_data=CatalogPageCallback(page=callback_data.page).pack(),
                    style=ButtonStyle.PRIMARY,
                )],
            ]
        )
        await _send_or_edit(call, text, markup)
        return

    await call.answer()
    text = (
        "🎟 <b>KUPON KODI</b>\n\n"
        f"📚 <b>{html.quote(course['name'])}</b>\n"
        f"💰 Narx: <b>{format_price(course['price'])}</b>\n\n"
        "Chegirma kupon kodingiz bormi?\n"
        "Kupon kurs narxini kamaytiradi."
    )
    msg = await _send_or_edit(call, text, _coupon_keyboard(course["id"], callback_data.page))
    msg_id = msg.message_id if msg else call.message.message_id
    await state.update_data(
        buy_course_id=course["id"],
        buy_original_price=course["price"],
        buy_discounted_price=course["price"],
        buy_coupon_id=0,
        buy_coupon_discount=0,
        buy_status_msg_id=msg_id,
        buy_status_chat_id=call.message.chat.id,
        buy_page=callback_data.page,
    )


@router.callback_query(BuyFlowCallback.filter(F.action == "coupon_enter"))
async def buy_coupon_enter(call: types.CallbackQuery, callback_data: BuyFlowCallback, state: FSMContext):
    await call.answer()
    data = await state.get_data()
    msg_id = data.get("buy_status_msg_id", call.message.message_id)
    await state.set_state(CouponState.enter_code)
    markup = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(
            text="❌ Bekor qilish",
            callback_data=BuyFlowCallback(
                action="cancel", course_id=callback_data.course_id, page=callback_data.page
            ).pack(),
            style=ButtonStyle.DANGER,
        )
    ]])
    await bot.edit_message_text(
        chat_id=call.message.chat.id,
        message_id=msg_id,
        text=(
            "🎟 <b>KUPON KODI</b>\n\n"
            "Kupon kodingizni yozing:\n"
            "<i>Misol: IMKON200</i>"
        ),
        reply_markup=markup,
    )


@router.callback_query(BuyFlowCallback.filter(F.action == "coupon_skip"))
async def buy_coupon_skip(call: types.CallbackQuery, callback_data: BuyFlowCallback, state: FSMContext):
    await call.answer()
    data = await state.get_data()
    course = await db.select_course(callback_data.course_id)
    if not course:
        await call.answer("Kurs topilmadi.", show_alert=True)
        return
    await state.update_data(buy_coupon_id=0, buy_coupon_discount=0, buy_discounted_price=course["price"])
    await _show_payment_methods(
        chat_id=call.message.chat.id,
        msg_id=data.get("buy_status_msg_id", call.message.message_id),
        course=course,
        discounted_price=course["price"],
        coupon=None,
        page=data.get("buy_page", 1),
    )


@router.message(StateFilter(CouponState.enter_code))
async def buy_coupon_code_input(message: types.Message, state: FSMContext):
    code = (message.text or "").strip()
    data = await state.get_data()
    chat_id = data.get("buy_status_chat_id", message.chat.id)
    msg_id = data.get("buy_status_msg_id")
    course_id = data.get("buy_course_id")
    original_price = data.get("buy_original_price", 0)
    page = data.get("buy_page", 1)

    await message.delete()

    coupon = await db.get_coupon_by_code(code)
    if not coupon or not coupon["is_active"]:
        markup = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(
                text="⏭️ Kuponsiz davom etish",
                callback_data=BuyFlowCallback(action="coupon_skip", course_id=course_id, page=page).pack(),
                style=ButtonStyle.SUCCESS,
            )],
            [InlineKeyboardButton(
                text="❌ Bekor qilish",
                callback_data=BuyFlowCallback(action="cancel", course_id=course_id, page=page).pack(),
                style=ButtonStyle.DANGER,
            )],
        ])
        await bot.edit_message_text(
            chat_id=chat_id,
            message_id=msg_id,
            text=(
                "❌ <b>Kupon topilmadi yoki faol emas.</b>\n\n"
                "Kupon kodini qayta kiriting yoki kuponsiz davom eting:"
            ),
            reply_markup=markup,
        )
        return

    from datetime import datetime, timezone
    if coupon["expires_at"] and coupon["expires_at"] < datetime.now(tz=timezone.utc):
        await bot.edit_message_text(
            chat_id=chat_id, message_id=msg_id,
            text="❌ <b>Kupon muddati tugagan.</b>\n\nBoshqa kupon kiriting yoki kuponsiz davom eting:",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(
                    text="⏭️ Kuponsiz",
                    callback_data=BuyFlowCallback(action="coupon_skip", course_id=course_id, page=page).pack(),
                    style=ButtonStyle.SUCCESS,
                ),
                InlineKeyboardButton(
                    text="❌ Bekor",
                    callback_data=BuyFlowCallback(action="cancel", course_id=course_id, page=page).pack(),
                    style=ButtonStyle.DANGER,
                ),
            ]]),
        )
        return

    if coupon["max_uses"] is not None and coupon["uses_count"] >= coupon["max_uses"]:
        await bot.edit_message_text(
            chat_id=chat_id, message_id=msg_id,
            text="❌ <b>Kupon limitiga yetildi.</b>\n\nBu kupon endi ishlamaydi.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(
                    text="⏭️ Kuponsiz",
                    callback_data=BuyFlowCallback(action="coupon_skip", course_id=course_id, page=page).pack(),
                    style=ButtonStyle.SUCCESS,
                ),
                InlineKeyboardButton(
                    text="❌ Bekor",
                    callback_data=BuyFlowCallback(action="cancel", course_id=course_id, page=page).pack(),
                    style=ButtonStyle.DANGER,
                ),
            ]]),
        )
        return

    already_used = await db.has_user_used_coupon(coupon["id"], message.from_user.id)
    if already_used:
        await bot.edit_message_text(
            chat_id=chat_id, message_id=msg_id,
            text="❌ <b>Bu kuponi allaqachon ishlatgansiz.</b>\n\nHar bir kupon bir marta ishlatiladi.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(
                    text="⏭️ Kuponsiz",
                    callback_data=BuyFlowCallback(action="coupon_skip", course_id=course_id, page=page).pack(),
                    style=ButtonStyle.SUCCESS,
                ),
                InlineKeyboardButton(
                    text="❌ Bekor",
                    callback_data=BuyFlowCallback(action="cancel", course_id=course_id, page=page).pack(),
                    style=ButtonStyle.DANGER,
                ),
            ]]),
        )
        return

    if coupon.get("course_id") and coupon["course_id"] != course_id:
        await bot.edit_message_text(
            chat_id=chat_id, message_id=msg_id,
            text="❌ <b>Bu kupon ushbu kurs uchun mo'ljallanmagan.</b>\n\nBoshqa kupon kiriting yoki kuponsiz davom eting:",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(
                    text="⏭️ Kuponsiz",
                    callback_data=BuyFlowCallback(action="coupon_skip", course_id=course_id, page=page).pack(),
                    style=ButtonStyle.SUCCESS,
                ),
                InlineKeyboardButton(
                    text="❌ Bekor",
                    callback_data=BuyFlowCallback(action="cancel", course_id=course_id, page=page).pack(),
                    style=ButtonStyle.DANGER,
                ),
            ]]),
        )
        return

    if coupon["discount_percent"]:
        discount = int(original_price * coupon["discount_percent"] / 100)
    else:
        discount = coupon["discount_amount"]
    discounted = max(original_price - discount, 0)

    await state.update_data(
        buy_coupon_id=coupon["id"],
        buy_coupon_discount=discount,
        buy_discounted_price=discounted,
    )
    await state.set_state(None)

    course = await db.select_course(course_id)
    await _show_payment_methods(chat_id, msg_id, course, discounted, coupon, page)


@router.callback_query(BuyFlowCallback.filter(F.action == "pay_full"))
async def buy_pay_full(call: types.CallbackQuery, callback_data: BuyFlowCallback, state: FSMContext):
    await call.answer("To'lov sahifasi tayyorlanmoqda…")
    data = await state.get_data()
    course = await db.select_course(callback_data.course_id)
    if not course:
        return

    discounted = data.get("buy_discounted_price", course["price"])
    coupon_id = callback_data.coupon_id or None
    coupon_discount = data.get("buy_coupon_discount", 0)
    original_price = data.get("buy_original_price", course["price"])
    msg_id = data.get("buy_status_msg_id", call.message.message_id)
    page = data.get("buy_page", callback_data.page)

    result = await create_course_payment(
        tg_id=call.from_user.id,
        course_id=course["id"],
        course_name=course["name"],
        course_link=course["telegram_link"] or "",
        amount=discounted,
    )

    if not result or not result.get("payment_url"):
        await bot.edit_message_text(
            chat_id=call.message.chat.id, message_id=msg_id,
            text="⚠️ <b>To'lov tizimida xatolik.</b>\n\nKeyinroq urinib ko'ring yoki admin bilan bog'laning.",
        )
        await state.clear()
        return

    await db.create_custom_purchase(
        telegram_id=call.from_user.id,
        course_id=course["id"],
        amount=discounted,
        coupon_id=coupon_id,
        original_amount=original_price,
        coupon_discount=coupon_discount,
        is_installment=False,
        click_order_id=result["order_id"],
    )
    if coupon_id:
        await db.increment_coupon_uses(coupon_id)

    await state.clear()

    markup = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💳 CLICK orqali to'lash", url=result["payment_url"])],
        [InlineKeyboardButton(
            text="❌ Bekor qilish",
            callback_data=CatalogPageCallback(page=page).pack(),
            style=ButtonStyle.DANGER,
        )],
    ])
    await bot.edit_message_text(
        chat_id=call.message.chat.id,
        message_id=msg_id,
        text=(
            "💳 <b>CLICK orqali to'lov</b>\n\n"
            f"📚 Kurs: <b>{html.quote(course['name'])}</b>\n"
            f"💰 Summa: <b>{format_price(discounted)}</b>\n\n"
            "Pastdagi tugmani bosib to'lovni amalga oshiring.\n"
            "To'lov tasdiqlangach, kurs linki <b>avtomatik</b> yuboriladi."
        ),
        reply_markup=markup,
    )


@router.callback_query(BuyFlowCallback.filter(F.action.in_({"pay_inst2", "pay_inst3"})))
async def buy_pay_installment(call: types.CallbackQuery, callback_data: BuyFlowCallback, state: FSMContext):
    await call.answer()
    data = await state.get_data()
    course = await db.select_course(callback_data.course_id)
    if not course:
        return

    count = 2 if callback_data.action == "pay_inst2" else 3
    discounted = data.get("buy_discounted_price", course["price"])
    coupon_id = callback_data.coupon_id or None
    coupon_discount = data.get("buy_coupon_discount", 0)
    original_price = data.get("buy_original_price", course["price"])
    msg_id = data.get("buy_status_msg_id", call.message.message_id)

    purchase = await db.create_custom_purchase(
        telegram_id=call.from_user.id,
        course_id=course["id"],
        amount=discounted,
        coupon_id=coupon_id,
        original_amount=original_price,
        coupon_discount=coupon_discount,
        is_installment=True,
    )
    if not purchase:
        await call.answer("Xatolik. Qayta urinib ko'ring.", show_alert=True)
        return

    if coupon_id:
        await db.increment_coupon_uses(coupon_id)

    plan = await db.create_installment_plan(purchase["id"], discounted, count)
    first_payment = await db.get_next_pending_installment(plan["id"])

    result = await create_course_payment(
        tg_id=call.from_user.id,
        course_id=course["id"],
        course_name=course["name"],
        course_link=course.get("telegram_link") or "",
        amount=first_payment["amount"],
    )

    await state.clear()

    if not result or not result.get("payment_url"):
        await bot.edit_message_text(
            chat_id=call.message.chat.id,
            message_id=msg_id,
            text="⚠️ <b>To'lov tizimida xatolik.</b>\n\nKeyinroq urinib ko'ring yoki admin bilan bog'laning.",
        )
        return

    await db.set_installment_click_order(first_payment["id"], result["order_id"])

    markup = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💳 CLICK orqali to'lash", url=result["payment_url"])],
    ])
    await bot.edit_message_text(
        chat_id=call.message.chat.id,
        message_id=msg_id,
        text=(
            f"📅 <b>MUDDATLI TO'LOV — 1/{count}</b>\n\n"
            f"📚 Kurs: <b>{html.quote(course['name'])}</b>\n"
            f"💰 1-to'lov summasi: <b>{format_price(first_payment['amount'])}</b>\n"
            f"💰 Jami kurs narxi: <b>{format_price(discounted)}</b>\n\n"
            "Pastdagi tugma orqali birinchi to'lovni CLICK orqali amalga oshiring.\n"
            "✅ Birinchi to'lov tasdiqlanishi bilan kursga kirish huquqi beriladi."
        ),
        reply_markup=markup,
    )


@router.callback_query(BuyFlowCallback.filter(F.action == "cancel"))
async def buy_flow_cancel(call: types.CallbackQuery, callback_data: BuyFlowCallback, state: FSMContext):
    await call.answer("Bekor qilindi.")
    await state.clear()
    await call.message.delete()
