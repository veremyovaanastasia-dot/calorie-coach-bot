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
            CREATE TABLE IF NOT EXISTS chat_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                role TEXT,
                content TEXT,
                created_at TEXT DEFAULT (datetime('now'))
            );
            CREATE TABLE IF NOT EXISTS sleep_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                hours REAL,
                quality TEXT,
                note TEXT,
                created_at TEXT DEFAULT (datetime('now'))
            );
            CREATE TABLE IF NOT EXISTS mood_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                mood TEXT,
                energy INTEGER,
                note TEXT,
                created_at TEXT DEFAULT (datetime('now'))
            );
            CREATE TABLE IF NOT EXISTS cycle_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                day_of_cycle INTEGER,
                phase TEXT,
                note TEXT,
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


async def add_chat_message(user_id: int, role: str, content: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO chat_history (user_id, role, content) VALUES (?, ?, ?)",
            (user_id, role, content)
        )
        await db.commit()


async def get_chat_history(user_id: int, limit: int = 20):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT role, content FROM ("
            "  SELECT role, content, id FROM chat_history "
            "  WHERE user_id = ? ORDER BY id DESC LIMIT ?"
            ") ORDER BY id ASC",
            (user_id, limit)
        ) as cur:
            rows = await cur.fetchall()
    return [{"role": r[0], "content": r[1]} for r in rows]


async def add_sleep(user_id: int, hours: float, quality: str = None, note: str = None):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO sleep_log (user_id, hours, quality, note) VALUES (?, ?, ?, ?)",
            (user_id, hours, quality, note)
        )
        await db.commit()


async def add_mood(user_id: int, mood: str, energy: int = None, note: str = None):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO mood_log (user_id, mood, energy, note) VALUES (?, ?, ?, ?)",
            (user_id, mood, energy, note)
        )
        await db.commit()


async def add_cycle(user_id: int, day_of_cycle: int, phase: str = None, note: str = None):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO cycle_log (user_id, day_of_cycle, phase, note) VALUES (?, ?, ?, ?)",
            (user_id, day_of_cycle, phase, note)
        )
        await db.commit()


async def build_client_context(user_id: int) -> str:
    """Build a comprehensive client context for the AI from ALL historical data."""
    user = await get_user(user_id)
    if not user:
        return ""

    parts = []
    async with aiosqlite.connect(DB_PATH) as db:
        # Weight trend (all time)
        async with db.execute(
            "SELECT weight, date(created_at) FROM weight_log WHERE user_id = ? ORDER BY created_at",
            (user_id,)
        ) as cur:
            weights = await cur.fetchall()
        if weights:
            first_w, last_w = weights[0][0], weights[-1][0]
            parts.append(f"Вес: {first_w} кг ({weights[0][1]}) → {last_w} кг ({weights[-1][1]}), изменение {last_w - first_w:+.1f} кг за {len(weights)} замеров")
            if len(weights) >= 3:
                recent = [w[0] for w in weights[-7:]]
                trend = "снижается" if recent[-1] < recent[0] else "растёт" if recent[-1] > recent[0] else "стабильный"
                parts.append(f"Тренд веса (последние замеры): {trend}")

        # Weekly food averages (last 14 days)
        async with db.execute(
            "SELECT date(created_at) as day, SUM(calories), SUM(protein), COUNT(*) "
            "FROM meals WHERE user_id = ? AND created_at >= date('now', '-14 days') "
            "GROUP BY date(created_at) ORDER BY day",
            (user_id,)
        ) as cur:
            daily_food = await cur.fetchall()
        if daily_food:
            avg_cal = sum(r[1] for r in daily_food) / len(daily_food)
            avg_prot = sum(r[2] for r in daily_food) / len(daily_food)
            avg_meals = sum(r[3] for r in daily_food) / len(daily_food)
            parts.append(f"Питание (среднее за {len(daily_food)} дней): {avg_cal:.0f} ккал, {avg_prot:.0f}г белка, {avg_meals:.1f} приёмов/день")

            # Find patterns: frequent foods
            async with db.execute(
                "SELECT description, COUNT(*) as cnt FROM meals WHERE user_id = ? "
                "AND created_at >= date('now', '-14 days') GROUP BY description ORDER BY cnt DESC LIMIT 5",
                (user_id,)
            ) as cur:
                top_foods = await cur.fetchall()
            if top_foods:
                foods_str = ", ".join(f"{f[0]} ({f[1]}x)" for f in top_foods)
                parts.append(f"Частая еда: {foods_str}")

        # Activity summary (last 14 days)
        async with db.execute(
            "SELECT COUNT(*), COALESCE(SUM(duration_min),0), COALESCE(SUM(calories_burned),0) "
            "FROM activity_log WHERE user_id = ? AND created_at >= date('now', '-14 days')",
            (user_id,)
        ) as cur:
            act = await cur.fetchone()
        if act[0] > 0:
            parts.append(f"Активность (14 дн): {act[0]} тренировок, {act[1]} мин, -{act[2]} ккал")

        # Sleep (last 7 days)
        async with db.execute(
            "SELECT hours, quality, note, date(created_at) FROM sleep_log "
            "WHERE user_id = ? AND created_at >= date('now', '-7 days') ORDER BY created_at",
            (user_id,)
        ) as cur:
            sleeps = await cur.fetchall()
        if sleeps:
            avg_sleep = sum(s[0] for s in sleeps) / len(sleeps)
            parts.append(f"Сон (7 дн): среднее {avg_sleep:.1f}ч за {len(sleeps)} записей")
            last_sleep = sleeps[-1]
            parts.append(f"Последний сон: {last_sleep[0]}ч" + (f", {last_sleep[1]}" if last_sleep[1] else "") + (f" — {last_sleep[2]}" if last_sleep[2] else ""))

        # Mood (last 7 days)
        async with db.execute(
            "SELECT mood, energy, note, date(created_at) FROM mood_log "
            "WHERE user_id = ? AND created_at >= date('now', '-7 days') ORDER BY created_at",
            (user_id,)
        ) as cur:
            moods = await cur.fetchall()
        if moods:
            mood_list = [f"{m[3]}: {m[0]}" + (f" (энергия {m[1]}/10)" if m[1] else "") for m in moods[-5:]]
            parts.append(f"Настроение (последние): {'; '.join(mood_list)}")

        # Cycle (last entry)
        async with db.execute(
            "SELECT day_of_cycle, phase, note, date(created_at) FROM cycle_log "
            "WHERE user_id = ? ORDER BY created_at DESC LIMIT 1",
            (user_id,)
        ) as cur:
            cycle = await cur.fetchone()
        if cycle:
            parts.append(f"Цикл: день {cycle[0]}" + (f", фаза: {cycle[1]}" if cycle[1] else "") + (f" ({cycle[3]})" if cycle[3] else ""))

    if not parts:
        return ""
    return "\n\n## ПОЛНЫЙ КОНТЕКСТ КЛИЕНТА (исторические данные)\n" + "\n".join(f"- {p}" for p in parts)


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
