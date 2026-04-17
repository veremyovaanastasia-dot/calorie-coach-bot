import aiosqlite
from datetime import datetime, date, timezone, timedelta
from zoneinfo import ZoneInfo
from config import DB_PATH

# Lisbon timezone (WET/WEST — auto DST: UTC+0 winter, UTC+1 summer)
LOCAL_TZ = ZoneInfo("Europe/Lisbon")

def today_local() -> str:
    """Return today's date in Lisbon timezone."""
    return datetime.now(LOCAL_TZ).strftime("%Y-%m-%d")

def now_local() -> str:
    """Return current datetime in Lisbon timezone."""
    return datetime.now(LOCAL_TZ).strftime("%Y-%m-%d %H:%M:%S")

def days_ago_local(n: int) -> str:
    """Return date N days ago in Lisbon timezone."""
    return (datetime.now(LOCAL_TZ) - timedelta(days=n)).strftime("%Y-%m-%d")

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
                created_at TEXT
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
                created_at TEXT
            );
            CREATE TABLE IF NOT EXISTS weight_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                weight REAL,
                created_at TEXT
            );
            CREATE TABLE IF NOT EXISTS activity_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                activity_type TEXT,
                duration_min INTEGER,
                calories_burned INTEGER,
                created_at TEXT
            );
            CREATE TABLE IF NOT EXISTS chat_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                role TEXT,
                content TEXT,
                created_at TEXT
            );
            CREATE TABLE IF NOT EXISTS sleep_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                hours REAL,
                quality TEXT,
                note TEXT,
                created_at TEXT
            );
            CREATE TABLE IF NOT EXISTS mood_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                mood TEXT,
                energy INTEGER,
                note TEXT,
                created_at TEXT
            );
            CREATE TABLE IF NOT EXISTS cycle_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                day_of_cycle INTEGER,
                phase TEXT,
                note TEXT,
                created_at TEXT
            );
        """)
        # Migration: add pinned columns if missing
        for col in ["pinned_message_id INTEGER", "pinned_date TEXT"]:
            try:
                await db.execute(f"ALTER TABLE users ADD COLUMN {col}")
            except Exception:
                pass
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
            fields["created_at"] = now_local()
            cols = ", ".join(fields.keys())
            placeholders = ", ".join("?" for _ in fields)
            await db.execute(f"INSERT INTO users ({cols}) VALUES ({placeholders})", list(fields.values()))
        await db.commit()


async def add_meal(user_id: int, description: str, calories: int, protein: float,
                   carbs: float, fat: float, photo_id: str = None, ai_response: str = None):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO meals (user_id, description, calories, protein, carbs, fat, photo_id, ai_response, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (user_id, description, calories, protein, carbs, fat, photo_id, ai_response, now_local())
        )
        await db.commit()


async def add_weight(user_id: int, weight: float):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("INSERT INTO weight_log (user_id, weight, created_at) VALUES (?, ?, ?)",
                         (user_id, weight, now_local()))
        await db.execute("UPDATE users SET weight_current = ? WHERE user_id = ?", (weight, user_id))
        await db.commit()


async def add_activity(user_id: int, activity_type: str, duration_min: int, calories_burned: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO activity_log (user_id, activity_type, duration_min, calories_burned, created_at) VALUES (?, ?, ?, ?, ?)",
            (user_id, activity_type, duration_min, calories_burned, now_local())
        )
        await db.commit()


async def get_today_activities(user_id: int):
    today = today_local()
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM activity_log WHERE user_id = ? AND date(created_at) = ?",
            (user_id, today)
        ) as cur:
            return await cur.fetchall()


async def get_today_sleep(user_id: int):
    today = today_local()
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM sleep_log WHERE user_id = ? AND date(created_at) = ? ORDER BY id DESC LIMIT 1",
            (user_id, today)
        ) as cur:
            return await cur.fetchone()


async def get_today_mood(user_id: int):
    today = today_local()
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM mood_log WHERE user_id = ? AND date(created_at) = ? ORDER BY id DESC LIMIT 1",
            (user_id, today)
        ) as cur:
            return await cur.fetchone()


async def get_today_cycle(user_id: int):
    """Get latest cycle entry (today or most recent)."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM cycle_log WHERE user_id = ? ORDER BY id DESC LIMIT 1",
            (user_id,)
        ) as cur:
            return await cur.fetchone()


async def delete_last_meal(user_id: int) -> dict | None:
    """Delete the most recent meal for today and return it (or None)."""
    today = today_local()
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM meals WHERE user_id = ? AND date(created_at) = ? ORDER BY id DESC LIMIT 1",
            (user_id, today)
        ) as cur:
            row = await cur.fetchone()
        if not row:
            return None
        meal = dict(row)
        await db.execute("DELETE FROM meals WHERE id = ?", (meal["id"],))
        await db.commit()
        return meal


async def delete_meal_by_id(user_id: int, meal_id: int) -> dict | None:
    """Delete a specific meal by ID (only if it belongs to this user)."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM meals WHERE id = ? AND user_id = ?",
            (meal_id, user_id)
        ) as cur:
            row = await cur.fetchone()
        if not row:
            return None
        meal = dict(row)
        await db.execute("DELETE FROM meals WHERE id = ?", (meal_id,))
        await db.commit()
        return meal


async def get_today_meals(user_id: int):
    today = today_local()
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM meals WHERE user_id = ? AND date(created_at) = ?",
            (user_id, today)
        ) as cur:
            return await cur.fetchall()


async def get_today_stats(user_id: int):
    today = today_local()
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
    week_ago = days_ago_local(7)
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT date(created_at) as day, SUM(calories), SUM(protein) "
            "FROM meals WHERE user_id = ? AND created_at >= ? "
            "GROUP BY date(created_at) ORDER BY day",
            (user_id, week_ago)
        ) as cur:
            meals = await cur.fetchall()
        async with db.execute(
            "SELECT date(created_at) as day, weight FROM weight_log "
            "WHERE user_id = ? AND created_at >= ? "
            "ORDER BY created_at",
            (user_id, week_ago)
        ) as cur:
            weights = await cur.fetchall()
        async with db.execute(
            "SELECT date(created_at) as day, SUM(calories_burned), SUM(duration_min) "
            "FROM activity_log WHERE user_id = ? AND created_at >= ? "
            "GROUP BY date(created_at) ORDER BY day",
            (user_id, week_ago)
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
            "INSERT INTO chat_history (user_id, role, content, created_at) VALUES (?, ?, ?, ?)",
            (user_id, role, content, now_local())
        )
        await db.commit()


async def get_chat_history(user_id: int, limit: int = 20):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT role, content, created_at FROM ("
            "  SELECT role, content, created_at, id FROM chat_history "
            "  WHERE user_id = ? ORDER BY id DESC LIMIT ?"
            ") ORDER BY id ASC",
            (user_id, limit)
        ) as cur:
            rows = await cur.fetchall()
    today = today_local()
    result = []
    for r in rows:
        msg_date = r[2][:10] if r[2] else ""
        if msg_date and msg_date != today:
            # Prefix old messages with date so AI knows they're not from today
            content = f"[{msg_date}] {r[1]}"
        else:
            content = r[1]
        result.append({"role": r[0], "content": content})
    return result


async def add_sleep(user_id: int, hours: float, quality: str = None, note: str = None):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO sleep_log (user_id, hours, quality, note, created_at) VALUES (?, ?, ?, ?, ?)",
            (user_id, hours, quality, note, now_local())
        )
        await db.commit()


async def add_mood(user_id: int, mood: str, energy: int = None, note: str = None):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO mood_log (user_id, mood, energy, note, created_at) VALUES (?, ?, ?, ?, ?)",
            (user_id, mood, energy, note, now_local())
        )
        await db.commit()


async def add_cycle(user_id: int, day_of_cycle: int, phase: str = None, note: str = None):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO cycle_log (user_id, day_of_cycle, phase, note, created_at) VALUES (?, ?, ?, ?, ?)",
            (user_id, day_of_cycle, phase, note, now_local())
        )
        await db.commit()


async def build_client_context(user_id: int) -> str:
    """Build a day-by-day diary for the AI — like a real coach's notes."""
    user = await get_user(user_id)
    if not user:
        return ""

    today = today_local()
    days_14_ago = days_ago_local(14)
    days_90_ago = days_ago_local(90)

    async with aiosqlite.connect(DB_PATH) as db:
        # All meals last 14 days
        async with db.execute(
            "SELECT date(created_at) as day, description, calories, protein "
            "FROM meals WHERE user_id = ? AND created_at >= ? ORDER BY created_at",
            (user_id, days_14_ago)
        ) as cur:
            all_meals = await cur.fetchall()

        # Activities last 14 days
        async with db.execute(
            "SELECT date(created_at) as day, activity_type, duration_min, calories_burned "
            "FROM activity_log WHERE user_id = ? AND created_at >= ? ORDER BY created_at",
            (user_id, days_14_ago)
        ) as cur:
            all_activities = await cur.fetchall()

        # Sleep last 14 days
        async with db.execute(
            "SELECT date(created_at) as day, hours, quality "
            "FROM sleep_log WHERE user_id = ? AND created_at >= ? ORDER BY created_at",
            (user_id, days_14_ago)
        ) as cur:
            all_sleep = await cur.fetchall()

        # Mood last 14 days
        async with db.execute(
            "SELECT date(created_at) as day, mood, note "
            "FROM mood_log WHERE user_id = ? AND created_at >= ? ORDER BY created_at",
            (user_id, days_14_ago)
        ) as cur:
            all_mood = await cur.fetchall()

        # Cycle last 14 days
        async with db.execute(
            "SELECT date(created_at) as day, day_of_cycle, phase "
            "FROM cycle_log WHERE user_id = ? AND created_at >= ? ORDER BY created_at",
            (user_id, days_14_ago)
        ) as cur:
            all_cycle = await cur.fetchall()

        # Weight all time
        async with db.execute(
            "SELECT weight, date(created_at) FROM weight_log WHERE user_id = ? ORDER BY created_at",
            (user_id,)
        ) as cur:
            all_weights = await cur.fetchall()

        # Older weekly summaries (weeks 3-12) for long-term view
        async with db.execute(
            "SELECT MIN(date(created_at)) || '..' || MAX(date(created_at)), "
            "  ROUND(AVG(day_cal)), ROUND(AVG(day_prot)), COUNT(*) "
            "FROM (SELECT date(created_at) as d, SUM(calories) as day_cal, "
            "  SUM(protein) as day_prot, created_at "
            "  FROM meals WHERE user_id = ? AND created_at >= ? AND created_at < ? "
            "  GROUP BY date(created_at)) "
            "GROUP BY strftime('%W', created_at) ORDER BY MIN(created_at)",
            (user_id, days_90_ago, days_14_ago)
        ) as cur:
            older_weeks = await cur.fetchall()

    # Group by day
    from collections import defaultdict
    days = defaultdict(lambda: {"meals": [], "act": [], "sleep": [], "mood": [], "cycle": []})

    for r in all_meals:
        days[r[0]]["meals"].append({"d": r[1], "c": r[2], "p": r[3]})
    for r in all_activities:
        days[r[0]]["act"].append({"t": r[1], "m": r[2], "b": r[3]})
    for r in all_sleep:
        days[r[0]]["sleep"].append({"h": r[1], "q": r[2]})
    for r in all_mood:
        days[r[0]]["mood"].append({"m": r[1], "n": r[2]})
    for r in all_cycle:
        days[r[0]]["cycle"].append({"day": r[1], "ph": r[2]})

    parts = []

    # Weight
    if all_weights:
        w0, wN = all_weights[0], all_weights[-1]
        parts.append(f"Вес: {w0[0]} ({w0[1]}) → {wN[0]} ({wN[1]}), {wN[0]-w0[0]:+.1f} кг")

    # Day-by-day diary (skip today — today's meals go separately)
    sorted_days = sorted(d for d in days if d != today)
    if sorted_days:
        parts.append("\nДНЕВНИК ПО ДНЯМ:")
        for day in sorted_days:
            d = days[day]
            line_parts = []
            if d["meals"]:
                total_c = sum(m["c"] for m in d["meals"])
                total_p = sum(m["p"] for m in d["meals"])
                foods = ", ".join(m["d"] for m in d["meals"])
                line_parts.append(f"еда: {foods} = {total_c}ккал/{total_p:.0f}г белка")
            if d["act"]:
                acts = ", ".join(f"{a['t']} {a['m']}мин" for a in d["act"])
                line_parts.append(f"активность: {acts}")
            if d["sleep"]:
                s = d["sleep"][-1]
                line_parts.append(f"сон: {s['h']}ч" + (f" ({s['q']})" if s["q"] else ""))
            if d["mood"]:
                line_parts.append(f"настроение: {d['mood'][-1]['m']}")
            if d["cycle"]:
                c = d["cycle"][-1]
                line_parts.append(f"цикл: день {c['day']} ({c['ph']})")
            if line_parts:
                parts.append(f"{day}: {' | '.join(line_parts)}")

    # Older weeks
    if older_weeks:
        parts.append("\nСТАРШЕ 2 НЕДЕЛЬ (средние по неделям):")
        for wk in older_weeks:
            parts.append(f"{wk[0]}: ~{wk[1]:.0f} ккал/день, ~{wk[2]:.0f}г белка, {wk[3]} дней с записями")

    if not parts:
        return ""
    return "\n\n## ИСТОРИЯ КЛИЕНТА\n" + "\n".join(parts)


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
