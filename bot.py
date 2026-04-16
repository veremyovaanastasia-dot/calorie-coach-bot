import io
import logging
from datetime import time as dtime

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from datetime import datetime

from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import (
    Application, CommandHandler, MessageHandler, ConversationHandler,
    ContextTypes, filters,
)

import db
import ai
from config import TELEGRAM_TOKEN

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

# Onboarding states
NAME, WEIGHT, HEIGHT, AGE, GOAL, MOTIVATION = range(6)


# ── /start onboarding ──────────────────────────────────────────────

async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Привет! Я твой персональный коуч по питанию и похудению.\n\n"
        "Давай познакомимся. Как тебя зовут?"
    )
    return NAME

async def onboard_name(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data["name"] = update.message.text.strip()
    await update.message.reply_text(f"Приятно, {ctx.user_data['name']}! Сколько ты весишь сейчас? (кг)")
    return WEIGHT

async def onboard_weight(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    try:
        ctx.user_data["weight"] = float(update.message.text.replace(",", "."))
    except ValueError:
        await update.message.reply_text("Введи число, например 67.5")
        return WEIGHT
    await update.message.reply_text("Какой у тебя рост? (см)")
    return HEIGHT

async def onboard_height(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    try:
        ctx.user_data["height"] = int(update.message.text)
    except ValueError:
        await update.message.reply_text("Введи число, например 165")
        return HEIGHT
    await update.message.reply_text("Сколько тебе лет?")
    return AGE

async def onboard_age(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    try:
        ctx.user_data["age"] = int(update.message.text)
    except ValueError:
        await update.message.reply_text("Введи число")
        return AGE
    await update.message.reply_text("Какой вес — твоя цель? (кг)")
    return GOAL

async def onboard_goal(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    try:
        ctx.user_data["goal"] = float(update.message.text.replace(",", "."))
    except ValueError:
        await update.message.reply_text("Введи число, например 60")
        return GOAL
    kb = ReplyKeyboardMarkup(
        [["Мягкая поддержка", "Жёсткий тренер", "Аналитик"]],
        one_time_keyboard=True, resize_keyboard=True,
    )
    await update.message.reply_text(
        "Какой стиль мотивации тебе ближе?\n\n"
        "🤗 Мягкая поддержка — похвала, без давления\n"
        "💪 Жёсткий тренер — конкретика, без отмазок\n"
        "📊 Аналитик — цифры, факты, проценты",
        reply_markup=kb,
    )
    return MOTIVATION

async def onboard_motivation(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.lower()
    if "жёстк" in text or "жестк" in text or "тренер" in text:
        mtype = "strict"
    elif "аналитик" in text or "цифр" in text:
        mtype = "analytical"
    else:
        mtype = "supportive"

    ud = ctx.user_data
    # Calculate daily targets (Mifflin-St Jeor + deficit)
    bmr = 10 * ud["weight"] + 6.25 * ud["height"] - 5 * ud["age"] - 161  # female
    tdee = bmr * 1.4  # moderate activity
    cal_target = max(1200, int(tdee - 400))  # ~400 kcal deficit
    protein_target = int(ud["weight"] * 1.6)  # 1.6g per kg

    await db.upsert_user(
        update.effective_user.id,
        name=ud["name"],
        weight_current=ud["weight"],
        weight_goal=ud["goal"],
        height=ud["height"],
        age=ud["age"],
        motivation_type=mtype,
        daily_calories_target=cal_target,
        daily_protein_target=protein_target,
    )
    await db.add_weight(update.effective_user.id, ud["weight"])

    style_names = {"supportive": "мягкая поддержка", "strict": "жёсткий тренер", "analytical": "аналитик"}
    await update.message.reply_text(
        f"Готово! Вот твой план:\n\n"
        f"📊 Текущий вес: {ud['weight']} кг → цель: {ud['goal']} кг\n"
        f"🔥 Дневная норма: {cal_target} ккал\n"
        f"🥩 Белок: {protein_target} г\n"
        f"💬 Стиль: {style_names[mtype]}\n\n"
        f"Теперь просто отправляй мне фото еды или пиши что съела — я посчитаю калории.\n\n"
        f"Команды:\n"
        f"/today — итог дня\n"
        f"/week — неделя\n"
        f"/progress — полный прогресс\n"
        f"/weight 67 — записать вес\n"
        f"/activity бег 30мин — записать тренировку\n"
        f"/coach — попросить совет",
        reply_markup=ReplyKeyboardRemove(),
    )
    return ConversationHandler.END

async def cancel(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Ок, отменено.", reply_markup=ReplyKeyboardRemove())
    return ConversationHandler.END


# ── Food logging (photo) ───────────────────────────────────────────

async def handle_photo(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = await db.get_user(update.effective_user.id)
    if not user:
        await update.message.reply_text("Сначала пройди /start")
        return

    msg = await update.message.reply_text("Анализирую фото...")
    photo = update.message.photo[-1]
    file = await ctx.bot.get_file(photo.file_id)
    buf = io.BytesIO()
    await file.download_to_memory(buf)
    photo_bytes = buf.getvalue()

    today_stats = await db.get_today_stats(update.effective_user.id)
    caption = update.message.caption or ""
    result = await ai.analyze_food_photo(photo_bytes, dict(user), today_stats, caption)

    if "error" in result:
        await msg.edit_text(f"Не удалось распознать: {result['error']}")
        return

    await db.add_meal(
        update.effective_user.id,
        description=result.get("dish", caption),
        calories=result.get("calories", 0),
        protein=result.get("protein", 0),
        carbs=result.get("carbs", 0),
        fat=result.get("fat", 0),
        photo_id=photo.file_id,
    )

    today_stats = await db.get_today_stats(update.effective_user.id)
    remaining = user["daily_calories_target"] - today_stats["calories"]

    text = (
        f"🍽 {result.get('dish', 'Блюдо')}\n"
        f"   {result.get('portion', '')}\n\n"
        f"🔥 {result['calories']} ккал\n"
        f"🥩 Белок: {result['protein']} г\n"
        f"🍞 Углеводы: {result['carbs']} г\n"
        f"🧈 Жиры: {result['fat']} г\n\n"
    )
    if result.get("comment"):
        text += f"💬 {result['comment']}\n\n"
    text += f"📊 Итого за день: {today_stats['calories']} ккал | осталось: {remaining} ккал"
    await msg.edit_text(text)


# ── Food logging (text) ────────────────────────────────────────────

async def handle_text(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = await db.get_user(update.effective_user.id)
    if not user:
        await update.message.reply_text("Сначала пройди /start")
        return

    text = update.message.text.strip()
    today_stats = await db.get_today_stats(update.effective_user.id)

    # Check if it's a coaching question or food
    food_keywords = ["съел", "съела", "ел", "ела", "пил", "пила", "завтрак", "обед", "ужин",
                     "перекус", "каша", "салат", "суп", "кофе", "чай", "бутерброд", "йогурт",
                     "яйц", "курица", "рис", "гречка", "овсянка", "банан", "яблок"]
    is_food = any(kw in text.lower() for kw in food_keywords)

    if is_food:
        msg = await update.message.reply_text("Считаю калории...")
        result = await ai.analyze_food_text(text, dict(user), today_stats)

        if "error" in result:
            await msg.edit_text(f"Не понял: {result['error']}\nПопробуй описать конкретнее.")
            return

        await db.add_meal(
            update.effective_user.id,
            description=result.get("dish", text),
            calories=result.get("calories", 0),
            protein=result.get("protein", 0),
            carbs=result.get("carbs", 0),
            fat=result.get("fat", 0),
        )

        today_stats = await db.get_today_stats(update.effective_user.id)
        remaining = user["daily_calories_target"] - today_stats["calories"]

        reply = (
            f"🍽 {result.get('dish', text)}\n\n"
            f"🔥 {result['calories']} ккал\n"
            f"🥩 Белок: {result['protein']} г | 🍞 Углеводы: {result['carbs']} г | 🧈 Жиры: {result['fat']} г\n"
        )
        if result.get("comment"):
            reply += f"\n💬 {result['comment']}\n"
        reply += f"\n📊 Итого за день: {today_stats['calories']} ккал | осталось: {remaining} ккал"
        await msg.edit_text(reply)
    else:
        # Coach mode
        response = await ai.coach_response(text, dict(user), today_stats)
        await update.message.reply_text(response)


# ── /weight ─────────────────────────────────────────────────────────

async def cmd_weight(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = await db.get_user(update.effective_user.id)
    if not user:
        await update.message.reply_text("Сначала /start")
        return
    if not ctx.args:
        await update.message.reply_text("Напиши вес: /weight 67.5")
        return
    try:
        w = float(ctx.args[0].replace(",", "."))
    except ValueError:
        await update.message.reply_text("Введи число: /weight 67.5")
        return

    await db.add_weight(update.effective_user.id, w)
    diff = w - user["weight_current"] if user["weight_current"] else 0
    arrow = "⬇️" if diff < 0 else "⬆️" if diff > 0 else "➡️"
    to_goal = w - user["weight_goal"]
    await update.message.reply_text(
        f"Записано: {w} кг {arrow} ({diff:+.1f} кг)\n"
        f"До цели ({user['weight_goal']} кг): {to_goal:.1f} кг"
    )


# ── /activity ───────────────────────────────────────────────────────

async def cmd_activity(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = await db.get_user(update.effective_user.id)
    if not user:
        await update.message.reply_text("Сначала /start")
        return
    if not ctx.args:
        await update.message.reply_text("Опиши: /activity бег 30 минут")
        return

    text = " ".join(ctx.args)
    result = await ai.analyze_activity(text)
    if "error" in result:
        await update.message.reply_text("Не понял. Попробуй: /activity бег 30 минут")
        return

    await db.add_activity(
        update.effective_user.id,
        result.get("activity_type", text),
        result.get("duration_min", 30),
        result.get("calories_burned", 0),
    )
    await update.message.reply_text(
        f"🏃 {result.get('activity_type', text)}\n"
        f"⏱ {result['duration_min']} мин\n"
        f"🔥 -{result['calories_burned']} ккал\n"
        + (f"\n💬 {result['comment']}" if result.get("comment") else "")
    )


# ── /today ──────────────────────────────────────────────────────────

async def cmd_today(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = await db.get_user(update.effective_user.id)
    if not user:
        await update.message.reply_text("Сначала /start")
        return

    stats = await db.get_today_stats(update.effective_user.id)
    cal_target = user["daily_calories_target"]
    prot_target = user["daily_protein_target"]
    remaining = cal_target - stats["calories"] + stats["calories_burned"]

    bar_len = 20
    cal_pct = min(stats["calories"] / cal_target, 1.0) if cal_target else 0
    bar = "█" * int(cal_pct * bar_len) + "░" * (bar_len - int(cal_pct * bar_len))

    await update.message.reply_text(
        f"📊 Сегодня:\n\n"
        f"🔥 Калории: {stats['calories']}/{cal_target} ккал\n"
        f"[{bar}] {cal_pct*100:.0f}%\n\n"
        f"🥩 Белок: {stats['protein']}/{prot_target} г\n"
        f"🍞 Углеводы: {stats['carbs']} г\n"
        f"🧈 Жиры: {stats['fat']} г\n\n"
        f"🍽 Приёмов пищи: {stats['meal_count']}\n"
        f"🏃 Сожжено: {stats['calories_burned']} ккал\n"
        f"💚 Осталось: {remaining} ккал"
    )


# ── /week ───────────────────────────────────────────────────────────

async def cmd_week(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = await db.get_user(update.effective_user.id)
    if not user:
        await update.message.reply_text("Сначала /start")
        return

    stats = await db.get_week_stats(update.effective_user.id)

    if not stats["daily_calories"]:
        await update.message.reply_text("Пока нет данных за неделю. Начни записывать еду!")
        return

    # Build chart
    fig, ax = plt.subplots(figsize=(8, 4))
    days = [datetime.strptime(d[0], "%Y-%m-%d") for d in stats["daily_calories"]]
    cals = [d[1] for d in stats["daily_calories"]]
    ax.bar(days, cals, color="#667eea", alpha=0.8, width=0.6)
    ax.axhline(y=user["daily_calories_target"], color="#ff6b6b", linestyle="--", label=f"Цель: {user['daily_calories_target']}")
    ax.set_ylabel("ккал")
    ax.set_title("Калории за неделю")
    ax.legend()
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%d.%m"))
    fig.tight_layout()

    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=120)
    buf.seek(0)
    plt.close(fig)

    avg_cal = sum(cals) / len(cals)
    text_parts = [f"📊 Неделя:\n\n🔥 Средние калории: {avg_cal:.0f} ккал/день"]

    if stats["weights"]:
        first_w = stats["weights"][0][1]
        last_w = stats["weights"][-1][1]
        diff = last_w - first_w
        text_parts.append(f"⚖️ Вес: {first_w} → {last_w} кг ({diff:+.1f})")

    if stats["activities"]:
        total_burned = sum(a[1] for a in stats["activities"])
        total_min = sum(a[2] for a in stats["activities"])
        text_parts.append(f"🏃 Активность: {total_min} мин, -{total_burned} ккал")

    await update.message.reply_photo(buf, caption="\n".join(text_parts))


# ── /progress ───────────────────────────────────────────────────────

async def cmd_progress(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = await db.get_user(update.effective_user.id)
    if not user:
        await update.message.reply_text("Сначала /start")
        return

    progress = await db.get_progress(update.effective_user.id)
    if not progress:
        await update.message.reply_text("Пока нет данных.")
        return

    u = progress["user"]

    text = f"📈 Прогресс {u['name']}:\n\n"

    if progress["weights"] and len(progress["weights"]) >= 2:
        start_w = progress["weights"][0][0]
        current_w = progress["weights"][-1][0]
        lost = start_w - current_w
        to_goal = current_w - u["weight_goal"]
        text += f"⚖️ Вес: {start_w} → {current_w} кг (сброшено: {lost:+.1f} кг)\n"
        text += f"🎯 До цели ({u['weight_goal']} кг): {to_goal:.1f} кг\n"
        if lost > 0 and to_goal > 0:
            pct = lost / (start_w - u["weight_goal"]) * 100
            text += f"📊 Выполнено: {pct:.0f}%\n"
    text += f"\n🍽 Всего приёмов пищи: {progress['total_meals']}\n"
    text += f"🔥 Средние калории: {progress['avg_calories']} ккал/день\n"
    text += f"🏃 Тренировок: {progress['total_workouts']} ({progress['total_workout_minutes']} мин)\n"

    # Weight chart if enough data
    if len(progress["weights"]) >= 2:
        fig, ax = plt.subplots(figsize=(8, 4))
        dates = [datetime.strptime(w[1], "%Y-%m-%d %H:%M:%S") if " " in w[1]
                 else datetime.strptime(w[1], "%Y-%m-%d") for w in progress["weights"]]
        weights = [w[0] for w in progress["weights"]]
        ax.plot(dates, weights, "o-", color="#667eea", linewidth=2, markersize=6)
        ax.axhline(y=u["weight_goal"], color="#2ecc71", linestyle="--", label=f"Цель: {u['weight_goal']} кг")
        ax.set_ylabel("кг")
        ax.set_title("Динамика веса")
        ax.legend()
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%d.%m"))
        fig.tight_layout()

        buf = io.BytesIO()
        fig.savefig(buf, format="png", dpi=120)
        buf.seek(0)
        plt.close(fig)
        await update.message.reply_photo(buf, caption=text)
    else:
        await update.message.reply_text(text)

    # Ask coach for motivation
    today_stats = await db.get_today_stats(update.effective_user.id)
    motivation = await ai.coach_response(
        "Дай мне мотивирующее сообщение на основе моего прогресса. Коротко, 2-3 предложения.",
        dict(user), today_stats
    )
    await update.message.reply_text(motivation)


# ── /coach ──────────────────────────────────────────────────────────

async def cmd_coach(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = await db.get_user(update.effective_user.id)
    if not user:
        await update.message.reply_text("Сначала /start")
        return
    today_stats = await db.get_today_stats(update.effective_user.id)
    prompt = " ".join(ctx.args) if ctx.args else "Дай мне совет на сегодня. Что мне поесть и как тренироваться?"
    response = await ai.coach_response(prompt, dict(user), today_stats)
    await update.message.reply_text(response)


# ── /goal ───────────────────────────────────────────────────────────

async def cmd_goal(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not ctx.args:
        await update.message.reply_text("Новая цель по весу: /goal 58")
        return
    try:
        new_goal = float(ctx.args[0].replace(",", "."))
    except ValueError:
        await update.message.reply_text("Введи число: /goal 58")
        return
    await db.upsert_user(update.effective_user.id, weight_goal=new_goal)
    await update.message.reply_text(f"Новая цель: {new_goal} кг")


# ── Scheduled reminders ────────────────────────────────────────────

async def evening_reminder(ctx: ContextTypes.DEFAULT_TYPE):
    """Check all users at 20:00 and remind if no meals today."""
    import aiosqlite
    from config import DB_PATH
    async with aiosqlite.connect(DB_PATH) as conn:
        async with conn.execute("SELECT user_id, name, motivation_type FROM users") as cur:
            users = await cur.fetchall()
    for user_id, name, mtype in users:
        stats = await db.get_today_stats(user_id)
        if stats["meal_count"] == 0:
            if mtype == "strict":
                msg = f"Эй, {name}! Ни одной записи за сегодня. Что ты ела? Давай запишем."
            elif mtype == "analytical":
                msg = f"{name}, сегодня 0 записей. Без данных нет прогресса. Запиши хотя бы основные приёмы."
            else:
                msg = f"{name}, привет! Заметила что сегодня нет записей. Ничего страшного — запиши что помнишь, даже примерно."
            try:
                await ctx.bot.send_message(user_id, msg)
            except Exception:
                pass


# ── Main ────────────────────────────────────────────────────────────

def main():
    import asyncio
    asyncio.get_event_loop().run_until_complete(db.init_db())

    app = Application.builder().token(TELEGRAM_TOKEN).build()

    # Onboarding conversation
    conv = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, onboard_name)],
            WEIGHT: [MessageHandler(filters.TEXT & ~filters.COMMAND, onboard_weight)],
            HEIGHT: [MessageHandler(filters.TEXT & ~filters.COMMAND, onboard_height)],
            AGE: [MessageHandler(filters.TEXT & ~filters.COMMAND, onboard_age)],
            GOAL: [MessageHandler(filters.TEXT & ~filters.COMMAND, onboard_goal)],
            MOTIVATION: [MessageHandler(filters.TEXT & ~filters.COMMAND, onboard_motivation)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )
    app.add_handler(conv)

    # Commands
    app.add_handler(CommandHandler("weight", cmd_weight))
    app.add_handler(CommandHandler("activity", cmd_activity))
    app.add_handler(CommandHandler("today", cmd_today))
    app.add_handler(CommandHandler("week", cmd_week))
    app.add_handler(CommandHandler("progress", cmd_progress))
    app.add_handler(CommandHandler("coach", cmd_coach))
    app.add_handler(CommandHandler("goal", cmd_goal))

    # Photo handler
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))

    # Text handler (food or coach)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    # Evening reminder at 20:00
    app.job_queue.run_daily(evening_reminder, time=dtime(hour=20, minute=0))

    log.info("Bot started!")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
