# utils/misc/notify.py
from data.config import ADMINS
from aiogram import Bot
from aiogram.types import PreCheckoutQuery

async def notify_admins(bot: Bot, payload: str, pre_checkout_query: PreCheckoutQuery):
    """
    To'lov muvaffaqiyatli bo'lgandan so'ng adminlarga bildirishnoma yuboradi
    """

    # Order ma'lumotlarini xavfsiz olish
    order_info = pre_checkout_query.order_info
    name = getattr(order_info, "name", "Noma’lum") if order_info else "Noma’lum"
    phone = getattr(order_info, "phone_number", "Noma’lum") if order_info else "Noma’lum"

    # Foydalanuvchi username yoki ID
    username = (
        f"@{pre_checkout_query.from_user.username}"
        if pre_checkout_query.from_user.username
        else pre_checkout_query.from_user.id
    )

    text = (
        f"🛒 Mahsulot sotildi!\n\n"
        f"📦 Mahsulot: {payload}\n"
        f"🆔 To‘lov ID: {pre_checkout_query.id}\n"
        f"👤 Xaridor: {name}\n"
        f"📱 Tel: {phone}\n"
        f"💬 Telegram: {username}"
    )

    # Har bir adminni xabardor qilish
    for admin in ADMINS:
        try:
            await bot.send_message(admin, text)
        except Exception as e:
            print(f"Admin {admin} ga yuborishda xatolik: {e}")