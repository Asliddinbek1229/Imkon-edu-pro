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
        await self.create_table_purchases()
        await self.ensure_purchases_columns()
        await self.create_table_user_access()

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
            "ALTER TABLE courses ADD COLUMN IF NOT EXISTS thumbnail VARCHAR(500)",
            "ALTER TABLE courses ADD COLUMN IF NOT EXISTS is_active BOOLEAN NOT NULL DEFAULT TRUE",
            "ALTER TABLE courses ADD COLUMN IF NOT EXISTS is_bundle BOOLEAN NOT NULL DEFAULT FALSE",
            "ALTER TABLE courses ADD COLUMN IF NOT EXISTS bundle_courses JSONB NOT NULL DEFAULT '[]'::jsonb",
            "ALTER TABLE courses ADD COLUMN IF NOT EXISTS sort_order INTEGER NOT NULL DEFAULT 100",
            "ALTER TABLE courses ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()",
            "ALTER TABLE courses ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()",
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
            "ALTER TABLE purchases ADD COLUMN IF NOT EXISTS receipt_file_id VARCHAR(500)",
            "ALTER TABLE purchases ADD COLUMN IF NOT EXISTS card_number_used VARCHAR(30)",
            "ALTER TABLE purchases ADD COLUMN IF NOT EXISTS admin_note TEXT",
            "ALTER TABLE purchases ADD COLUMN IF NOT EXISTS approved_by BIGINT",
            "ALTER TABLE purchases ADD COLUMN IF NOT EXISTS invite_link VARCHAR(500)",
            "ALTER TABLE purchases ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()",
            "ALTER TABLE purchases ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()",
            "ALTER TABLE purchases ADD COLUMN IF NOT EXISTS approved_at TIMESTAMPTZ",
            "ALTER TABLE purchases ADD COLUMN IF NOT EXISTS rejected_at TIMESTAMPTZ",
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
        telegram_link: str | None = None,
        author: str = "Maqsudxon Mo'minxonov",
        duration: str | None = None,
        target_exam: str | None = "DTM, Milliy Sertifikat, Attestatsiya",
        includes: str | None = None,
        access_type: str = "Hayotbod",
        sort_order: int = 100,
    ):
        sql = """
        INSERT INTO courses (
            name, description, price, video_count, thumbnail, telegram_link,
            author, duration, target_exam, includes, access_type, sort_order, updated_at
        )
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, NOW())
        RETURNING *;
        """
        return await self.execute(
            sql,
            name,
            description,
            price,
            video_count,
            thumbnail,
            telegram_link,
            author,
            duration,
            target_exam,
            includes,
            access_type,
            sort_order,
            fetchrow=True,
        )

    async def update_course_field(self, course_id: int, field_name: str, value):
        allowed_fields = {
            "name",
            "description",
            "price",
            "video_count",
            "thumbnail",
            "telegram_link",
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
            user_id, course_id, amount, status, invite_link, approved_at, updated_at
        )
        VALUES ($1, $2, $3, $4, $5, {approved_at_sql}, NOW())
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

    async def select_active_purchase_for_course(self, user_id: int, course_id: int):
        sql = """
        SELECT
            p.*,
            c.name AS course_name,
            c.description AS course_description,
            c.telegram_link AS course_telegram_link,
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

    async def select_purchase_by_id(self, purchase_id: int):
        sql = """
        SELECT
            p.*,
            c.name AS course_name,
            c.description AS course_description,
            c.telegram_link AS course_telegram_link,
            c.thumbnail AS course_thumbnail,
            c.video_count AS course_video_count,
            c.access_type AS course_access_type,
            u.telegram_id,
            u.full_name,
            u.phone
        FROM purchases p
        JOIN courses c ON c.id = p.course_id
        JOIN users u ON u.id = p.user_id
        WHERE p.id = $1;
        """
        return await self.execute(sql, purchase_id, fetchrow=True)

    async def count_user_purchases(self, telegram_id: int):
        sql = """
        SELECT COUNT(*)
        FROM purchases p
        JOIN users u ON u.id = p.user_id
        WHERE u.telegram_id = $1;
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
            c.thumbnail AS course_thumbnail,
            c.video_count AS course_video_count,
            c.access_type AS course_access_type
        FROM purchases p
        JOIN users u ON u.id = p.user_id
        JOIN courses c ON c.id = p.course_id
        WHERE u.telegram_id = $1
        ORDER BY p.created_at DESC, p.id DESC
        LIMIT $2 OFFSET $3;
        """
        return await self.execute(sql, telegram_id, limit, offset, fetch=True)

    async def select_user_purchase(self, telegram_id: int, purchase_id: int):
        sql = """
        SELECT
            p.*,
            c.name AS course_name,
            c.description AS course_description,
            c.telegram_link AS course_telegram_link,
            c.thumbnail AS course_thumbnail,
            c.video_count AS course_video_count,
            c.access_type AS course_access_type,
            u.telegram_id,
            u.full_name,
            u.phone
        FROM purchases p
        JOIN users u ON u.id = p.user_id
        JOIN courses c ON c.id = p.course_id
        WHERE u.telegram_id = $1 AND p.id = $2;
        """
        return await self.execute(sql, telegram_id, purchase_id, fetchrow=True)

    async def delete_users(self):
        # Barcha foydalanuvchilarni o'chirish
        await self.execute("DELETE FROM users WHERE TRUE", execute=True)

    async def drop_users(self):
        # Users jadvalini o'chirish
        await self.execute("DROP TABLE IF EXISTS users", execute=True)
