import os

from environs import Env
from dotenv import load_dotenv

env = Env()
env.read_env()

BOT_TOKEN = env.str("BOT_TOKEN")
ADMINS = list(map(int, os.getenv("ADMINS", "").split(",")))

DB_USER = env.str("DB_USER")
DB_PASS = env.str("DB_PASS")
DB_NAME = env.str("DB_NAME")
DB_HOST = env.str("DB_HOST")

# CLICK to'lov (imkon-edu-web API)
COURSE_PAYMENT_API_BASE = env.str("COURSE_PAYMENT_API_BASE", default="http://localhost:8000/api")
COURSE_INTEGRATION_KEY = env.str("COURSE_INTEGRATION_KEY", default="")

