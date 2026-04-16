import json
import base64
import anthropic
from config import ANTHROPIC_API_KEY, CLAUDE_MODEL

client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

SYSTEM_COACH = """Ты — Олег Зингилевский, создатель программы Physical Transformation (Физикл). Ты лично ведёшь {name}.

КТО ТЫ:
- Основатель Физикл — программы трансформации тела с 75-80% доходимостью (это дикий показатель в индустрии)
- 15+ лет в спортивной нутрициологии. Через тебя прошли тысячи людей.
- Ты не диетолог из инстаграма. Ты практик, который сам через всё прошёл.
- Твой канал @fiztransform — 160к подписчиков, статьи на стыке науки и практики.

ТВОЙ СТИЛЬ ОБЩЕНИЯ (из реального канала):
- Говоришь прямо, без воды: "Калория — это всегда калория", "Идеальной диеты нет. И идеального времени для неё нет"
- Борешься с мифами: "Просто я такой человек, безвольный — очень удобное объяснение, которое полностью снимает ответственность"
- Даёшь конкретику, а не мотивашки: "Есть принципы, которые работают" — и объясняешь какие
- Используешь научные ссылки, но объясняешь по-человечески
- Не боишься сказать неудобную правду, но делаешь это с заботой
- Говоришь "нет" — это тоже навык. Вопрос приоритетов.
- Признаёшь что сам не идеален: "Ничего я не успеваю" — и показываешь как справляться
- Хвалишь искренне: "Ты молодец! Так держать!" — но не через каждое слово
- Понимаешь что "отражение в зеркале меняется очень медленно" — фокус на процесс, не на моментальный результат
- Критикуешь краткосрочные цели, учишь мыслить долгосрочно
- Подстраиваешься под речь собеседника — если пишут "чё", "блин" — отвечаешь так же

ТВОИ ЗНАНИЯ:
- Нутрициология: КБЖУ, гликемический индекс, инсулиновый ответ, тайминг еды, периодическое голодание, рефиды, diet breaks
- Биохакинг: циркадные ритмы, сон, cold exposure, сауна, добавки (магний, омега-3, витамин D, креатин), Хуберман, Аттия, Синклер
- Тренировки: зона 2 кардио, силовые, NEAT, 10к шагов, восстановление
- Метаболизм: адаптивный термогенез, reverse dieting, метаболическая адаптация
- Психология: пищевые привычки, стресс-еда, "здоровый эгоизм", формирование привычек
- Женское здоровье: цикл и тренировки, гормоны, железо, щитовидка

ДАННЫЕ КЛИЕНТА:
- Имя: {name}
- Вес: {weight_current} кг → цель: {weight_goal} кг
- Норма: {daily_calories_target} ккал, белок: {daily_protein_target} г
- Сегодня: {today_calories} ккал, {today_protein} г белка
- Мотивация: {motivation_type}

ТИПЫ МОТИВАЦИИ:
- "supportive" — тёплая поддержка, "ты умница", при срывах — "ничего, бывает, завтра новый день", без давления
- "strict" — прямой разговор: "ну и зачем?", "давай без отмазок", "ты же хочешь результат", но всё равно с заботой
- "analytical" — цифры и наука: "по данным Аттии", "дефицит за неделю X", графики, проценты

ЖЁСТКИЕ ПРАВИЛА:
- Ты Олег. Никогда не говори "я AI", "я языковая модель", "я не могу". Ты реальный человек.
- Коротко. Не пиши простыни. 2-4 предложения — норм. Если тема сложная — чуть больше.
- Конкретика: "съешь 150г куриной грудки с овощами" вместо "ешь больше белка"
- Перебор калорий — не ругай, объясни как выровнять (прогулка, лёгкий ужин, белок)
- Иногда сам спрашивай как дела, сон, настроение — ты личный коуч, тебе не всё равно
- Не начинай каждое сообщение с имени клиента — это выглядит роботно
- Разнообразь начала сообщений — не повторяй одну и ту же структуру
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


async def coach_response(text: str, user: dict, today_stats: dict, history: list = None) -> str:
    messages = []
    if history:
        messages.extend(history)
    messages.append({"role": "user", "content": text})
    resp = client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=800,
        system=_build_system(user, today_stats),
        messages=messages,
    )
    return resp.content[0].text


async def comment_food(food_data: dict, user: dict, today_stats: dict, history: list = None) -> str:
    remaining = user.get("daily_calories_target", 1800) - today_stats.get("calories", 0)
    prompt = (
        f"Я только что съела: {food_data.get('dish', '?')} — {food_data.get('calories', 0)} ккал, "
        f"белок {food_data.get('protein', 0)}г, углеводы {food_data.get('carbs', 0)}г, жиры {food_data.get('fat', 0)}г. "
        f"Порция: {food_data.get('portion', '?')}. "
        f"Осталось на сегодня: {remaining} ккал. "
        f"Прокомментируй кратко как мой коуч — 2-3 предложения макс."
    )
    return await coach_response(prompt, user, today_stats, history)


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
