import aiosqlite
from datetime import datetime, date
from config import DB_PATH

async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.executescript("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                name TEXT,
                weight_current REAL,
                weight_goal REAL,
                height INTEGER,
                age INTEGER,
                activity_level TEXT DEFAULT 'moderate',
                motivation_type TEXT DEFAULT 'supportive',
                daily_calories_target INTEGER DEFAULT 1800,
                daily_protein_target INTEGER DEFAULT 100,
                created_at TEXT DEFAULT (datetime('now'))
            );
            CREATE TABLE IF NOT EXISTS meals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                description TEXT,
                calories INTEGER,
                protein REAL,
                carbs REAL,
                fat REAL,
                photo_id TEXT,
                ai_response TEXT,
                created_at TEXT DEFAULT (datetime('now'))
            );
            CREATE TABLE IF NOT EXISTS weight_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                weight REAL,
                created_at TEXT DEFAULT (datetime('now'))
            );
            CREATE TABLE IF NOT EXISTS activity_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                activity_type TEXT,
                duration_min INTEGER,
                calories_burned INTEGER,
                created_at TEXT DEFAULT (datetime('now'))
            );
        """)
        await db.commit()


async def get_user(user_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)) as cur:
            return await cur.fetchone()


async def upsert_user(user_id: int, **fields):
    user = await get_user(user_id)
    async with aiosqlite.connect(DB_PATH) as db:
        if user:
            sets = ", ".join(f"{k} = ?" for k in fields)
            vals = list(fields.values()) + [user_id]
            await db.execute(f"UPDATE users SET {sets} WHERE user_id = ?", vals)
        else:
            fields["user_id"] = user_id
            cols = ", ".join(fields.keys())
            placeholders = ", ".join("?" for _ in fields)
            await db.execute(f"INSERT INTO users ({cols}) VALUES ({placeholders})", list(fields.values()))
        await db.commit()


async def add_meal(user_id: int, description: str, calories: int, protein: float,
                   carbs: float, fat: float, photo_id: str = None, ai_response: str = None):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO meals (user_id, description, calories, protein, carbs, fat, photo_id, ai_response) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (user_id, description, calories, protein, carbs, fat, photo_id, ai_response)
        )
        await db.commit()


async def add_weight(user_id: int, weight: float):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("INSERT INTO weight_log (user_id, weight) VALUES (?, ?)", (user_id, weight))
        await db.execute("UPDATE users SET weight_current = ? WHERE user_id = ?", (weight, user_id))
        await db.commit()


async def add_activity(user_id: int, activity_type: str, duration_min: int, calories_burned: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO activity_log (user_id, activity_type, duration_min, calories_burned) VALUES (?, ?, ?, ?)",
            (user_id, activity_type, duration_min, calories_burned)
        )
        await db.commit()


async def get_today_meals(user_id: int):
    today = date.today().isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM meals WHERE user_id = ? AND date(created_at) = ?",
            (user_id, today)
        ) as cur:
            return await cur.fetchall()


async def get_today_stats(user_id: int):
    today = date.today().isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT COALESCE(SUM(calories),0), COALESCE(SUM(protein),0), "
            "COALESCE(SUM(carbs),0), COALESCE(SUM(fat),0), COUNT(*) "
            "FROM meals WHERE user_id = ? AND date(created_at) = ?",
            (user_id, today)
        ) as cur:
            row = await cur.fetchone()
        async with db.execute(
            "SELECT COALESCE(SUM(calories_burned),0) FROM activity_log "
            "WHERE user_id = ? AND date(created_at) = ?",
            (user_id, today)
        ) as cur:
            burned = (await cur.fetchone())[0]
    return {
        "calories": int(row[0]),
        "protein": round(row[1], 1),
        "carbs": round(row[2], 1),
        "fat": round(row[3], 1),
        "meal_count": row[4],
        "calories_burned": int(burned),
    }


async def get_week_stats(user_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT date(created_at) as day, SUM(calories), SUM(protein) "
            "FROM meals WHERE user_id = ? AND created_at >= date('now', '-7 days') "
            "GROUP BY date(created_at) ORDER BY day",
            (user_id,)
        ) as cur:
            meals = await cur.fetchall()
        async with db.execute(
            "SELECT date(created_at) as day, weight FROM weight_log "
            "WHERE user_id = ? AND created_at >= date('now', '-7 days') "
            "ORDER BY created_at",
            (user_id,)
        ) as cur:
            weights = await cur.fetchall()
        async with db.execute(
            "SELECT date(created_at) as day, SUM(calories_burned), SUM(duration_min) "
            "FROM activity_log WHERE user_id = ? AND created_at >= date('now', '-7 days') "
            "GROUP BY date(created_at) ORDER BY day",
            (user_id,)
        ) as cur:
            activities = await cur.fetchall()
    return {
        "daily_calories": [(r[0], int(r[1]), round(r[2], 1)) for r in meals],
        "weights": [(r[0], r[1]) for r in weights],
        "activities": [(r[0], int(r[1]), int(r[2])) for r in activities],
    }


async def get_progress(user_id: int):
    user = await get_user(user_id)
    if not user:
        return None
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT weight, created_at FROM weight_log WHERE user_id = ? ORDER BY created_at",
            (user_id,)
        ) as cur:
            all_weights = await cur.fetchall()
        async with db.execute(
            "SELECT COUNT(*), COALESCE(AVG(calories),0) FROM meals WHERE user_id = ?",
            (user_id,)
        ) as cur:
            meal_stats = await cur.fetchone()
        async with db.execute(
            "SELECT COUNT(*), COALESCE(SUM(duration_min),0) FROM activity_log WHERE user_id = ?",
            (user_id,)
        ) as cur:
            activity_stats = await cur.fetchone()
    return {
        "user": dict(user),
        "weights": [(w[0], w[1]) for w in all_weights],
        "total_meals": meal_stats[0],
        "avg_calories": round(meal_stats[1]),
        "total_workouts": activity_stats[0],
        "total_workout_minutes": activity_stats[1],
    }
