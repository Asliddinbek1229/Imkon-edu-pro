import os

from environs import Env
from dotenv import load_dotenv

# environs kutubxonasidan foydalanish
env = Env()
env.read_env()

# .env fayl ichidan quyidagilarni o'qiymiz
BOT_TOKEN = env.str("BOT_TOKEN") # Bot Token
ADMINS = list(map(int, os.getenv("ADMINS", "").split(","))) # adminlar ro'yxati


DB_USER = env.str("DB_USER")
DB_PASS = env.str("DB_PASS")
DB_NAME = env.str("DB_NAME")
DB_HOST = env.str("DB_HOST")


# To'lov sozlamalari
PAYMENT_CARD_NUMBER = env.str("PAYMENT_CARD_NUMBER", default="")
PAYMENT_CARD_OWNER = env.str("PAYMENT_CARD_OWNER", default="")
PAYMENT_BANK_NAME = env.str("PAYMENT_BANK_NAME", default="")
PAYMENT_APPROVAL_CHAT_ID = env.int("PAYMENT_APPROVAL_CHAT_ID", default=0)
PAYMENT_SUPPORT_USERNAME = env.str("PAYMENT_SUPPORT_USERNAME", default="")

