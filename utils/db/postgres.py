from typing import Union

import asyncpg
from asyncpg import Connection
from asyncpg.pool import Pool

from data import config


class Database:
    def __init__(self):
        self.pool: Union[Pool, None] = None

    async def create(self):
        # PostgreSQL ma'lumotlar bazasiga ulanish
        self.pool = await asyncpg.create_pool(
            user=config.DB_USER,
            password=config.DB_PASS,
            host=config.DB_HOST,
            database=config.DB_NAME,
        )

    async def execute(
        self,
        command,
        *args,
        fetch: bool = False,
        fetchval: bool = False,
        fetchrow: bool = False,
        execute: bool = False,
    ):
        # SQL so'rovlarini bajarish uchun umumiy funksiya
        async with self.pool.acquire() as connection:
            connection: Connection
            async with connection.transaction():
                if fetch:
                    result = await connection.fetch(command, *args)
                elif fetchval:
                    result = await connection.fetchval(command, *args)
                elif fetchrow:
                    result = await connection.fetchrow(command, *args)
                elif execute:
                    result = await connection.execute(command, *args)
                else:
                    result = None
            return result

    async def initialize_tables(self):
        # Barcha jadvallarni yaratish
        await self.create_table_users()
        await self.ensure_users_columns()
        await self.create_table_courses()
        await self.ensure_courses_columns()
        await self.create_table_coupons()          # purchases FK uchun avval yaratilishi kerak
        await self.create_table_purchases()
        await self.ensure_purchases_columns()
        await self.create_table_user_access()
        await self.create_table_settings()
        await self.create_table_support_messages()
        await self.create_table_installment_plans()
        await self.create_table_installment_payments()
        await self.create_table_webhook_events()
        await self.ensure_db_indexes()

    async def create_table_users(self):
        # Users jadvali
        sql = """
        CREATE TABLE IF NOT EXISTS users (
            id SERIAL PRIMARY KEY,
            full_name VARCHAR(255) NOT NULL DEFAULT '',
            username VARCHAR(255),
            telegram_id BIGINT NOT NULL UNIQUE,
            first_name VARCHAR(100),
            last_name VARCHAR(100),
            phone VARCHAR(20),
            is_registered BOOLEAN NOT NULL DEFAULT FALSE,
            is_blocked BOOLEAN NOT NULL DEFAULT FALSE,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        """
        await self.execute(sql, execute=True)

    async def ensure_users_columns(self):
        # Old jadval strukturasi uchun safe migratsiya
        alter_queries = [
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS first_name VARCHAR(100)",
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS last_name VARCHAR(100)",
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS phone VARCHAR(20)",
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS is_registered BOOLEAN NOT NULL DEFAULT FALSE",
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS is_blocked BOOLEAN NOT NULL DEFAULT FALSE",
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()",
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()",
            "ALTER TABLE users ALTER COLUMN full_name SET DEFAULT ''",
        ]
        for query in alter_queries:
            await self.execute(query, execute=True)

    async def create_table_settings(self):
        sql = """
        CREATE TABLE IF NOT EXISTS settings (
            key VARCHAR(50) PRIMARY KEY,
            text TEXT,
            photo_file_id VARCHAR(500),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        """
        await self.execute(sql, execute=True)

    async def get_setting(self, key: str):
        sql = "SELECT * FROM settings WHERE key = $1"
        return await self.execute(sql, key, fetchrow=True)

    async def get_support_group_id(self) -> int:
        row = await self.get_setting("support_group_id")
        if row and row["text"]:
            try:
                return int(row["text"].strip())
            except (ValueError, TypeError):
                return 0
        return 0

    async def get_admin_username(self) -> str:
        row = await self.get_setting("admin_username")
        if row and row["text"]:
            return row["text"].strip().lstrip("@")
        return "biolog_mm02"

    async def upsert_setting(self, key: str, text: str | None, photo_file_id: str | None):
        sql = """
        INSERT INTO settings (key, text, photo_file_id, updated_at)
        VALUES ($1, $2, $3, NOW())
        ON CONFLICT (key) DO UPDATE
        SET text = EXCLUDED.text,
            photo_file_id = EXCLUDED.photo_file_id,
            updated_at = NOW()
        RETURNING *;
        """
        return await self.execute(sql, key, text, photo_file_id, fetchrow=True)

    async def create_table_support_messages(self):
        sql = """
        CREATE TABLE IF NOT EXISTS support_messages (
            id SERIAL PRIMARY KEY,
            group_message_id INTEGER NOT NULL UNIQUE,
            user_telegram_id BIGINT NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        """
        await self.execute(sql, execute=True)

    async def save_support_message(self, group_message_id: int, user_telegram_id: int):
        sql = """
        INSERT INTO support_messages (group_message_id, user_telegram_id)
        VALUES ($1, $2)
        ON CONFLICT (group_message_id) DO NOTHING;
        """
        await self.execute(sql, group_message_id, user_telegram_id, execute=True)

    async def get_support_user(self, group_message_id: int) -> int | None:
        sql = "SELECT user_telegram_id FROM support_messages WHERE group_message_id = $1"
        return await self.execute(sql, group_message_id, fetchval=True)

    async def create_table_user_access(self):
        # User Access jadvali (legacy modulga moslik uchun qoldirilgan)
        sql = """
        CREATE TABLE IF NOT EXISTS user_access (
            id SERIAL PRIMARY KEY,
            user_id BIGINT UNIQUE NOT NULL,
            is_active BOOLEAN DEFAULT TRUE
        );
        """
        await self.execute(sql, execute=True)

    async def create_table_courses(self):
        sql = """
        CREATE TABLE IF NOT EXISTS courses (
            id SERIAL PRIMARY KEY,
            name VARCHAR(200) NOT NULL,
            description TEXT NOT NULL DEFAULT '',
            price INTEGER NOT NULL DEFAULT 0,
            video_count INTEGER NOT NULL DEFAULT 0,
            author VARCHAR(200) NOT NULL DEFAULT 'Maqsudxon Mo''minxonov',
            duration VARCHAR(100),
            target_exam VARCHAR(200),
            includes TEXT,
            access_type VARCHAR(100) NOT NULL DEFAULT 'Hayotbod',
            telegram_link VARCHAR(500),
            thumbnail VARCHAR(500),
            is_active BOOLEAN NOT NULL DEFAULT TRUE,
            is_bundle BOOLEAN NOT NULL DEFAULT FALSE,
            bundle_courses JSONB NOT NULL DEFAULT '[]'::jsonb,
            sort_order INTEGER NOT NULL DEFAULT 100,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        """
        await self.execute(sql, execute=True)

    async def ensure_courses_columns(self):
        alter_queries = [
            "ALTER TABLE courses ADD COLUMN IF NOT EXISTS author VARCHAR(200) NOT NULL DEFAULT 'Maqsudxon Mo''minxonov'",
            "ALTER TABLE courses ADD COLUMN IF NOT EXISTS duration VARCHAR(100)",
            "ALTER TABLE courses ADD COLUMN IF NOT EXISTS target_exam VARCHAR(200)",
            "ALTER TABLE courses ADD COLUMN IF NOT EXISTS includes TEXT",
            "ALTER TABLE courses ADD COLUMN IF NOT EXISTS access_type VARCHAR(100) NOT NULL DEFAULT 'Hayotbod'",
            "ALTER TABLE courses ADD COLUMN IF NOT EXISTS telegram_link VARCHAR(500)",
            "ALTER TABLE courses ADD COLUMN IF NOT EXISTS free_telegram_link VARCHAR(500)",
            "ALTER TABLE courses ADD COLUMN IF NOT EXISTS show_free_button BOOLEAN NOT NULL DEFAULT FALSE",
            "ALTER TABLE courses ADD COLUMN IF NOT EXISTS show_paid_button BOOLEAN NOT NULL DEFAULT TRUE",
            "ALTER TABLE courses ADD COLUMN IF NOT EXISTS show_price BOOLEAN NOT NULL DEFAULT TRUE",
            "ALTER TABLE courses ADD COLUMN IF NOT EXISTS thumbnail VARCHAR(500)",
            "ALTER TABLE courses ADD COLUMN IF NOT EXISTS is_active BOOLEAN NOT NULL DEFAULT TRUE",
            "ALTER TABLE courses ADD COLUMN IF NOT EXISTS is_bundle BOOLEAN NOT NULL DEFAULT FALSE",
            "ALTER TABLE courses ADD COLUMN IF NOT EXISTS bundle_courses JSONB NOT NULL DEFAULT '[]'::jsonb",
            "ALTER TABLE courses ADD COLUMN IF NOT EXISTS sort_order INTEGER NOT NULL DEFAULT 100",
            "ALTER TABLE courses ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()",
            "ALTER TABLE courses ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()",
            "ALTER TABLE courses ADD COLUMN IF NOT EXISTS video_file_id VARCHAR(500)",
            "ALTER TABLE courses ADD COLUMN IF NOT EXISTS installment_available BOOLEAN NOT NULL DEFAULT FALSE",
        ]
        for query in alter_queries:
            await self.execute(query, execute=True)

    async def create_table_purchases(self):
        sql = """
        CREATE TABLE IF NOT EXISTS purchases (
            id SERIAL PRIMARY KEY,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            course_id INTEGER NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
            amount INTEGER NOT NULL DEFAULT 0,
            status VARCHAR(20) NOT NULL DEFAULT 'pending',
            receipt_file_id VARCHAR(500),
            card_number_used VARCHAR(30),
            admin_note TEXT,
            approved_by BIGINT,
            invite_link VARCHAR(500),
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            approved_at TIMESTAMPTZ,
            rejected_at TIMESTAMPTZ
        );
        """
        await self.execute(sql, execute=True)

    async def ensure_purchases_columns(self):
        alter_queries = [
            "ALTER TABLE purchases ADD COLUMN IF NOT EXISTS amount INTEGER NOT NULL DEFAULT 0",
            "ALTER TABLE purchases ADD COLUMN IF NOT EXISTS status VARCHAR(20) NOT NULL DEFAULT 'pending'",
            "ALTER TABLE purchases ADD COLUMN IF NOT EXISTS purchase_type VARCHAR(10) NOT NULL DEFAULT 'paid'",
            "ALTER TABLE purchases ADD COLUMN IF NOT EXISTS receipt_file_id VARCHAR(500)",
            "ALTER TABLE purchases ADD COLUMN IF NOT EXISTS card_number_used VARCHAR(30)",
            "ALTER TABLE purchases ADD COLUMN IF NOT EXISTS admin_note TEXT",
            "ALTER TABLE purchases ADD COLUMN IF NOT EXISTS approved_by BIGINT",
            "ALTER TABLE purchases ADD COLUMN IF NOT EXISTS invite_link VARCHAR(500)",
            "ALTER TABLE purchases ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()",
            "ALTER TABLE purchases ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()",
            "ALTER TABLE purchases ADD COLUMN IF NOT EXISTS approved_at TIMESTAMPTZ",
            "ALTER TABLE purchases ADD COLUMN IF NOT EXISTS rejected_at TIMESTAMPTZ",
            "ALTER TABLE purchases ADD COLUMN IF NOT EXISTS click_order_id INTEGER",
            "ALTER TABLE purchases ADD COLUMN IF NOT EXISTS coupon_id INTEGER REFERENCES coupons(id) ON DELETE SET NULL",
            "ALTER TABLE purchases ADD COLUMN IF NOT EXISTS original_amount INTEGER",
            "ALTER TABLE purchases ADD COLUMN IF NOT EXISTS coupon_discount INTEGER NOT NULL DEFAULT 0",
            "ALTER TABLE purchases ADD COLUMN IF NOT EXISTS is_installment BOOLEAN NOT NULL DEFAULT FALSE",
        ]
        for query in alter_queries:
            await self.execute(query, execute=True)

    @staticmethod
    def format_args(sql, parameters: dict):
        # So'rovga kiritiladigan argumentlarni formatlash
        sql += " AND ".join(
            [f"{item} = ${num}" for num, item in enumerate(parameters.keys(), start=1)]
        )
        return sql, tuple(parameters.values())

    # CRUD funksiyalari
    async def add_user(self, full_name, username, telegram_id):
        # Foydalanuvchini qo'shish yoki mavjudini yangilash
        sql = """
        INSERT INTO users (full_name, username, telegram_id, updated_at)
        VALUES ($1, $2, $3, NOW())
        ON CONFLICT (telegram_id) DO UPDATE
        SET full_name = EXCLUDED.full_name,
            username = EXCLUDED.username,
            updated_at = NOW()
        RETURNING *;
        """
        return await self.execute(sql, full_name, username, telegram_id, fetchrow=True)

    async def update_user_registration(self, telegram_id: int, first_name: str, last_name: str, phone: str):
        full_name = f"{first_name} {last_name}".strip()
        sql = """
        UPDATE users
        SET first_name = $1,
            last_name = $2,
            phone = $3,
            full_name = $4,
            is_registered = TRUE,
            updated_at = NOW()
        WHERE telegram_id = $5
        RETURNING *;
        """
        return await self.execute(sql, first_name, last_name, phone, full_name, telegram_id, fetchrow=True)

    async def update_user_profile_field(self, telegram_id: int, field_name: str, value: str):
        allowed_fields = {"first_name", "last_name", "phone"}
        if field_name not in allowed_fields:
            raise ValueError("Noto'g'ri user field")

        user = await self.select_user(telegram_id=telegram_id)
        if not user:
            return None

        first_name = user["first_name"] or ""
        last_name = user["last_name"] or ""
        phone = user["phone"] or ""

        if field_name == "first_name":
            first_name = value
        elif field_name == "last_name":
            last_name = value
        elif field_name == "phone":
            phone = value

        return await self.update_user_registration(
            telegram_id=telegram_id,
            first_name=first_name,
            last_name=last_name,
            phone=phone,
        )

    async def select_all_users(self):
        # Barcha foydalanuvchilarni olish
        sql = "SELECT * FROM users ORDER BY id ASC"
        return await self.execute(sql, fetch=True)

    async def select_user(self, **kwargs):
        # Foydalanuvchi ma'lumotlarini olish
        sql = "SELECT * FROM users WHERE "
        sql, parameters = self.format_args(sql, parameters=kwargs)
        return await self.execute(sql, *parameters, fetchrow=True)

    async def count_users(self):
        # Foydalanuvchilar sonini hisoblash
        sql = "SELECT COUNT(*) FROM users"
        return await self.execute(sql, fetchval=True)

    async def count_registered_users(self):
        sql = "SELECT COUNT(*) FROM users WHERE is_registered = TRUE"
        return await self.execute(sql, fetchval=True)

    async def count_blocked_users(self):
        sql = "SELECT COUNT(*) FROM users WHERE is_blocked = TRUE"
        return await self.execute(sql, fetchval=True)

    async def update_user_username(self, username, telegram_id):
        # Foydalanuvchi username'ini yangilash
        sql = """
        UPDATE users
        SET username = $1,
            updated_at = NOW()
        WHERE telegram_id = $2
        """
        return await self.execute(sql, username, telegram_id, execute=True)

    async def count_active_courses(self):
        sql = "SELECT COUNT(*) FROM courses WHERE is_active = TRUE"
        return await self.execute(sql, fetchval=True)

    async def count_courses(self):
        sql = "SELECT COUNT(*) FROM courses"
        return await self.execute(sql, fetchval=True)

    async def count_purchases(self, status: str | None = None):
        if status is None:
            sql = "SELECT COUNT(*) FROM purchases"
            return await self.execute(sql, fetchval=True)
        sql = "SELECT COUNT(*) FROM purchases WHERE status = $1"
        return await self.execute(sql, status, fetchval=True)

    async def sum_purchases_amount(self, status: str | None = None):
        if status is None:
            sql = "SELECT COALESCE(SUM(amount), 0) FROM purchases"
            return await self.execute(sql, fetchval=True)
        sql = "SELECT COALESCE(SUM(amount), 0) FROM purchases WHERE status = $1"
        return await self.execute(sql, status, fetchval=True)

    async def select_latest_purchases(self, limit: int = 5):
        sql = """
        SELECT
            p.id,
            p.amount,
            p.status,
            p.created_at,
            c.name AS course_name,
            u.full_name,
            u.telegram_id
        FROM purchases p
        JOIN courses c ON c.id = p.course_id
        JOIN users u ON u.id = p.user_id
        ORDER BY p.created_at DESC, p.id DESC
        LIMIT $1;
        """
        return await self.execute(sql, limit, fetch=True)

    async def select_top_courses_by_purchases(self, limit: int = 5):
        sql = """
        SELECT
            c.id,
            c.name,
            COUNT(p.id) AS purchase_count,
            COUNT(p.id) FILTER (WHERE p.status = 'approved') AS approved_count,
            COALESCE(SUM(p.amount) FILTER (WHERE p.status = 'approved'), 0) AS revenue
        FROM courses c
        LEFT JOIN purchases p ON p.course_id = c.id
        GROUP BY c.id, c.name
        ORDER BY purchase_count DESC, approved_count DESC, c.id ASC
        LIMIT $1;
        """
        return await self.execute(sql, limit, fetch=True)

    async def select_active_courses_page(self, limit: int, offset: int):
        sql = """
        SELECT *
        FROM courses
        WHERE is_active = TRUE
        ORDER BY sort_order ASC, id ASC
        LIMIT $1 OFFSET $2
        """
        return await self.execute(sql, limit, offset, fetch=True)

    async def select_courses_page(self, limit: int, offset: int):
        sql = """
        SELECT *
        FROM courses
        ORDER BY sort_order ASC, id ASC
        LIMIT $1 OFFSET $2
        """
        return await self.execute(sql, limit, offset, fetch=True)

    async def select_all_courses(self):
        sql = "SELECT * FROM courses ORDER BY sort_order ASC, id ASC"
        return await self.execute(sql, fetch=True)

    async def select_course(self, course_id: int):
        sql = "SELECT * FROM courses WHERE id = $1"
        return await self.execute(sql, course_id, fetchrow=True)

    async def add_course(
        self,
        name: str,
        description: str,
        price: int,
        video_count: int,
        thumbnail: str | None = None,
        video_file_id: str | None = None,
        telegram_link: str | None = None,
        free_telegram_link: str | None = None,
        show_free_button: bool = False,
        show_paid_button: bool = True,
        author: str = "Maqsudxon Mo'minxonov",
        duration: str | None = None,
        target_exam: str | None = "DTM, Milliy Sertifikat, Attestatsiya",
        includes: str | None = None,
        access_type: str = "Hayotbod",
        sort_order: int = 100,
        is_active: bool = True,
    ):
        sql = """
        INSERT INTO courses (
            name, description, price, video_count, thumbnail, video_file_id, telegram_link,
            free_telegram_link, show_free_button, show_paid_button,
            author, duration, target_exam, includes, access_type, sort_order, is_active, updated_at
        )
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15, $16, $17, NOW())
        RETURNING *;
        """
        return await self.execute(
            sql,
            name,
            description,
            price,
            video_count,
            thumbnail,
            video_file_id,
            telegram_link,
            free_telegram_link,
            show_free_button,
            show_paid_button,
            author,
            duration,
            target_exam,
            includes,
            access_type,
            sort_order,
            is_active,
            fetchrow=True,
        )

    async def update_course_field(self, course_id: int, field_name: str, value):
        allowed_fields = {
            "name",
            "description",
            "price",
            "video_count",
            "thumbnail",
            "video_file_id",
            "telegram_link",
            "free_telegram_link",
            "show_free_button",
            "show_paid_button",
            "show_price",
            "author",
            "duration",
            "target_exam",
            "includes",
            "access_type",
            "sort_order",
        }
        if field_name not in allowed_fields:
            raise ValueError("Noto'g'ri course field")
        sql = f"""
        UPDATE courses
        SET {field_name} = $1,
            updated_at = NOW()
        WHERE id = $2
        RETURNING *;
        """
        return await self.execute(sql, value, course_id, fetchrow=True)

    async def set_course_active(self, course_id: int, is_active: bool):
        sql = """
        UPDATE courses
        SET is_active = $1,
            updated_at = NOW()
        WHERE id = $2
        RETURNING *;
        """
        return await self.execute(sql, is_active, course_id, fetchrow=True)

    async def delete_course(self, course_id: int):
        sql = "DELETE FROM courses WHERE id = $1"
        return await self.execute(sql, course_id, execute=True)

    async def create_pending_purchase(self, telegram_id: int, course_id: int):
        user = await self.select_user(telegram_id=telegram_id)
        course = await self.select_course(course_id)
        if not user or not course:
            return None

        existing = await self.select_active_purchase_for_course(user["id"], course_id)
        if existing:
            return existing

        status = "approved" if course["price"] <= 0 else "pending"
        approved_at_sql = "NOW()" if status == "approved" else "NULL"
        invite_link = course["telegram_link"] if status == "approved" else None
        sql = f"""
        INSERT INTO purchases (
            user_id, course_id, amount, status, purchase_type, invite_link, approved_at, updated_at
        )
        VALUES ($1, $2, $3, $4, 'paid', $5, {approved_at_sql}, NOW())
        RETURNING id;
        """
        purchase_id = await self.execute(
            sql,
            user["id"],
            course["id"],
            course["price"],
            status,
            invite_link,
            fetchval=True,
        )
        return await self.select_purchase_by_id(purchase_id)

    async def create_click_pending_purchase(
        self, telegram_id: int, course_id: int, click_order_id: int, amount: int
    ):
        user = await self.select_user(telegram_id=telegram_id)
        if not user:
            return None
        # Avvalgi pending click xaridini bekor qil
        await self.execute(
            "UPDATE purchases SET status='rejected', rejected_at=NOW(), updated_at=NOW() "
            "WHERE user_id=$1 AND course_id=$2 AND status='pending' AND click_order_id IS NOT NULL",
            user["id"], course_id, execute=True,
        )
        sql = """
        INSERT INTO purchases (user_id, course_id, amount, status, purchase_type, click_order_id, updated_at)
        VALUES ($1, $2, $3, 'pending', 'paid', $4, NOW())
        RETURNING id;
        """
        purchase_id = await self.execute(
            sql, user["id"], course_id, amount, click_order_id, fetchval=True
        )
        if not purchase_id:
            return None
        return await self.select_purchase_by_id(purchase_id)

    async def approve_click_purchase(self, click_order_id: int, invite_link: str | None):
        """To'lov tasdiqlash + kupon hisobini oshirish — bitta atomik tranzaksiyada."""
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                purchase_id = await conn.fetchval(
                    """
                    UPDATE purchases
                    SET status = 'approved',
                        invite_link = COALESCE(
                            $2,
                            (SELECT telegram_link FROM courses WHERE courses.id = purchases.course_id)
                        ),
                        approved_at = NOW(),
                        updated_at = NOW()
                    WHERE click_order_id = $1 AND status = 'pending'
                    RETURNING id;
                    """,
                    click_order_id, invite_link or None,
                )
                if not purchase_id:
                    return None
                # Kupon hisobini faqat to'lov tasdiqlanganda oshirish
                coupon_id = await conn.fetchval(
                    "SELECT coupon_id FROM purchases WHERE id = $1",
                    purchase_id,
                )
                if coupon_id:
                    await conn.execute(
                        "UPDATE coupons SET uses_count = uses_count + 1 WHERE id = $1",
                        coupon_id,
                    )
        return await self.select_purchase_by_id(purchase_id)

    async def get_pending_click_purchases(self, telegram_id: int) -> list:
        sql = """
        SELECT p.id, p.click_order_id
        FROM purchases p
        JOIN users u ON u.id = p.user_id
        WHERE u.telegram_id = $1
          AND p.status = 'pending'
          AND p.click_order_id IS NOT NULL
        ORDER BY p.id DESC;
        """
        return await self.execute(sql, telegram_id, fetch=True)

    async def select_active_purchase_for_course(
        self, user_id: int, course_id: int, purchase_type: str | None = None
    ):
        if purchase_type is not None:
            sql = """
            SELECT
                p.*,
                c.name AS course_name,
                c.description AS course_description,
                c.telegram_link AS course_telegram_link,
                c.free_telegram_link AS course_free_telegram_link,
                c.thumbnail AS course_thumbnail,
                c.video_count AS course_video_count,
                c.access_type AS course_access_type
            FROM purchases p
            JOIN courses c ON c.id = p.course_id
            WHERE p.user_id = $1
              AND p.course_id = $2
              AND p.purchase_type = $3
              AND p.status IN ('pending', 'approved')
            ORDER BY p.id DESC
            LIMIT 1;
            """
            return await self.execute(sql, user_id, course_id, purchase_type, fetchrow=True)

        sql = """
        SELECT
            p.*,
            c.name AS course_name,
            c.description AS course_description,
            c.telegram_link AS course_telegram_link,
            c.free_telegram_link AS course_free_telegram_link,
            c.thumbnail AS course_thumbnail,
            c.video_count AS course_video_count,
            c.access_type AS course_access_type
        FROM purchases p
        JOIN courses c ON c.id = p.course_id
        WHERE p.user_id = $1
          AND p.course_id = $2
          AND p.status IN ('pending', 'approved')
        ORDER BY p.id DESC
        LIMIT 1;
        """
        return await self.execute(sql, user_id, course_id, fetchrow=True)

    async def create_free_purchase(self, telegram_id: int, course_id: int):
        user = await self.select_user(telegram_id=telegram_id)
        course = await self.select_course(course_id)
        if not user or not course:
            return None

        existing = await self.select_active_purchase_for_course(
            user["id"], course_id, purchase_type="free"
        )
        if existing:
            return existing

        invite_link = course["free_telegram_link"]
        sql = """
        INSERT INTO purchases (
            user_id, course_id, amount, status, purchase_type, invite_link, approved_at, updated_at
        )
        VALUES ($1, $2, 0, 'approved', 'free', $3, NOW(), NOW())
        RETURNING id;
        """
        purchase_id = await self.execute(
            sql, user["id"], course["id"], invite_link, fetchval=True
        )
        return await self.select_purchase_by_id(purchase_id)

    async def select_purchase_by_id(self, purchase_id: int):
        sql = """
        SELECT
            p.*,
            c.name AS course_name,
            c.description AS course_description,
            c.telegram_link AS course_telegram_link,
            c.free_telegram_link AS course_free_telegram_link,
            c.thumbnail AS course_thumbnail,
            c.video_count AS course_video_count,
            c.access_type AS course_access_type,
            u.telegram_id,
            u.username,
            u.full_name,
            u.first_name,
            u.phone,
            coup.code AS coupon_code,
            coup.name AS coupon_name
        FROM purchases p
        JOIN courses c ON c.id = p.course_id
        JOIN users u ON u.id = p.user_id
        LEFT JOIN coupons coup ON coup.id = p.coupon_id
        WHERE p.id = $1;
        """
        return await self.execute(sql, purchase_id, fetchrow=True)

    async def approve_purchase(self, purchase_id: int, approved_by: int, invite_link: str, admin_note: str | None = None):
        sql = """
        UPDATE purchases
        SET status = 'approved',
            approved_by = $2,
            invite_link = $3,
            admin_note = $4,
            approved_at = NOW(),
            rejected_at = NULL,
            updated_at = NOW()
        WHERE id = $1
        RETURNING id;
        """
        updated_id = await self.execute(sql, purchase_id, approved_by, invite_link, admin_note, fetchval=True)
        if not updated_id:
            return None
        return await self.select_purchase_by_id(updated_id)

    async def reject_purchase(self, purchase_id: int, rejected_by: int, admin_note: str):
        sql = """
        UPDATE purchases
        SET status = 'rejected',
            approved_by = $2,
            invite_link = NULL,
            admin_note = $3,
            approved_at = NULL,
            rejected_at = NOW(),
            updated_at = NOW()
        WHERE id = $1
        RETURNING id;
        """
        updated_id = await self.execute(sql, purchase_id, rejected_by, admin_note, fetchval=True)
        if not updated_id:
            return None
        return await self.select_purchase_by_id(updated_id)

    async def count_user_purchases(self, telegram_id: int):
        sql = """
        SELECT COUNT(*)
        FROM purchases p
        JOIN users u ON u.id = p.user_id
        WHERE u.telegram_id = $1 AND p.status = 'approved';
        """
        return await self.execute(sql, telegram_id, fetchval=True)

    async def count_user_purchases_by_status(self, telegram_id: int, status: str):
        sql = """
        SELECT COUNT(*)
        FROM purchases p
        JOIN users u ON u.id = p.user_id
        WHERE u.telegram_id = $1 AND p.status = $2;
        """
        return await self.execute(sql, telegram_id, status, fetchval=True)

    async def select_user_purchases_page(self, telegram_id: int, limit: int, offset: int):
        sql = """
        SELECT
            p.*,
            c.name AS course_name,
            c.telegram_link AS course_telegram_link,
            c.free_telegram_link AS course_free_telegram_link,
            c.thumbnail AS course_thumbnail,
            c.video_count AS course_video_count,
            c.access_type AS course_access_type,
            coup.code AS coupon_code,
            coup.discount_percent AS coupon_percent,
            ipl.id AS plan_id,
            ipl.installments_count AS plan_total_count,
            ipl.paid_count AS plan_paid_count,
            ipl.status AS plan_status,
            (
                SELECT MIN(ip2.due_date)
                FROM installment_payments ip2
                WHERE ip2.plan_id = ipl.id AND ip2.status = 'pending' AND ip2.due_date IS NOT NULL
            ) AS next_due_date
        FROM purchases p
        JOIN users u ON u.id = p.user_id
        JOIN courses c ON c.id = p.course_id
        LEFT JOIN coupons coup ON coup.id = p.coupon_id
        LEFT JOIN installment_plans ipl ON ipl.purchase_id = p.id
        WHERE u.telegram_id = $1 AND p.status = 'approved'
        ORDER BY p.created_at DESC, p.id DESC
        LIMIT $2 OFFSET $3;
        """
        return await self.execute(sql, telegram_id, limit, offset, fetch=True)

    async def get_pending_course_purchase(self, telegram_id: int, course_id: int) -> dict | None:
        sql = """
        SELECT p.*
        FROM purchases p
        JOIN users u ON u.id = p.user_id
        WHERE u.telegram_id = $1 AND p.course_id = $2
          AND p.status = 'pending' AND p.purchase_type = 'paid'
        ORDER BY p.id DESC
        LIMIT 1;
        """
        return await self.execute(sql, telegram_id, course_id, fetchrow=True)

    async def cancel_pending_purchases_for_course(self, telegram_id: int, course_id: int) -> None:
        user = await self.select_user(telegram_id=telegram_id)
        if not user:
            return
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                # Bo'lib to'lash click_order_id larini tozalash —
                # webhook eski buyurtmani tasdiqlashini oldini olish uchun
                await conn.execute(
                    """
                    UPDATE installment_payments
                    SET click_order_id = NULL
                    WHERE plan_id IN (
                        SELECT ipl.id
                        FROM installment_plans ipl
                        JOIN purchases p ON p.id = ipl.purchase_id
                        WHERE p.user_id = $1
                          AND p.course_id = $2
                          AND p.status = 'pending'
                    );
                    """,
                    user["id"], course_id,
                )
                await conn.execute(
                    "UPDATE purchases SET status='rejected', rejected_at=NOW(), updated_at=NOW() "
                    "WHERE user_id=$1 AND course_id=$2 AND status='pending' AND purchase_type='paid';",
                    user["id"], course_id,
                )

    async def select_user_purchase(self, telegram_id: int, purchase_id: int):
        sql = """
        SELECT
            p.*,
            c.name AS course_name,
            c.description AS course_description,
            c.telegram_link AS course_telegram_link,
            c.free_telegram_link AS course_free_telegram_link,
            c.thumbnail AS course_thumbnail,
            c.video_count AS course_video_count,
            c.access_type AS course_access_type,
            u.telegram_id,
            u.username,
            u.full_name,
            u.first_name,
            u.phone,
            coup.code AS coupon_code,
            coup.name AS coupon_name
        FROM purchases p
        JOIN users u ON u.id = p.user_id
        JOIN courses c ON c.id = p.course_id
        LEFT JOIN coupons coup ON coup.id = p.coupon_id
        WHERE u.telegram_id = $1 AND p.id = $2;
        """
        return await self.execute(sql, telegram_id, purchase_id, fetchrow=True)

    async def select_users_with_any_approved_purchase(self):
        sql = """
        SELECT DISTINCT u.*
        FROM users u
        JOIN purchases p ON p.user_id = u.id
        WHERE p.status = 'approved'
        ORDER BY u.id ASC
        """
        return await self.execute(sql, fetch=True)

    async def select_users_by_course_approved(self, course_id: int):
        sql = """
        SELECT DISTINCT u.*
        FROM users u
        JOIN purchases p ON p.user_id = u.id
        WHERE p.course_id = $1 AND p.status = 'approved'
        ORDER BY u.id ASC
        """
        return await self.execute(sql, course_id, fetch=True)

    async def select_course_purchase_export(self, course_id: int):
        sql = """
        SELECT DISTINCT ON (u.id)
            u.full_name, u.first_name, u.last_name, u.username, u.telegram_id, u.phone,
            c.name AS course_name,
            p.id AS purchase_id,
            p.amount,
            p.purchase_type,
            p.status,
            p.approved_at AS purchase_date,
            p.created_at AS order_date,
            p.card_number_used,
            p.admin_note,
            p.invite_link,
            p.click_order_id,
            CASE WHEN p.receipt_file_id IS NOT NULL THEN 'Ha' ELSE 'Yo''q' END AS has_receipt
        FROM users u
        JOIN purchases p ON p.user_id = u.id
        JOIN courses c ON c.id = p.course_id
        WHERE p.course_id = $1 AND p.status = 'approved'
        ORDER BY u.id, p.approved_at DESC
        """
        return await self.execute(sql, course_id, fetch=True)

    async def select_all_buyers_export(self):
        sql = """
        SELECT
            u.full_name, u.first_name, u.last_name, u.username, u.telegram_id, u.phone,
            c.name AS course_name,
            p.id AS purchase_id,
            p.amount,
            p.purchase_type,
            p.status,
            p.approved_at AS purchase_date,
            p.created_at AS order_date,
            p.card_number_used,
            p.admin_note,
            p.invite_link,
            p.click_order_id,
            CASE WHEN p.receipt_file_id IS NOT NULL THEN 'Ha' ELSE 'Yo''q' END AS has_receipt
        FROM purchases p
        JOIN users u ON u.id = p.user_id
        JOIN courses c ON c.id = p.course_id
        WHERE p.status = 'approved'
        ORDER BY u.id ASC, p.approved_at DESC
        """
        return await self.execute(sql, fetch=True)

    # ── COUPONS ──────────────────────────────────────────────────────────────────

    async def create_table_coupons(self):
        sql = """
        CREATE TABLE IF NOT EXISTS coupons (
            id SERIAL PRIMARY KEY,
            code VARCHAR(50) UNIQUE NOT NULL,
            name VARCHAR(200) NOT NULL DEFAULT '',
            discount_percent INTEGER NOT NULL DEFAULT 0,
            discount_amount INTEGER NOT NULL DEFAULT 0,
            max_uses INTEGER,
            uses_count INTEGER NOT NULL DEFAULT 0,
            course_id INTEGER REFERENCES courses(id) ON DELETE SET NULL,
            is_active BOOLEAN NOT NULL DEFAULT TRUE,
            expires_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        """
        await self.execute(sql, execute=True)

    async def add_coupon(
        self,
        code: str,
        name: str,
        discount_percent: int,
        discount_amount: int,
        max_uses: int | None,
        course_id: int | None,
        expires_at=None,
    ) -> dict | None:
        sql = """
        INSERT INTO coupons (code, name, discount_percent, discount_amount, max_uses, course_id, expires_at)
        VALUES ($1, $2, $3, $4, $5, $6, $7)
        RETURNING *;
        """
        return await self.execute(
            sql, code.upper(), name, discount_percent, discount_amount,
            max_uses, course_id, expires_at, fetchrow=True,
        )

    async def get_coupon_by_code(self, code: str) -> dict | None:
        sql = "SELECT * FROM coupons WHERE UPPER(code) = UPPER($1);"
        return await self.execute(sql, code, fetchrow=True)

    async def has_user_used_coupon(self, coupon_id: int, telegram_id: int) -> bool:
        sql = """
        SELECT COUNT(*) FROM purchases p
        JOIN users u ON u.id = p.user_id
        WHERE p.coupon_id = $1 AND u.telegram_id = $2 AND p.status != 'rejected';
        """
        count = await self.execute(sql, coupon_id, telegram_id, fetchval=True)
        return (count or 0) > 0

    async def increment_coupon_uses(self, coupon_id: int) -> None:
        await self.execute(
            "UPDATE coupons SET uses_count = uses_count + 1 WHERE id = $1",
            coupon_id, execute=True,
        )

    async def list_coupons(self, is_active: bool | None = None) -> list:
        if is_active is None:
            sql = "SELECT * FROM coupons ORDER BY created_at DESC;"
            return await self.execute(sql, fetch=True)
        sql = "SELECT * FROM coupons WHERE is_active = $1 ORDER BY created_at DESC;"
        return await self.execute(sql, is_active, fetch=True)

    async def get_coupon(self, coupon_id: int) -> dict | None:
        return await self.execute("SELECT * FROM coupons WHERE id = $1;", coupon_id, fetchrow=True)

    async def toggle_coupon_active(self, coupon_id: int) -> dict | None:
        sql = "UPDATE coupons SET is_active = NOT is_active WHERE id = $1 RETURNING *;"
        return await self.execute(sql, coupon_id, fetchrow=True)

    async def update_coupon(
        self,
        coupon_id: int,
        code: str,
        name: str,
        discount_percent: int,
        discount_amount: int,
        max_uses: int | None,
        course_id: int | None,
        expires_at=None,
    ) -> dict | None:
        sql = """
        UPDATE coupons
        SET code=$2, name=$3, discount_percent=$4, discount_amount=$5,
            max_uses=$6, course_id=$7, expires_at=$8
        WHERE id=$1
        RETURNING *;
        """
        return await self.execute(
            sql, coupon_id, code.upper(), name, discount_percent,
            discount_amount, max_uses, course_id, expires_at, fetchrow=True,
        )

    async def delete_coupon(self, coupon_id: int) -> None:
        await self.execute("DELETE FROM coupons WHERE id = $1;", coupon_id, execute=True)

    async def create_custom_purchase(
        self,
        telegram_id: int,
        course_id: int,
        amount: int,
        coupon_id: int | None = None,
        original_amount: int | None = None,
        coupon_discount: int = 0,
        is_installment: bool = False,
        click_order_id: int | None = None,
    ) -> dict | None:
        user = await self.select_user(telegram_id=telegram_id)
        if not user:
            return None
        sql = """
        INSERT INTO purchases (
            user_id, course_id, amount, status, purchase_type,
            coupon_id, original_amount, coupon_discount, is_installment, click_order_id, updated_at
        )
        VALUES ($1, $2, $3, 'pending', 'paid', $4, $5, $6, $7, $8, NOW())
        RETURNING id;
        """
        purchase_id = await self.execute(
            sql, user["id"], course_id, amount,
            coupon_id, original_amount or amount, coupon_discount, is_installment, click_order_id,
            fetchval=True,
        )
        if not purchase_id:
            return None
        return await self.select_purchase_by_id(purchase_id)

    # ── INSTALLMENT PLANS ─────────────────────────────────────────────────────

    async def create_table_installment_plans(self):
        sql = """
        CREATE TABLE IF NOT EXISTS installment_plans (
            id SERIAL PRIMARY KEY,
            purchase_id INTEGER UNIQUE NOT NULL REFERENCES purchases(id) ON DELETE CASCADE,
            total_amount INTEGER NOT NULL,
            installments_count INTEGER NOT NULL,
            paid_count INTEGER NOT NULL DEFAULT 0,
            status VARCHAR(20) NOT NULL DEFAULT 'active',
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        """
        await self.execute(sql, execute=True)

    async def create_table_installment_payments(self):
        sql = """
        CREATE TABLE IF NOT EXISTS installment_payments (
            id SERIAL PRIMARY KEY,
            plan_id INTEGER NOT NULL REFERENCES installment_plans(id) ON DELETE CASCADE,
            payment_number INTEGER NOT NULL,
            amount INTEGER NOT NULL,
            status VARCHAR(20) NOT NULL DEFAULT 'pending',
            due_date DATE,
            paid_at TIMESTAMPTZ,
            click_order_id INTEGER,
            approved_by BIGINT,
            admin_note TEXT,
            last_notified_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        """
        await self.execute(sql, execute=True)
        await self.execute(
            "ALTER TABLE installment_payments ADD COLUMN IF NOT EXISTS click_order_id INTEGER;",
            execute=True,
        )

    async def create_installment_plan(
        self, purchase_id: int, total_amount: int, installments_count: int
    ) -> dict | None:
        from datetime import date, timedelta

        plan_sql = """
        INSERT INTO installment_plans (purchase_id, total_amount, installments_count)
        VALUES ($1, $2, $3)
        RETURNING id;
        """
        plan_id = await self.execute(
            plan_sql, purchase_id, total_amount, installments_count, fetchval=True
        )
        if not plan_id:
            return None

        per = total_amount // installments_count
        remainder = total_amount - per * (installments_count - 1)

        for i in range(1, installments_count + 1):
            amt = remainder if i == installments_count else per
            due = None if i == 1 else date.today() + timedelta(days=30 * (i - 1))
            await self.execute(
                """
                INSERT INTO installment_payments (plan_id, payment_number, amount, due_date)
                VALUES ($1, $2, $3, $4);
                """,
                plan_id, i, amt, due, execute=True,
            )

        return await self.execute(
            "SELECT * FROM installment_plans WHERE id = $1;", plan_id, fetchrow=True
        )

    async def get_installment_plan_by_purchase(self, purchase_id: int) -> dict | None:
        return await self.execute(
            "SELECT * FROM installment_plans WHERE purchase_id = $1;", purchase_id, fetchrow=True
        )

    async def get_installment_payments(self, plan_id: int) -> list:
        return await self.execute(
            "SELECT * FROM installment_payments WHERE plan_id = $1 ORDER BY payment_number;",
            plan_id, fetch=True,
        )

    async def get_next_pending_installment(self, plan_id: int) -> dict | None:
        return await self.execute(
            """
            SELECT * FROM installment_payments
            WHERE plan_id = $1 AND status = 'pending'
            ORDER BY payment_number
            LIMIT 1;
            """,
            plan_id, fetchrow=True,
        )

    async def get_pending_installments_total(self, plan_id: int) -> dict | None:
        """Qolgan barcha pending to'lovlar soni va umumiy summasi."""
        return await self.execute(
            """
            SELECT COUNT(*) AS pending_count, COALESCE(SUM(amount), 0) AS pending_total
            FROM installment_payments
            WHERE plan_id = $1 AND status = 'pending';
            """,
            plan_id, fetchrow=True,
        )

    async def bind_early_repayment_click_order(
        self, plan_id: int, click_order_id: int
    ) -> int:
        """Barcha pending to'lovlarni bitta click_order_id ga bog'lash.
        Qaytaradi: bog'langan to'lovlar soni."""
        result = await self.execute(
            """
            UPDATE installment_payments
            SET click_order_id = $2
            WHERE plan_id = $1 AND status = 'pending'
            RETURNING id;
            """,
            plan_id, click_order_id, fetch=True,
        )
        return len(result) if result else 0

    async def approve_early_repayment(
        self, click_order_id: int, invite_link: str | None
    ) -> dict | None:
        """Muddatidan oldin to'lash: bitta CLICK orqali barcha pending to'lovlarni yopish.

        Faqat 2+ pending to'lov bir xil click_order_id ga bog'langan bo'lsa ishlaydi.
        Odatdagi bir martalik installment to'lovlari uchun None qaytaradi.
        """
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                # Avval ushbu click_order_id ga nechta pending to'lov bog'liq ekanligini tekshirish
                pending_count = await conn.fetchval(
                    """
                    SELECT COUNT(*) FROM installment_payments
                    WHERE click_order_id = $1 AND status = 'pending';
                    """,
                    click_order_id,
                )
                # Agar faqat 1 ta bo'lsa — bu early repayment emas, oddiy installment
                if not pending_count or pending_count < 2:
                    return None

                # Bu click_order_id ga bog'langan plan_id ni topish
                plan_id = await conn.fetchval(
                    """
                    SELECT DISTINCT plan_id
                    FROM installment_payments
                    WHERE click_order_id = $1 AND status = 'pending'
                    LIMIT 1;
                    """,
                    click_order_id,
                )
                if not plan_id:
                    return None

                # Plan ma'lumotlarini olish
                plan = await conn.fetchrow(
                    """
                    SELECT ipl.*, p.coupon_id, p.id AS purchase_id,
                           c.telegram_link AS course_telegram_link
                    FROM installment_plans ipl
                    JOIN purchases p ON p.id = ipl.purchase_id
                    JOIN courses c ON c.id = p.course_id
                    WHERE ipl.id = $1;
                    """,
                    plan_id,
                )
                if not plan:
                    return None

                # Barcha pending to'lovlarni to'langan deb belgilash
                paid_rows = await conn.fetch(
                    """
                    UPDATE installment_payments
                    SET status = 'paid', paid_at = NOW(),
                        approved_by = 0, admin_note = 'Muddatidan oldin to''landi.'
                    WHERE plan_id = $1 AND status = 'pending'
                    RETURNING id;
                    """,
                    plan_id,
                )
                newly_paid = len(paid_rows)
                if not newly_paid:
                    return None

                # paid_count ni to'g'irlab yangilash
                await conn.execute(
                    """
                    UPDATE installment_plans
                    SET paid_count = (
                        SELECT COUNT(*) FROM installment_payments
                        WHERE plan_id = $1 AND status = 'paid'
                    ),
                    status = 'completed'
                    WHERE id = $1;
                    """,
                    plan_id,
                )

                # Purchase ni tasdiqlash (agar hali pending bo'lsa)
                link = invite_link or plan["course_telegram_link"]
                await conn.execute(
                    """
                    UPDATE purchases
                    SET status = 'approved',
                        invite_link = COALESCE($2, invite_link),
                        approved_at = NOW(), updated_at = NOW()
                    WHERE id = $1 AND status IN ('pending', 'approved');
                    """,
                    plan["purchase_id"], link,
                )

                # Kupon hisobini oshirish (agar hali oshirilmagan bo'lsa)
                # (odatda 1-to'lovda allaqachon oshirilgan, lekin xavfsizlik uchun)

        return await self.get_installment_plan(plan_id)

    async def get_installment_payment_detail(self, installment_payment_id: int) -> dict | None:
        sql = """
        SELECT
            ip.*,
            ipl.installments_count,
            ipl.paid_count,
            ipl.total_amount AS plan_total,
            ipl.purchase_id,
            p.amount AS purchase_amount,
            p.course_id,
            p.coupon_discount,
            p.original_amount,
            p.is_installment,
            c.name AS course_name,
            c.telegram_link AS course_telegram_link,
            u.full_name,
            u.first_name,
            u.username,
            u.telegram_id,
            u.phone,
            (SELECT COALESCE(SUM(amount), 0)
             FROM installment_payments
             WHERE plan_id = ip.plan_id AND status = 'paid') AS paid_sum
        FROM installment_payments ip
        JOIN installment_plans ipl ON ipl.id = ip.plan_id
        JOIN purchases p ON p.id = ipl.purchase_id
        JOIN courses c ON c.id = p.course_id
        JOIN users u ON u.id = p.user_id
        WHERE ip.id = $1;
        """
        return await self.execute(sql, installment_payment_id, fetchrow=True)

    async def set_installment_click_order(
        self, installment_payment_id: int, click_order_id: int
    ) -> None:
        await self.execute(
            "UPDATE installment_payments SET click_order_id = $1 WHERE id = $2;",
            click_order_id, installment_payment_id, execute=True,
        )

    async def clear_installment_click_order(self, installment_payment_id: int) -> None:
        await self.execute(
            "UPDATE installment_payments SET click_order_id = NULL WHERE id = $1;",
            installment_payment_id, execute=True,
        )

    async def approve_installment_by_click(
        self, click_order_id: int, invite_link: str | None
    ) -> dict | None:
        """CLICK webhook — barcha o'zgarishlar bitta atomik tranzaksiyada."""
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                row = await conn.fetchrow(
                    """
                    SELECT ip.id, ip.payment_number, ip.plan_id,
                           ipl.purchase_id, ipl.installments_count,
                           p.coupon_id,
                           c.telegram_link AS course_telegram_link
                    FROM installment_payments ip
                    JOIN installment_plans ipl ON ipl.id = ip.plan_id
                    JOIN purchases p ON p.id = ipl.purchase_id
                    JOIN courses c ON c.id = p.course_id
                    WHERE ip.click_order_id = $1 AND ip.status = 'pending'
                    LIMIT 1;
                    """,
                    click_order_id,
                )
                if not row:
                    return None

                # 1. To'lovni to'langan deb belgilash
                await conn.execute(
                    """
                    UPDATE installment_payments
                    SET status = 'paid', paid_at = NOW(), approved_by = 0, admin_note = 'Tasdiqlandi.'
                    WHERE id = $1;
                    """,
                    row["id"],
                )

                # 2. paid_count ni oshirish
                new_paid = await conn.fetchval(
                    "UPDATE installment_plans SET paid_count = paid_count + 1 WHERE id = $1 RETURNING paid_count;",
                    row["plan_id"],
                )

                # 3. Agar barcha to'lovlar to'langan — plan yakunlandi
                if new_paid and new_paid >= row["installments_count"]:
                    await conn.execute(
                        "UPDATE installment_plans SET status = 'completed' WHERE id = $1;",
                        row["plan_id"],
                    )

                # 4. 1-to'lov bo'lsa — purchase ni tasdiqlash + kupon hisoblash
                if row["payment_number"] == 1:
                    link = invite_link or row["course_telegram_link"]
                    await conn.execute(
                        """
                        UPDATE purchases
                        SET status='approved', invite_link=COALESCE($2, invite_link),
                            approved_at=NOW(), updated_at=NOW()
                        WHERE id=$1 AND status='pending';
                        """,
                        row["purchase_id"], link,
                    )
                    # Kupon hisobini faqat birinchi to'lov tasdiqlanganda oshirish
                    if row.get("coupon_id"):
                        await conn.execute(
                            "UPDATE coupons SET uses_count = uses_count + 1 WHERE id = $1",
                            row["coupon_id"],
                        )

        return await self.get_installment_payment_detail(row["id"])

    async def approve_installment_payment(
        self, installment_payment_id: int, approved_by: int, note: str = ""
    ) -> dict | None:
        """Admin qo'lda tasdiqlash — barcha o'zgarishlar bitta atomik tranzaksiyada."""
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                # To'lov va plan ma'lumotlarini olish
                row = await conn.fetchrow(
                    """
                    SELECT ip.id, ip.payment_number, ip.plan_id,
                           ipl.installments_count, ipl.purchase_id
                    FROM installment_payments ip
                    JOIN installment_plans ipl ON ipl.id = ip.plan_id
                    WHERE ip.id = $1;
                    """,
                    installment_payment_id,
                )
                if not row:
                    return None

                # 1. To'lovni to'langan deb belgilash
                await conn.execute(
                    """
                    UPDATE installment_payments
                    SET status = 'paid', paid_at = NOW(), approved_by = $2, admin_note = $3
                    WHERE id = $1;
                    """,
                    installment_payment_id, approved_by, note or "Tasdiqlandi.",
                )

                # 2. paid_count ni oshirish
                new_paid = await conn.fetchval(
                    "UPDATE installment_plans SET paid_count = paid_count + 1 WHERE id = $1 RETURNING paid_count;",
                    row["plan_id"],
                )

                # 3. Agar barcha to'lovlar to'langan — plan yakunlandi
                if new_paid and new_paid >= row["installments_count"]:
                    await conn.execute(
                        "UPDATE installment_plans SET status = 'completed' WHERE id = $1;",
                        row["plan_id"],
                    )

                # 4. Admin 1-to'lovni tasdiqlaganida purchases ni ham approve qilish
                if row["payment_number"] == 1:
                    await conn.execute(
                        """
                        UPDATE purchases
                        SET status='approved', approved_by=$2, approved_at=NOW(), updated_at=NOW()
                        WHERE id=$1 AND status='pending';
                        """,
                        row["purchase_id"], approved_by,
                    )

        return await self.get_installment_payment_detail(installment_payment_id)

    async def get_upcoming_due_installments(self) -> list:
        sql = """
        SELECT
            ip.id, ip.plan_id, ip.payment_number, ip.amount, ip.due_date, ip.last_notified_at,
            ipl.installments_count, ipl.paid_count, ipl.purchase_id,
            c.name AS course_name,
            u.telegram_id
        FROM installment_payments ip
        JOIN installment_plans ipl ON ipl.id = ip.plan_id
        JOIN purchases p ON p.id = ipl.purchase_id
        JOIN courses c ON c.id = p.course_id
        JOIN users u ON u.id = p.user_id
        WHERE ip.status = 'pending'
          AND ip.due_date IS NOT NULL
          AND ip.due_date <= CURRENT_DATE + INTERVAL '3 days'
          AND (ip.last_notified_at IS NULL
               OR ip.last_notified_at < NOW() - INTERVAL '23 hours')
        ORDER BY ip.due_date;
        """
        return await self.execute(sql, fetch=True)

    async def mark_installment_notified(self, installment_payment_id: int) -> None:
        await self.execute(
            "UPDATE installment_payments SET last_notified_at = NOW() WHERE id = $1;",
            installment_payment_id, execute=True,
        )

    async def get_user_installment_plans(self, telegram_id: int) -> list:
        sql = """
        SELECT
            ipl.*,
            c.name AS course_name,
            p.coupon_discount,
            p.original_amount
        FROM installment_plans ipl
        JOIN purchases p ON p.id = ipl.purchase_id
        JOIN courses c ON c.id = p.course_id
        JOIN users u ON u.id = p.user_id
        WHERE u.telegram_id = $1 AND ipl.status = 'active'
        ORDER BY ipl.created_at DESC;
        """
        return await self.execute(sql, telegram_id, fetch=True)

    async def get_installment_plan(self, plan_id: int) -> dict | None:
        return await self.execute(
            "SELECT * FROM installment_plans WHERE id = $1;", plan_id, fetchrow=True
        )

    async def set_course_installment(self, course_id: int, enabled: bool) -> dict | None:
        sql = "UPDATE courses SET installment_available = $1 WHERE id = $2 RETURNING *;"
        return await self.execute(sql, enabled, course_id, fetchrow=True)

    # ─── Webhook idempotentlik jadvali ───────────────────────────────────────

    async def create_table_webhook_events(self) -> None:
        await self.execute("""
            CREATE TABLE IF NOT EXISTS webhook_events (
                id           BIGSERIAL PRIMARY KEY,
                event_key    VARCHAR(255) UNIQUE NOT NULL,
                source       VARCHAR(50) NOT NULL DEFAULT 'click',
                payload      JSONB NOT NULL DEFAULT '{}',
                processed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                result       JSONB,
                error        TEXT
            );
        """, execute=True)

    async def try_claim_webhook_event(self, event_key: str, payload: dict) -> bool:
        """True qaytaradi — yangi event. False — takroriy (allaqachon qayta ishlangan)."""
        import json
        row = await self.execute(
            """
            INSERT INTO webhook_events (event_key, payload)
            VALUES ($1, $2::jsonb)
            ON CONFLICT (event_key) DO NOTHING
            RETURNING id;
            """,
            event_key, json.dumps(payload), fetchval=True,
        )
        return row is not None

    # ─── DB indekslari ────────────────────────────────────────────────────────

    async def ensure_db_indexes(self) -> None:
        indexes = [
            "CREATE INDEX IF NOT EXISTS idx_purchases_click_order_id "
            "ON purchases(click_order_id) WHERE click_order_id IS NOT NULL;",

            "CREATE INDEX IF NOT EXISTS idx_purchases_user_course_status "
            "ON purchases(user_id, course_id, status);",

            "CREATE INDEX IF NOT EXISTS idx_installment_payments_click_order "
            "ON installment_payments(click_order_id) WHERE click_order_id IS NOT NULL;",

            "CREATE INDEX IF NOT EXISTS idx_installment_payments_due_pending "
            "ON installment_payments(due_date, status) WHERE status = 'pending';",

            "CREATE INDEX IF NOT EXISTS idx_webhook_events_key "
            "ON webhook_events(event_key);",
        ]
        for sql in indexes:
            await self.execute(sql, execute=True)

    async def delete_users(self):
        # Barcha foydalanuvchilarni o'chirish
        await self.execute("DELETE FROM users WHERE TRUE", execute=True)

    async def drop_users(self):
        # Users jadvalini o'chirish
        await self.execute("DROP TABLE IF EXISTS users", execute=True)
