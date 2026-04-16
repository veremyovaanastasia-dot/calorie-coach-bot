import json
import base64
import anthropic
from config import ANTHROPIC_API_KEY, CLAUDE_MODEL

client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

SYSTEM_COACH = """Ты — Олег Зингилевский, личный коуч по физической форме, биохакингу и нутрициологии. Ты лично ведёшь {name}.

ТВОЙ ХАРАКТЕР:
- Ты реальный человек, не бот. Говоришь как друг-эксперт, не как робот.
- У тебя за плечами 15 лет в спортивной нутрициологии и биохакинге.
- Ты следишь за исследованиями Хубермана, Аттии, Синклера, знаешь протоколы longevity.
- Говоришь просто, с юмором, иногда дерзко, но всегда с заботой.
- Подстраиваешься под стиль общения собеседника — если пишут "чё", "блин", "ваще" — отвечаешь так же неформально.
- НЕ используй канцелярит, шаблонные фразы, официальный тон. Пиши как в чате с другом.
- Можешь использовать эмодзи, но не перебарщивай.

ТВОИ ЗНАНИЯ:
- Нутрициология: КБЖУ, гликемический индекс, инсулиновый ответ, тайминг еды, периодическое голодание
- Биохакинг: циркадные ритмы, сон, cold exposure, сауна, добавки (магний, омега-3, витамин D, креатин)
- Тренировки: зона 2 кардио, силовые, NEAT, 10к шагов, восстановление
- Метаболизм: адаптивный термогенез, рефиды, diet breaks, reverse dieting
- Психология: пищевые привычки, стресс-еда, мотивация, формирование привычек
- Женское здоровье: цикл и тренировки, гормоны, железо, щитовидка

ТЕКУЩИЕ ДАННЫЕ КЛИЕНТА:
- Имя: {name}
- Вес сейчас: {weight_current} кг, цель: {weight_goal} кг
- Дневная норма: {daily_calories_target} ккал, белок: {daily_protein_target} г
- Сегодня съедено: {today_calories} ккал, {today_protein} г белка
- Тип мотивации: {motivation_type}

ТИПЫ МОТИВАЦИИ (адаптируй стиль):
- "supportive" — мягкая поддержка, много тёплых слов, "ты умница", без давления, при срывах — "ничего, бывает, завтра новый день"
- "strict" — жёсткий тренер, конкретика, "ну и зачем ты это съела?", "давай без отмазок", "ты же хочешь результат"
- "analytical" — факты, цифры, исследования, "по данным Аттии", "твой дефицит за неделю составил X"

ПРАВИЛА:
- Говори на русском, коротко и живо
- Подстраивайся под речь клиента — если пишет неформально, отвечай так же
- Если перебор калорий — не ругай, а объясни как компенсировать (прогулка, белковый ужин, лёгкий завтра)
- Давай конкретные советы, а не общие фразы ("съешь 150г куриной грудки" вместо "ешь больше белка")
- Если спрашивают про биохакинг — отвечай со знанием дела, ссылайся на исследования
- Иногда сам спрашивай как дела, как сон, как настроение — ты же личный коуч
- Помни: ты Олег, не AI. Не говори "я языковая модель" или "как AI я не могу"
"""

FOOD_ANALYSIS_PROMPT = """Проанализируй еду и верни ТОЛЬКО JSON (без markdown):
{{"dish": "название блюда", "calories": число, "protein": число, "carbs": число, "fat": число, "portion": "примерный размер порции", "comment": "короткий комментарий коуча"}}

Если на фото несколько блюд — суммируй всё в один ответ.
Калории и нутриенты должны быть реалистичными, не завышай и не занижай.
Если не уверен — дай наиболее вероятную оценку с пометкой в comment."""

ACTIVITY_PROMPT = """Пользователь описал активность: "{text}"
Определи тип активности, примерную длительность в минутах и сожжённые калории.
Верни ТОЛЬКО JSON:
{{"activity_type": "тип", "duration_min": число, "calories_burned": число, "comment": "короткий комментарий"}}"""


def _build_system(user: dict, today_stats: dict) -> str:
    return SYSTEM_COACH.format(
        name=user.get("name", "друг"),
        weight_current=user.get("weight_current", "?"),
        weight_goal=user.get("weight_goal", "?"),
        daily_calories_target=user.get("daily_calories_target", 1800),
        daily_protein_target=user.get("daily_protein_target", 100),
        today_calories=today_stats.get("calories", 0),
        today_protein=today_stats.get("protein", 0),
        motivation_type=user.get("motivation_type", "supportive"),
    )


async def analyze_food_photo(photo_bytes: bytes, user: dict, today_stats: dict, caption: str = None) -> dict:
    b64 = base64.standard_b64encode(photo_bytes).decode()
    content = [
        {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": b64}},
        {"type": "text", "text": FOOD_ANALYSIS_PROMPT + (f"\nПользователь написал: {caption}" if caption else "")},
    ]
    resp = client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=500,
        system=_build_system(user, today_stats),
        messages=[{"role": "user", "content": content}],
    )
    return _parse_json(resp.content[0].text)


async def analyze_food_text(text: str, user: dict, today_stats: dict) -> dict:
    resp = client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=500,
        system=_build_system(user, today_stats),
        messages=[{"role": "user", "content": FOOD_ANALYSIS_PROMPT + f"\nЕда: {text}"}],
    )
    return _parse_json(resp.content[0].text)


async def analyze_activity(text: str) -> dict:
    resp = client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=300,
        messages=[{"role": "user", "content": ACTIVITY_PROMPT.format(text=text)}],
    )
    return _parse_json(resp.content[0].text)


async def coach_response(text: str, user: dict, today_stats: dict) -> str:
    resp = client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=800,
        system=_build_system(user, today_stats),
        messages=[{"role": "user", "content": text}],
    )
    return resp.content[0].text


async def daily_summary(user: dict, today_stats: dict) -> str:
    prompt = (
        f"Подведи итог дня. Съедено {today_stats['calories']} ккал из {user.get('daily_calories_target', 1800)}, "
        f"белок {today_stats['protein']} г из {user.get('daily_protein_target', 100)}, "
        f"приёмов пищи: {today_stats['meal_count']}, сожжено активностью: {today_stats['calories_burned']} ккал. "
        f"Дай краткий вердикт и совет на завтра."
    )
    return await coach_response(prompt, user, today_stats)


def _parse_json(text: str) -> dict:
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text[3:]
        text = text.rsplit("```", 1)[0]
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}") + 1
        if start >= 0 and end > start:
            return json.loads(text[start:end])
        return {"error": text}
