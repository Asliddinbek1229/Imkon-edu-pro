# Imkon-Edu Pro — Telegram Bot

Biologiya kurslari uchun Telegram bot. CLICK Merchant to'lov tizimi orqali kurslarni sotib olish imkonini beradi. To'lov tasdiqlangach foydalanuvchiga kurs linki avtomatik yuboriladi.

## Texnologiyalar

- Python 3.11+
- Aiogram 3.x (async Telegram bot)
- asyncpg + PostgreSQL
- aiohttp (imkon-edu-web API bilan bog'liqlik)
- CLICK Merchant (to'lov tizimi, webhook imkon-edu-web orqali)

## O'rnatish

```bash
git clone <repo-url>
cd imkon-edu-pro

python -m venv venv
venv\Scripts\activate        # Windows
# yoki
source venv/bin/activate     # Linux / macOS

pip install -r requirements.txt
```

## Sozlash

`env_example` faylini `.env` nomi bilan nusxalab, qiymatlarni to'ldiring:

```bash
cp env_example .env
```

`.env` ichidagi o'zgaruvchilar:

| O'zgaruvchi | Tavsif |
|---|---|
| `BOT_TOKEN` | Telegram Bot token (BotFather dan) |
| `ADMINS` | Admin Telegram ID lar, vergul bilan |
| `DB_USER` | PostgreSQL foydalanuvchi nomi |
| `DB_PASS` | PostgreSQL parol |
| `DB_NAME` | Ma'lumotlar bazasi nomi |
| `DB_HOST` | PostgreSQL host (odatda `localhost`) |
| `COURSE_PAYMENT_API_BASE` | imkon-edu-web API manzili, masalan `https://domain.uz/api/v1` |
| `COURSE_INTEGRATION_KEY` | Maxfiy kalit — imkon-edu-web `BOT_PRO_INTEGRATION_KEY` bilan bir xil |

## Ishga tushirish

```bash
python app.py
```

## Production (systemd)

`/etc/systemd/system/imkon-edu-pro.service` fayli:

```ini
[Unit]
Description=Imkon-Edu Pro Telegram Bot
After=network.target postgresql.service

[Service]
Type=simple
User=ubuntu
WorkingDirectory=/home/ubuntu/imkon-edu-pro
ExecStart=/home/ubuntu/imkon-edu-pro/venv/bin/python app.py
Restart=always
RestartSec=5
EnvironmentFile=/home/ubuntu/imkon-edu-pro/.env

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable imkon-edu-pro
sudo systemctl start imkon-edu-pro
sudo systemctl status imkon-edu-pro
```

## To'lov oqimi

1. Foydalanuvchi botda kursni tanlaydi → "Sotib olish" tugmasi
2. Bot imkon-edu-web ga so'rov yuboradi → CLICK to'lov URL hosil bo'ladi
3. Foydalanuvchi CLICK sahifasida to'lov qiladi
4. CLICK → imkon-edu-web webhook → foydalanuvchiga kurs linki Telegram orqali avtomatik yuboriladi

## Loyiha tuzilmasi

```
imkon-edu-pro/
├── app.py                          # Bot kirish nuqtasi
├── loader.py                       # Bot va DB obyektlari
├── data/
│   └── config.py                   # .env o'qish
├── handlers/
│   └── users/
│       ├── core/                   # /start, /help, echo
│       ├── courses/main.py         # Kurslar katalogi + CLICK to'lov
│       ├── payment/main.py         # To'lov callback lari
│       ├── profile/                # Profil boshqaruvi
│       └── purchases/main.py       # Xaridlar tarixi
├── states/                         # FSM holatlari
├── middlewares/                    # Throttling
├── filters/                        # Admin, private chat filterlari
├── utils/
│   ├── db/postgres.py              # PostgreSQL Database klassi
│   ├── misc/api/course_payment.py  # imkon-edu-web API helper
│   └── set_bot_commands.py         # Bot komandalarini sozlash
├── requirements.txt
├── env_example                     # .env namunasi
└── .gitignore
```
