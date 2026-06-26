from aiogram import F, Router, types
from aiogram.client.session.middlewares.request_logging import logger

from loader import bot, db

router = Router()


@router.message(F.reply_to_message)
async def admin_reply_to_user(message: types.Message):
    support_group_id = await db.get_support_group_id()
    if not support_group_id or message.chat.id != support_group_id:
        return

    reply_msg_id = message.reply_to_message.message_id
    user_telegram_id = await db.get_support_user(reply_msg_id)
    if not user_telegram_id:
        return

    try:
        await bot.copy_message(
            chat_id=user_telegram_id,
            from_chat_id=message.chat.id,
            message_id=message.message_id,
        )
    except Exception as error:
        logger.info(f"Support reply yuborilmadi {user_telegram_id}: {error}")
