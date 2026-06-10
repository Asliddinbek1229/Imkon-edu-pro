import logging
from typing import Any

from aiogram import Router
from aiogram.exceptions import (TelegramAPIError,
                                TelegramUnauthorizedError,
                                TelegramBadRequest,
                                TelegramNetworkError,
                                TelegramNotFound,
                                TelegramConflictError,
                                TelegramForbiddenError,
                                RestartingTelegram,
                                CallbackAnswerException,
                                TelegramEntityTooLarge,
                                TelegramRetryAfter,
                                TelegramMigrateToChat,
                                TelegramServerError)
from aiogram.handlers import ErrorHandler


router = Router()


@router.errors()
class MyErrorHandler(ErrorHandler):
    async def handle(self) -> Any:
        exc = self.exception

        if isinstance(exc, TelegramUnauthorizedError):
            logging.info(f'Unauthorized: {exc}')
            return True

        if isinstance(exc, TelegramNetworkError):
            logging.warning(f'NetworkError (transient): {exc}')
            return True

        if isinstance(exc, TelegramNotFound):
            logging.exception(f'NotFound: {exc} \nUpdate: {self.update}')
            return True

        if isinstance(exc, TelegramConflictError):
            logging.exception(f'ConflictError: {exc} \nUpdate: {self.update}')
            return True

        if isinstance(exc, TelegramForbiddenError):
            logging.exception(f'ForbiddenError: {exc} \nUpdate: {self.update}')
            return True

        if isinstance(exc, CallbackAnswerException):
            logging.exception(f'CallbackAnswerException: {exc} \nUpdate: {self.update}')
            return True

        if isinstance(exc, TelegramMigrateToChat):
            logging.exception(f'MigrateToChat: {exc} \nUpdate: {self.update}')
            return True

        if isinstance(exc, TelegramServerError):
            logging.exception(f'ServerError: {exc} \nUpdate: {self.update}')
            return True

        if isinstance(exc, TelegramRetryAfter):
            logging.exception(f'RetryAfter: {exc} \nUpdate: {self.update}')
            return True

        if isinstance(exc, TelegramEntityTooLarge):
            logging.exception(f'EntityTooLarge: {exc} \nUpdate: {self.update}')
            return True

        if isinstance(exc, TelegramBadRequest):
            logging.exception(f'BadRequest: {exc} \nUpdate: {self.update}')
            return True

        if isinstance(exc, RestartingTelegram):
            logging.exception(f'RestartingTelegram: {exc} \nUpdate: {self.update}')
            return True

        if isinstance(exc, TelegramAPIError):
            logging.exception(f'TelegramAPIError: {exc} \nUpdate: {self.update}')
            return True

        logging.exception(f'Unhandled exception\nUpdate: {self.update}\n{exc}')
        return True
