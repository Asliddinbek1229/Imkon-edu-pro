from dataclasses import dataclass
from typing import List

from aiogram.types import LabeledPrice

from data import config

@dataclass
class Product:
    """
    https://core.telegram.org/bots/api#sendinvoice
    """
    title: str
    description: str
    start_parameter: str
    currency: str
    prices: List[LabeledPrice]
    provider_data: dict = None
    photo_url: str = None
    photo_size: int = None
    photo_width: int = None
    photo_height: int = None
    need_name: bool = False
    need_phone_number: bool = False
    need_email: bool = False
    need_shipping_address: bool = False
    send_phone_number_to_provider: bool = False
    send_email_to_provider: bool = False
    is_flexible: bool = False

    provider_token: str = config.PROVIDER_TOKEN

    def generate_invoice(self):
        return {
            "title": self.title,
            "description": self.description,
            "start_parameter": self.start_parameter,
            "currency": self.currency,
            "prices": self.prices,
            "provider_token": self.provider_token,
            "photo_url": self.photo_url,
            "need_name": self.need_name,
            "need_phone_number": self.need_phone_number,
            "need_email": self.need_email,
            "need_shipping_address": self.need_shipping_address,
            "is_flexible": self.is_flexible,
        }
