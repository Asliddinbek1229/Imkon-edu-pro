from __future__ import annotations

from datetime import date, datetime
from math import ceil

from aiogram import F, Router, html, types
from aiogram.enums import ButtonStyle
from aiogram.filters.callback_data import CallbackData
from aiogram.fsm.context import FSMContext
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from handlers.users.payment.main import NextInstallmentCallback
from loader import db
from utils.misc.api.course_payment import check_order_status, create_course_payment

router = Router()

PURCHASES_BUTTON_TEXT = "🛒 Mening sotib olganlarim"
PURCHASES_PER_PAGE = 5


class MyPurchasesPageCallback(CallbackData, prefix="myp"):
    page: int


class MyPurchaseDetailCallback(CallbackData, prefix="mypd"):
    purchase_id: int
    page: int = 1


class MyPurchaseActionCallback(CallbackData, prefix="mypa"):
    action: str
    purchase_id: int = 0
    page: int = 1


class EarlyRepaymentCallback(CallbackData, prefix="earlyp"):
    plan_id: int
    purchase_id: int


def format_price(price: int) -> str:
    if price <= 0:
        return "BEPUL"
    return f"{price:,}".replace(",", " ") + " so'm"


def format_date(value) -> str:
    if not value:
        return "-"
    if isinstance(value, datetime):
        return value.strftime("%d.%m.%Y %H:%M")
    return str(value)


def _fmt_date_short(value) -> str:
    """Faqat sana (vaqtsiz)."""
    if not value:
        return "—"
    if hasattr(value, "strftime"):
        return value.strftime("%d.%m.%Y")
    return str(value)


def _days_label(due_date) -> str:
    """Muddatga qancha kun qolganini yoki kechikkanini ko'rsatadi."""
    if not due_date:
        return ""
    today = date.today()
    delta = (due_date.date() if hasattr(due_date, "date") else due_date) - today
    days = delta.days
    if days < 0:
        return f"  ⚠️ {abs(days)} kun kechikdi"
    if days == 0:
        return "  ⚠️ Bugun!"
    if days <= 3:
        return f"  ⚠️ {days} kun qoldi"
    return ""


def status_label(status: str, purchase_type: str = "paid") -> str:
    if status == "approved" and purchase_type == "free":
        return "🎁 Bepul kirish"
    labels = {
        "pending": "⏳ Tekshirilmoqda",
        "approved": "✅ Faol",
        "rejected": "❌ Rad etilgan",
    }
    return labels.get(status, status)


def purchases_text(purchases: list, page: int, total: int) -> str:
    if not purchases:
        return (
            "🛒 <b>MENING SOTIB OLGANLARIM</b>\n\n"
            "Sizda hali sotib olingan kurslar yo'q.\n"
            "Kurslar katalogidan o'zingizga kerakli kursni tanlang."
        )

    total_pages = max(ceil(total / PURCHASES_PER_PAGE), 1)
    lines = [
        "🛒 <b>Mening sotib olganlarim</b>",
        f"<i>Sahifa {page} / {total_pages}  •  Jami: {total} ta kurs</i>",
        "",
    ]

    for index, p in enumerate(purchases, start=1):
        purchase_type = p.get("purchase_type", "paid")
        is_free = purchase_type == "free"
        plan_id = p.get("plan_id")
        plan_total = p.get("plan_total_count")

        # ── Holat ikonkasi ────────────────────────────────────────────────
        if is_free:
            status_icon = "🎁"
        elif plan_id and plan_total:
            plan_done = p.get("plan_status") == "completed"
            status_icon = "✅" if plan_done else "📅"
        else:
            status_icon = "✅"

        # ── Narx qatori ───────────────────────────────────────────────────
        price_str = format_price(p["amount"])
        if p.get("coupon_code"):
            pct = p.get("coupon_percent") or 0
            price_str += f" <i>(−{pct}% kupon)</i>" if pct else " <i>(kupon)</i>"

        # ── Bo'lib to'lash holati ─────────────────────────────────────────
        install_line = ""
        if plan_id and plan_total:
            paid_n = p.get("plan_paid_count") or 0
            plan_status = p.get("plan_status", "active")
            if plan_status == "completed":
                install_line = f"\n     └ 📊 {paid_n}/{plan_total} to'lov ✅ yakunlandi"
            else:
                bar = "▓" * paid_n + "░" * (plan_total - paid_n)
                nxt = p.get("next_due_date")
                urgency = _days_label(nxt) if nxt else ""
                due_str = f"  ⏰ {_fmt_date_short(nxt)}{urgency}" if nxt else ""
                install_line = f"\n     └ [{bar}] {paid_n}/{plan_total}{due_str}"

        block = (
            f"<b>{index}.</b> {status_icon} <b>{html.quote(p['course_name'])}</b>\n"
            f"💰 {price_str}   📅 {_fmt_date_short(p['created_at'])}"
            f"{install_line}"
        )
        lines.append(f"<blockquote>{block}</blockquote>")

    lines += ["", "👇 Batafsil ko'rish uchun raqamni tanlang:"]
    return "\n".join(lines)


def purchases_keyboard(purchases: list, page: int, total: int) -> InlineKeyboardMarkup:
    total_pages = max(ceil(total / PURCHASES_PER_PAGE), 1)
    rows: list[list[InlineKeyboardButton]] = []

    if purchases:
        rows.append(
            [
                InlineKeyboardButton(
                    text=str(index),
                    callback_data=MyPurchaseDetailCallback(purchase_id=purchase["id"], page=page).pack(),
                    style=ButtonStyle.PRIMARY,
                )
                for index, purchase in enumerate(purchases, start=1)
            ]
        )

    nav_row: list[InlineKeyboardButton] = []
    if page > 1:
        nav_row.append(
            InlineKeyboardButton(
                text="⬅️ Oldingi",
                callback_data=MyPurchasesPageCallback(page=page - 1).pack(),
                style=ButtonStyle.PRIMARY,
            )
        )
    if page < total_pages:
        nav_row.append(
            InlineKeyboardButton(
                text="Keyingi ➡️",
                callback_data=MyPurchasesPageCallback(page=page + 1).pack(),
                style=ButtonStyle.PRIMARY,
            )
        )
    if nav_row:
        rows.append(nav_row)

    rows.append(
        [
            InlineKeyboardButton(
                text="📚 Kurslar katalogi",
                callback_data=MyPurchaseActionCallback(action="catalog").pack(),
                style=ButtonStyle.SUCCESS,
            ),
            InlineKeyboardButton(
                text="❌ Bekor qilish",
                callback_data=MyPurchaseActionCallback(action="cancel").pack(),
                style=ButtonStyle.DANGER,
            ),
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def purchase_detail_text(purchase, plan=None, payments=None) -> str:
    purchase_type = purchase.get("purchase_type", "paid")
    is_free_type = purchase_type == "free"
    real_access_link = purchase.get("invite_link") or (
        purchase.get("course_free_telegram_link") if is_free_type
        else purchase.get("course_telegram_link")
    )

    # ─── Sarlavha ────────────────────────────────────────────────────────────
    type_label = "🎁 Bepul" if is_free_type else ("📅 Muddatli" if purchase.get("is_installment") else "💎 To'liq")
    lines = [
        f"📘 <b>{html.quote(purchase['course_name'])}</b>",
        "",
        f"Tur:   <b>{type_label}</b>",
        f"Holat: <b>{status_label(purchase['status'], purchase_type)}</b>",
        f"Sana:  <b>{_fmt_date_short(purchase.get('created_at'))}</b>",
    ]
    if purchase.get("approved_at"):
        lines.append(f"Tasdiqlangan: <b>{_fmt_date_short(purchase.get('approved_at'))}</b>")

    # ─── Narx bloki ──────────────────────────────────────────────────────────
    orig = purchase.get("original_amount") or 0
    disc = purchase.get("coupon_discount") or 0
    final = purchase.get("amount") or 0
    coupon_code = purchase.get("coupon_code") or ""

    lines.append("")
    lines.append("💰 <b>NARX MA'LUMOTLARI</b>")
    if disc and orig:
        lines.append(f"  Asl narx:       <b>{format_price(orig)}</b>")
        lines.append(f"  🎟 Kupon <code>{html.quote(coupon_code)}</code>:  −<b>{format_price(disc)}</b>")
        lines.append(f"  Siz to'ladingiz: <b>{format_price(final)}</b>")
        lines.append(f"  💚 Tejashingiz:  <b>{format_price(disc)}</b>")
    else:
        lines.append(f"  To'lov summasi: <b>{format_price(final)}</b>")

    # ─── Bo'lib to'lash jadvali ───────────────────────────────────────────────
    if plan and payments:
        paid_count   = sum(1 for p in payments if p["status"] == "paid")
        total_count  = plan["installments_count"]
        paid_amount  = sum(p["amount"] for p in payments if p["status"] == "paid")
        remaining    = plan["total_amount"] - paid_amount

        plan_status_str = "✅ Yakunlandi" if plan.get("status") == "completed" else f"{paid_count}/{total_count} to'landi"
        lines.append("")
        lines.append(f"📅 <b>MUDDATLI TO'LOV REJASI</b>  ({plan_status_str})")

        for p in payments:
            pnum = p["payment_number"]
            amt  = format_price(p["amount"])
            if p["status"] == "paid":
                paid_on = _fmt_date_short(p.get("paid_at"))
                lines.append(f"  ✅ {pnum}-to'lov: <b>{amt}</b>  ·  {paid_on}")
            else:
                due = p.get("due_date")
                due_str = _fmt_date_short(due)
                urgency = _days_label(due) if due else ""
                if p.get("click_order_id"):
                    lines.append(f"  ⏳ {pnum}-to'lov: <b>{amt}</b>  ·  {due_str}{urgency}  <i>(to'lov kutilmoqda)</i>")
                else:
                    lines.append(f"  ⏳ {pnum}-to'lov: <b>{amt}</b>  ·  {due_str}{urgency}")

        lines.append("  ─────────────────────────────")
        lines.append(f"  Jami narx:  <b>{format_price(plan['total_amount'])}</b>")
        lines.append(f"  To'langan:  <b>{format_price(paid_amount)}</b>")
        if remaining > 0:
            lines.append(f"  Qolgan qarz: <b>{format_price(remaining)}</b>")
        else:
            lines.append("  Qolgan qarz: <b>✅ To'liq to'langan</b>")

    # ─── Qo'shimcha kurs ma'lumotlari ────────────────────────────────────────
    lines.append("")
    if purchase.get("course_video_count"):
        lines.append(f"🎬 Video darslar: <b>{purchase['course_video_count']} ta</b>")
    if purchase.get("course_access_type"):
        lines.append(f"🔓 Kirish turi: <b>{html.quote(purchase['course_access_type'])}</b>")

    # ─── Holat xabari ────────────────────────────────────────────────────────
    if purchase["status"] == "approved":
        lines.append("")
        if real_access_link:
            lines.append(
                "🎉 <b>Kirish huquqi berilgan.</b>\n"
                "Pastdagi tugma orqali guruh yoki kanalga qo'shiling.\n"
                "Kirgach pinned postni o'qing va darslarni tartib bilan o'rganing."
            )
        else:
            lines.append(
                "🎉 <b>Kirish huquqi berilgan.</b>\n"
                "Admin tez orada kurs linkini yuboradi."
            )
    elif purchase["status"] == "pending":
        lines.append("")
        if purchase.get("click_order_id"):
            lines.append("⏳ <b>CLICK to'lov kutilmoqda.</b>\nTo'lov tasdiqlangach kurs linki avtomatik yuboriladi.")
        else:
            lines.append("⏳ <b>To'lov tekshirilmoqda.</b>\nAdmin tasdiqlagach kurs linki avtomatik ko'rinadi.")
    elif purchase["status"] == "rejected":
        note = purchase.get("admin_note") or "Rad etildi."
        lines.append(f"\n❌ <b>To'lov rad etilgan.</b>\nSabab: {html.quote(note)}")

    return "\n".join(lines)


def purchase_detail_keyboard(purchase, page: int, plan=None, payments=None) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    purchase_type = purchase.get("purchase_type", "paid")
    is_free_type = purchase_type == "free"
    access_link = purchase.get("invite_link") or (
        purchase.get("course_free_telegram_link") if is_free_type
        else purchase.get("course_telegram_link")
    )

    if purchase["status"] == "approved" and access_link:
        rows.append([
            InlineKeyboardButton(text="🔗 Kursga qo'shilish", url=access_link)
        ])

    is_installment = purchase.get("is_installment", False)

    if is_installment and plan and payments:
        pending = [p for p in payments if p["status"] == "pending"]
        has_active_click = any(p.get("click_order_id") for p in pending)

        if pending and purchase["status"] == "approved":
            nxt = pending[0]
            nxt_amt = format_price(nxt["amount"])
            nxt_num = nxt["payment_number"]
            total_count = plan["installments_count"]

            if has_active_click:
                next_btn_text = f"⏳ {nxt_num}/{total_count} — to'lov kutilmoqda"
            else:
                next_btn_text = f"💳 {nxt_num}/{total_count}-to'lov: {nxt_amt}"

            rows.append([
                InlineKeyboardButton(
                    text=next_btn_text,
                    callback_data=NextInstallmentCallback(
                        plan_id=plan["id"], purchase_id=purchase["id"]
                    ).pack(),
                )
            ])

            # Muddatidan oldin to'lash — faqat 2+ pending bo'lganda
            if len(pending) >= 2 and not has_active_click:
                total_pending = sum(p["amount"] for p in pending)
                rows.append([
                    InlineKeyboardButton(
                        text=f"⚡ Barcha qarzni to'lash: {format_price(total_pending)}",
                        callback_data=EarlyRepaymentCallback(
                            plan_id=plan["id"], purchase_id=purchase["id"]
                        ).pack(),
                    )
                ])

    if purchase["status"] == "rejected" and not is_installment:
        rows.append([
            InlineKeyboardButton(
                text="🔁 Qayta sotib olish",
                callback_data=MyPurchaseActionCallback(action="retry", purchase_id=purchase["id"], page=page).pack(),
            )
        ])

    rows.append([
        InlineKeyboardButton(
            text="↩️ Orqaga",
            callback_data=MyPurchasesPageCallback(page=page).pack(),
            style=ButtonStyle.PRIMARY,
        ),
        InlineKeyboardButton(
            text="❌ Bekor qilish",
            callback_data=MyPurchaseActionCallback(action="cancel").pack(),
            style=ButtonStyle.DANGER,
        ),
    ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def sync_pending_click_purchases(telegram_id: int) -> None:
    """Pending CLICK xaridlarini Django dan tekshirib avtomatik approve qiladi."""
    pending = await db.get_pending_click_purchases(telegram_id)
    for row in pending:
        order_data = await check_order_status(row["click_order_id"])
        if order_data and order_data.get("paid"):
            invite_link = order_data.get("course_link") or None
            await db.approve_click_purchase(
                click_order_id=row["click_order_id"],
                invite_link=invite_link,
            )


async def render_purchases(message: types.Message, page: int = 1) -> None:
    await sync_pending_click_purchases(message.from_user.id)
    total = await db.count_user_purchases(message.from_user.id)
    total_pages = max(ceil(total / PURCHASES_PER_PAGE), 1)
    page = min(max(page, 1), total_pages)
    offset = (page - 1) * PURCHASES_PER_PAGE
    purchases = await db.select_user_purchases_page(message.from_user.id, PURCHASES_PER_PAGE, offset)

    await message.answer(
        purchases_text(purchases=purchases, page=page, total=total),
        reply_markup=purchases_keyboard(purchases=purchases, page=page, total=total),
    )


async def edit_or_send_purchases(call: types.CallbackQuery, page: int = 1, answer: bool = True) -> None:
    await sync_pending_click_purchases(call.from_user.id)
    total = await db.count_user_purchases(call.from_user.id)
    total_pages = max(ceil(total / PURCHASES_PER_PAGE), 1)
    page = min(max(page, 1), total_pages)
    offset = (page - 1) * PURCHASES_PER_PAGE
    purchases = await db.select_user_purchases_page(call.from_user.id, PURCHASES_PER_PAGE, offset)
    text = purchases_text(purchases=purchases, page=page, total=total)
    markup = purchases_keyboard(purchases=purchases, page=page, total=total)

    if answer:
        await call.answer()
    if call.message.photo:
        await call.message.delete()
        await call.message.answer(text, reply_markup=markup)
        return
    await call.message.edit_text(text, reply_markup=markup)


async def render_purchase_detail(
    call: types.CallbackQuery,
    purchase_id: int,
    page: int,
    answer: bool = True,
) -> None:
    purchase = await db.select_user_purchase(call.from_user.id, purchase_id)
    if not purchase:
        await call.answer("Xarid topilmadi.", show_alert=True)
        await edit_or_send_purchases(call, page=page, answer=False)
        return

    if purchase["status"] == "pending" and purchase.get("click_order_id"):
        order_data = await check_order_status(purchase["click_order_id"])
        if order_data and order_data.get("paid"):
            updated = await db.approve_click_purchase(
                click_order_id=purchase["click_order_id"],
                invite_link=order_data.get("course_link") or None,
            )
            if updated:
                purchase = updated

    plan = None
    payments = None
    if purchase.get("is_installment"):
        plan = await db.get_installment_plan_by_purchase(purchase["id"])
        if plan:
            payments = await db.get_installment_payments(plan["id"])

    if answer:
        await call.answer()
    text = purchase_detail_text(purchase, plan=plan, payments=payments)
    markup = purchase_detail_keyboard(purchase, page=page, plan=plan, payments=payments)
    if call.message.photo:
        await call.message.delete()
        await call.message.answer(text, reply_markup=markup)
        return
    await call.message.edit_text(text, reply_markup=markup)


@router.message(F.text == PURCHASES_BUTTON_TEXT)
async def my_purchases(message: types.Message):
    await render_purchases(message, page=1)


@router.callback_query(MyPurchasesPageCallback.filter())
async def my_purchases_page(call: types.CallbackQuery, callback_data: MyPurchasesPageCallback):
    await edit_or_send_purchases(call, page=callback_data.page)


@router.callback_query(MyPurchaseDetailCallback.filter())
async def my_purchase_detail(call: types.CallbackQuery, callback_data: MyPurchaseDetailCallback):
    await render_purchase_detail(call, purchase_id=callback_data.purchase_id, page=callback_data.page)


@router.callback_query(MyPurchaseActionCallback.filter(F.action == "cancel"))
async def my_purchase_cancel(call: types.CallbackQuery):
    await call.answer("Bekor qilindi.")
    await call.message.delete()


@router.callback_query(MyPurchaseActionCallback.filter(F.action == "catalog"))
async def my_purchase_catalog(call: types.CallbackQuery):
    await call.answer("Kurslar katalogini menyudan oching.")
    await call.message.delete()


@router.callback_query(MyPurchaseActionCallback.filter(F.action == "retry"))
async def my_purchase_retry(call: types.CallbackQuery, callback_data: MyPurchaseActionCallback, state: FSMContext):
    old_purchase = await db.select_user_purchase(call.from_user.id, callback_data.purchase_id)
    if not old_purchase:
        await call.answer("Xarid topilmadi.", show_alert=True)
        return

    course = await db.select_course(old_purchase["course_id"])
    if not course or not course["is_active"]:
        await call.answer("Kurs topilmadi yoki vaqtincha yopilgan.", show_alert=True)
        return

    await state.clear()

    if course["price"] <= 0:
        new_purchase = await db.create_pending_purchase(call.from_user.id, course["id"])
        if not new_purchase:
            await call.answer("Kurs topilmadi.", show_alert=True)
            return
        await call.answer("Kurs sizga biriktirildi.")
        await render_purchase_detail(call, purchase_id=new_purchase["id"], page=callback_data.page, answer=False)
        return

    # Pullik kurs: CLICK to'lov
    await call.answer("To'lov sahifasi tayyorlanmoqda…")
    result = await create_course_payment(
        tg_id=call.from_user.id,
        course_id=course["id"],
        course_name=course["name"],
        course_link="",
        amount=course["price"],
    )
    if not result or not result.get("payment_url"):
        await call.answer("To'lov tizimida xatolik. Qayta urinib ko'ring.", show_alert=True)
        return

    await db.create_click_pending_purchase(
        telegram_id=call.from_user.id,
        course_id=course["id"],
        click_order_id=result["order_id"],
        amount=course["price"],
    )

    payment_url = result["payment_url"]
    text = (
        "💳 <b>CLICK orqali to'lov</b>\n\n"
        f"📚 Kurs: <b>{html.quote(course['name'])}</b>\n"
        f"💰 Summa: <b>{format_price(course['price'])}</b>\n\n"
        "Pastdagi tugmani bosib to'lovni amalga oshiring.\n"
        "To'lov tasdiqlangach, kurs linki <b>avtomatik</b> yuboriladi."
    )
    markup = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="💳 CLICK orqali to'lash", url=payment_url)],
            [
                InlineKeyboardButton(
                    text="❌ Bekor qilish",
                    callback_data=MyPurchaseActionCallback(action="cancel").pack(),
                    style=ButtonStyle.DANGER,
                )
            ],
        ]
    )
    if call.message.photo:
        await call.message.delete()
        await call.message.answer(text, reply_markup=markup)
        return
    await call.message.edit_text(text, reply_markup=markup)


@router.callback_query(EarlyRepaymentCallback.filter())
async def early_repayment_handler(
    call: types.CallbackQuery,
    callback_data: EarlyRepaymentCallback,
):
    """Muddatidan oldin barcha qarzni to'lash — bitta CLICK to'lov."""
    await call.answer("Tayyorlanmoqda…")

    plan_id = callback_data.plan_id
    purchase_id = callback_data.purchase_id

    # Qolgan pending to'lovlar soni va summasi
    pending_info = await db.get_pending_installments_total(plan_id)
    if not pending_info or pending_info["pending_count"] < 1:
        await call.answer("Barcha to'lovlar allaqachon amalga oshirilgan.", show_alert=True)
        return

    pending_total = int(pending_info["pending_total"])
    pending_count = int(pending_info["pending_count"])

    # Plan va purchase ma'lumotlari
    plan = await db.get_installment_plan(plan_id)
    purchase = await db.select_purchase_by_id(purchase_id)
    if not plan or not purchase:
        await call.answer("Ma'lumotlar topilmadi.", show_alert=True)
        return

    course = await db.select_course(purchase["course_id"])
    course_name = course["name"] if course else "Kurs"

    # CLICK orqali umumiy qarz summasiga to'lov yaratish
    result = await create_course_payment(
        tg_id=call.from_user.id,
        course_id=purchase["course_id"],
        course_name=course_name,
        course_link="",
        amount=pending_total,
    )
    if not result or not result.get("payment_url"):
        await call.answer("To'lov tizimida xatolik. Qayta urinib ko'ring.", show_alert=True)
        return

    click_order_id = int(result["order_id"])

    # Barcha pending to'lovlarni ushbu click_order_id ga bog'lash
    bound = await db.bind_early_repayment_click_order(plan_id, click_order_id)
    if not bound:
        await call.answer("Bog'lashda xatolik yuz berdi.", show_alert=True)
        return

    payment_url = result["payment_url"]
    text = (
        "⚡ <b>Muddatidan oldin to'lash</b>\n\n"
        f"📚 Kurs: <b>{html.quote(course_name)}</b>\n"
        f"📊 Qolgan to'lovlar: <b>{pending_count} ta</b>\n"
        f"💰 Umumiy summa: <b>{format_price(pending_total)}</b>\n\n"
        "Pastdagi tugmani bosib to'lovni amalga oshiring.\n"
        "To'lov tasdiqlangach, barcha qarz avtomatik yopiladi."
    )
    markup = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💳 CLICK orqali to'lash", url=payment_url)],
        [InlineKeyboardButton(
            text="↩️ Orqaga",
            callback_data=MyPurchaseDetailCallback(purchase_id=purchase_id, page=1).pack(),
        )],
    ])
    if call.message.photo:
        await call.message.delete()
        await call.message.answer(text, reply_markup=markup)
        return
    await call.message.edit_text(text, reply_markup=markup)
