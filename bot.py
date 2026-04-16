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

# Onboarding: single conversational state
ONBOARDING = 0


# ── /start onboarding ──────────────────────────────────────────────

ONBOARD_EXTRACT_PROMPT = """Из сообщений пользователя извлеки данные для профиля.
Верни ТОЛЬКО JSON (без markdown):
{{"name": "имя или null", "weight": число_или_null, "height": число_см_или_null, "age": число_или_null, "goal": число_кг_или_null, "motivation": "supportive/strict/analytical или null", "missing": ["список того что ещё не указано"], "reply": "твой ответ пользователю от лица Олега — попроси недостающее или поприветствуй если всё есть"}}

Правила:
- Извлекай данные из ВСЕХ сообщений в истории, не только последнего
- Если пользователь исправляет ("нет, не 63, а 65") — бери исправлённое значение
- Рост в метрах (1.65) переводи в см (165)
- "имя" — только имя, без "я", "меня зовут" и т.п.
- "motivation": мягкая/поддержка = supportive, жёсткий/строгий = strict, аналитик/цифры = analytical
- Если пользователь не указал мотивацию — по умолчанию "supportive", НЕ спрашивай отдельно
- "missing" — ТОЛЬКО: name, weight, height, age, goal. Motivation не обязательна.
- "reply" — говори от лица Олега (короткий, живой, с характером). Если всё есть — поприветствуй и скажи что готов работать.
- Если можешь получить несколько данных за раз ("я Настя, 28 лет, 63 кг") — бери всё сразу"""


async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = await db.get_user(update.effective_user.id)
    if user:
        today_stats = await db.get_today_stats(update.effective_user.id)
        history = await db.get_chat_history(update.effective_user.id)
        response = await ai.coach_response(
            "Пользователь нажал /start заново. Поприветствуй как старого знакомого, напомни что ты тут и готов помогать.",
            dict(user), today_stats, history
        )
        await update.message.reply_text(response)
        return ConversationHandler.END
    ctx.user_data["onboard_history"] = []
    await update.message.reply_text(
        "Йо! Олег на связи 🤙\n\n"
        "Расскажи о себе — имя, вес, рост, возраст и цель по весу. "
        "Можно всё сразу, можно по частям, как удобно."
    )
    return ONBOARDING

async def onboard_chat(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Single conversational onboarding handler — AI extracts all data from free chat."""
    text = update.message.text.strip()
    history = ctx.user_data.get("onboard_history", [])
    history.append({"role": "user", "content": text})
    ctx.user_data["onboard_history"] = history

    # Build messages for AI extraction
    messages = [{"role": "user", "content": ONBOARD_EXTRACT_PROMPT + "\n\nИстория сообщений:\n" +
                 "\n".join(f"{'Пользователь' if m['role']=='user' else 'Олег'}: {m['content']}" for m in history)}]

    import anthropic as _anthropic
    from config import ANTHROPIC_API_KEY, CLAUDE_MODEL_FAST
    _client = _anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    resp = _client.messages.create(
        model=CLAUDE_MODEL_FAST,
        max_tokens=600,
        messages=messages,
    )

    try:
        data = ai._parse_json(resp.content[0].text)
    except Exception:
        await update.message.reply_text("Прости, не понял. Расскажи имя, вес, рост, возраст и цель по весу.")
        return ONBOARDING

    if "error" in data:
        await update.message.reply_text("Прости, не разобрал. Попробуй ещё раз — имя, вес, рост, возраст и цель.")
        return ONBOARDING

    # Check if we have all required fields
    name = data.get("name")
    weight = data.get("weight")
    height = data.get("height")
    age = data.get("age")
    goal = data.get("goal")
    motivation = data.get("motivation") or "supportive"
    missing = [f for f in ["name", "weight", "height", "age", "goal"]
               if not data.get(f)]

    if missing:
        # Still missing data — reply and continue conversation
        reply = data.get("reply", f"Не хватает: {', '.join(missing)}. Расскажи!")
        history.append({"role": "assistant", "content": reply})
        await update.message.reply_text(reply)
        return ONBOARDING

    # All data collected — save user
    # Convert height from m to cm if needed
    if height < 3:
        height = height * 100

    bmr = 10 * weight + 6.25 * height - 5 * age - 161
    tdee = bmr * 1.4
    cal_target = max(1200, int(tdee - 400))
    protein_target = int(weight * 1.6)

    await db.upsert_user(
        update.effective_user.id,
        name=name,
        weight_current=weight,
        weight_goal=goal,
        height=int(height),
        age=int(age),
        motivation_type=motivation,
        daily_calories_target=cal_target,
        daily_protein_target=protein_target,
    )
    await db.add_weight(update.effective_user.id, weight)

    # Let Oleg greet personally
    user_obj = await db.get_user(update.effective_user.id)
    today_stats = await db.get_today_stats(update.effective_user.id)
    greeting = await ai.coach_response(
        f"Я только что зарегистрировалась. Меня зовут {name}, мне {age}, вешу {weight} кг, хочу {goal} кг. "
        f"Мой план: {cal_target} ккал, {protein_target}г белка в день. "
        f"Поприветствуй меня, расскажи кратко что я могу делать (отправлять фото еды, "
        f"писать что съела, команды /today /week /weight /coach). Будь собой.",
        dict(user_obj), today_stats
    )
    await update.message.reply_text(greeting, reply_markup=ReplyKeyboardRemove())
    return ConversationHandler.END

async def cancel(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Ок, отменено.", reply_markup=ReplyKeyboardRemove())
    return ConversationHandler.END


# ── Food logging (photo) ───────────────────────────────────────────

async def handle_photo(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = await db.get_user(update.effective_user.id)
    if not user:
        await update.message.reply_text(
            "Привет! Я Олег, твой коуч. Давай познакомимся — "
            "расскажи о себе: имя, вес, рост, возраст и цель по весу. "
            "Можно всё сразу, можно по частям 🤙\n\n"
            "Или нажми /start"
        )
        return

    msg = await update.message.reply_text("Секунду, смотрю что тут...")
    photo = update.message.photo[-1]
    file = await ctx.bot.get_file(photo.file_id)
    buf = io.BytesIO()
    await file.download_to_memory(buf)
    photo_bytes = buf.getvalue()

    today_stats = await db.get_today_stats(update.effective_user.id)
    client_context = await db.build_client_context(update.effective_user.id)
    caption = update.message.caption or ""
    result = await ai.analyze_food_photo(photo_bytes, dict(user), today_stats, caption, client_context)

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

    # Compact nutrition line + Oleg's live comment
    nutrition = (
        f"📝 {result.get('dish', 'Блюдо')} — {result['calories']} ккал\n"
        f"Б {result['protein']}г | У {result['carbs']}г | Ж {result['fat']}г\n"
        f"Итого за день: {today_stats['calories']}/{user['daily_calories_target']} ккал | осталось {remaining}\n\n"
    )

    history = await db.get_chat_history(update.effective_user.id)
    comment = await ai.comment_food(result, dict(user), today_stats, history, client_context)

    full_text = nutrition + comment

    # Save to chat history
    await db.add_chat_message(update.effective_user.id, "user", f"[отправила фото еды: {result.get('dish', caption)}]")
    await db.add_chat_message(update.effective_user.id, "assistant", full_text)

    await msg.edit_text(full_text)


# ── Food logging (text) ────────────────────────────────────────────

async def handle_text(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = await db.get_user(update.effective_user.id)
    if not user:
        await update.message.reply_text(
            "Привет! Я Олег, твой коуч. Давай познакомимся — "
            "расскажи о себе: имя, вес, рост, возраст и цель по весу. "
            "Можно всё сразу, можно по частям 🤙\n\n"
            "Или нажми /start"
        )
        return

    text = update.message.text.strip()
    text_lower = text.lower()
    today_stats = await db.get_today_stats(update.effective_user.id)
    client_context = await db.build_client_context(update.effective_user.id)

    # Auto-detect sleep logging
    sleep_keywords = ["спала", "спал", "сон", "проснул", "выспал", "не выспал", "бессонниц", "часов сна"]
    is_sleep = any(kw in text_lower for kw in sleep_keywords)
    if is_sleep:
        # Try to extract hours from text
        import re
        hours_match = re.search(r'(\d+[.,]?\d*)\s*(?:час|ч\.?|hrs?)', text_lower)
        if hours_match:
            hours = float(hours_match.group(1).replace(",", "."))
            quality = "плохо" if any(w in text_lower for w in ["плохо", "не выспал", "бессонниц", "ужасно"]) else \
                      "отлично" if any(w in text_lower for w in ["отлично", "супер", "класс", "выспал"]) else "нормально"
            await db.add_sleep(update.effective_user.id, hours, quality, text)

    # Auto-detect mood
    mood_keywords = ["настроен", "чувствую", "устала", "устал", "бодр", "энерги", "тревог", "стресс",
                     "грустн", "злюсь", "раздраж", "счастлив", "хорошо себя", "плохо себя", "апати"]
    is_mood = any(kw in text_lower for kw in mood_keywords)
    if is_mood:
        mood = "плохое" if any(w in text_lower for w in ["устал", "плохо", "грустн", "тревог", "стресс", "апати", "злюсь", "раздраж"]) else \
               "отличное" if any(w in text_lower for w in ["супер", "отличн", "счастлив", "бодр", "энерги"]) else "нормальное"
        await db.add_mood(update.effective_user.id, mood, note=text)

    # Auto-detect cycle
    cycle_keywords = ["цикл", "месячн", "пмс", "менструац", "день цикла", "критическ", "овуляц"]
    is_cycle = any(kw in text_lower for kw in cycle_keywords)
    if is_cycle:
        import re
        day_match = re.search(r'(\d+)\s*день', text_lower) or re.search(r'день\s*(\d+)', text_lower)
        if day_match:
            day = int(day_match.group(1))
            phase = "менструальная" if day <= 5 else "фолликулярная" if day <= 14 else "лютеиновая"
            await db.add_cycle(update.effective_user.id, day, phase, text)

    # Check if it's a coaching question or food
    food_keywords = ["съел", "съела", "ел", "ела", "пил", "пила", "завтрак", "обед", "ужин",
                     "перекус", "каша", "салат", "суп", "кофе", "чай", "бутерброд", "йогурт",
                     "яйц", "курица", "рис", "гречка", "овсянка", "банан", "яблок"]
    is_food = any(kw in text_lower for kw in food_keywords) and not (is_sleep or is_mood or is_cycle)

    history = await db.get_chat_history(update.effective_user.id)

    if is_food:
        msg = await update.message.reply_text("Записываю...")
        result = await ai.analyze_food_text(text, dict(user), today_stats, client_context)

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

        nutrition = (
            f"📝 {result.get('dish', text)} — {result['calories']} ккал\n"
            f"Б {result['protein']}г | У {result['carbs']}г | Ж {result['fat']}г\n"
            f"Итого за день: {today_stats['calories']}/{user['daily_calories_target']} ккал | осталось {remaining}\n\n"
        )

        comment = await ai.comment_food(result, dict(user), today_stats, history, client_context)
        reply = nutrition + comment

        await db.add_chat_message(update.effective_user.id, "user", text)
        await db.add_chat_message(update.effective_user.id, "assistant", reply)
        await msg.edit_text(reply)
    else:
        # Coach mode with full conversation history + client context
        await db.add_chat_message(update.effective_user.id, "user", text)
        response = await ai.coach_response(text, dict(user), today_stats, history, client_context)
        await db.add_chat_message(update.effective_user.id, "assistant", response)
        await update.message.reply_text(response)


# ── /weight ─────────────────────────────────────────────────────────

async def cmd_weight(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = await db.get_user(update.effective_user.id)
    if not user:
        await update.message.reply_text("Давай сначала познакомимся! Нажми /start")
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
        await update.message.reply_text("Давай сначала познакомимся! Нажми /start")
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
        await update.message.reply_text("Давай сначала познакомимся! Нажми /start")
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
        await update.message.reply_text("Давай сначала познакомимся! Нажми /start")
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
        await update.message.reply_text("Давай сначала познакомимся! Нажми /start")
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
        await update.message.reply_text("Давай сначала познакомимся! Нажми /start")
        return
    today_stats = await db.get_today_stats(update.effective_user.id)
    history = await db.get_chat_history(update.effective_user.id)
    client_context = await db.build_client_context(update.effective_user.id)
    prompt = " ".join(ctx.args) if ctx.args else "Дай мне совет на сегодня. Что мне поесть и как тренироваться?"
    response = await ai.coach_response(prompt, dict(user), today_stats, history, client_context)
    await db.add_chat_message(update.effective_user.id, "user", prompt)
    await db.add_chat_message(update.effective_user.id, "assistant", response)
    await update.message.reply_text(response)


# ── /sleep ──────────────────────────────────────────────────────

async def cmd_sleep(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = await db.get_user(update.effective_user.id)
    if not user:
        await update.message.reply_text("Давай сначала познакомимся! Нажми /start")
        return
    if not ctx.args:
        await update.message.reply_text("Сколько спала: /sleep 7.5\nИли с пометкой: /sleep 6 плохо")
        return
    try:
        hours = float(ctx.args[0].replace(",", "."))
    except ValueError:
        await update.message.reply_text("Введи число часов: /sleep 7.5")
        return
    quality = " ".join(ctx.args[1:]) if len(ctx.args) > 1 else None
    await db.add_sleep(update.effective_user.id, hours, quality)
    today_stats = await db.get_today_stats(update.effective_user.id)
    client_context = await db.build_client_context(update.effective_user.id)
    history = await db.get_chat_history(update.effective_user.id)
    response = await ai.coach_response(
        f"Я спала {hours} часов" + (f", качество: {quality}" if quality else "") + ". Прокомментируй кратко.",
        dict(user), today_stats, history, client_context
    )
    await update.message.reply_text(f"Записано: {hours}ч сна" + (f" ({quality})" if quality else "") + f"\n\n{response}")


# ── /mood ───────────────────────────────────────────────────────

async def cmd_mood(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = await db.get_user(update.effective_user.id)
    if not user:
        await update.message.reply_text("Давай сначала познакомимся! Нажми /start")
        return
    if not ctx.args:
        await update.message.reply_text("Как настроение: /mood отлично\nИли: /mood устала после работы")
        return
    mood_text = " ".join(ctx.args)
    await db.add_mood(update.effective_user.id, mood_text)
    today_stats = await db.get_today_stats(update.effective_user.id)
    client_context = await db.build_client_context(update.effective_user.id)
    history = await db.get_chat_history(update.effective_user.id)
    response = await ai.coach_response(
        f"Моё настроение сейчас: {mood_text}. Прокомментируй как коуч, кратко.",
        dict(user), today_stats, history, client_context
    )
    await update.message.reply_text(response)


# ── /cycle ──────────────────────────────────────────────────────

async def cmd_cycle(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = await db.get_user(update.effective_user.id)
    if not user:
        await update.message.reply_text("Давай сначала познакомимся! Нажми /start")
        return
    if not ctx.args:
        await update.message.reply_text("День цикла: /cycle 14\nИли: /cycle 3 болит живот")
        return
    try:
        day = int(ctx.args[0])
    except ValueError:
        await update.message.reply_text("Введи номер дня: /cycle 14")
        return
    phase = "менструальная" if day <= 5 else "фолликулярная" if day <= 14 else "лютеиновая"
    note = " ".join(ctx.args[1:]) if len(ctx.args) > 1 else None
    await db.add_cycle(update.effective_user.id, day, phase, note)
    today_stats = await db.get_today_stats(update.effective_user.id)
    client_context = await db.build_client_context(update.effective_user.id)
    history = await db.get_chat_history(update.effective_user.id)
    response = await ai.coach_response(
        f"У меня {day} день цикла ({phase} фаза)" + (f", {note}" if note else "") +
        ". Дай рекомендации по тренировкам и питанию с учётом фазы цикла.",
        dict(user), today_stats, history, client_context
    )
    await update.message.reply_text(f"📅 День {day} ({phase} фаза)\n\n{response}")


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
    from config import DB_PATH
    log.info(f"DB_PATH = {DB_PATH}")
    log.info(f"/data exists: {__import__('os').path.isdir('/data')}")
    asyncio.get_event_loop().run_until_complete(db.init_db())

    app = Application.builder().token(TELEGRAM_TOKEN).build()

    # Onboarding conversation — single free-form state
    conv = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            ONBOARDING: [MessageHandler(filters.TEXT & ~filters.COMMAND, onboard_chat)],
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
    app.add_handler(CommandHandler("sleep", cmd_sleep))
    app.add_handler(CommandHandler("mood", cmd_mood))
    app.add_handler(CommandHandler("cycle", cmd_cycle))

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
