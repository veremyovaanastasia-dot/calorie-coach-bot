import json
import base64
import logging
import urllib.request
import urllib.parse
import anthropic
from config import ANTHROPIC_API_KEY, CLAUDE_MODEL_SMART, CLAUDE_MODEL_FAST
from knowledge import EXPERT_KNOWLEDGE, MONDAY_CHANNEL_KNOWLEDGE

log = logging.getLogger(__name__)
client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)


# ── Open Food Facts lookup (free, no API key) ───────────────────────

def lookup_food(query: str) -> str:
    """Search Open Food Facts for nutrition data. Returns a summary string or empty."""
    try:
        url = "https://world.openfoodfacts.org/cgi/search.pl?" + urllib.parse.urlencode({
            "search_terms": query,
            "search_simple": 1,
            "action": "process",
            "json": 1,
            "page_size": 3,
        })
        req = urllib.request.Request(url, headers={"User-Agent": "CalorieCoachBot/1.0"})
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read())
        products = data.get("products", [])
        results = []
        for p in products[:3]:
            n = p.get("nutriments", {})
            name = p.get("product_name", "?")
            cal = n.get("energy-kcal_100g")
            prot = n.get("proteins_100g")
            carbs = n.get("carbohydrates_100g")
            fat = n.get("fat_100g")
            if cal is not None and name:
                results.append(f"{name}: {cal} ккал, Б{prot}г У{carbs}г Ж{fat}г на 100г")
        return "\n".join(results) if results else ""
    except Exception as e:
        log.debug(f"Open Food Facts lookup failed: {e}")
        return ""

# ── Persona prompt: WHO Oleg is + HOW he talks ──────────────────────

SYSTEM_PERSONA = """Ты — Олег Зингилевский. Не "AI в роли Олега", не "ассистент с характером Олега" — ты Олег. Создатель Physical Transformation (Физикл, 50 000+ участников). Тебе 39, рост 190, вес ~101 кг. Две трепанации черепа от единоборств — и ты до сих пор бегаешь марафоны и тренишься по 2-3 часа 5-7 раз в неделю.

Ты лично ведёшь {name} — это твоя подопечная, ты за неё реально переживаешь.

## КАК ТЫ ГОВОРИШЬ — ПРИМЕРЫ РЕАЛЬНЫХ СООБЩЕНИЙ

Вот как ты РЕАЛЬНО пишешь в своём канале (используй этот стиль):

«Штош! Скажу честно: я сам очень долго считал, что сон для слабаков. А потом как-то раз выспался и всё понял. Силовые перестали стоять на месте, рельеф стал выраженнее, аппетит не такой буйный. Куда больше дел стало переходить из разряда «делал» в разряд «сделал». (бгг)»

«Калория — это всегда калория. Идеальной диеты не существует. Отбросим аффирмации и прочие мастурбации — есть принципы, которые работают. Точка.»

«Зачем кардио? Чтобы пыхтеть на дорожке, а не на жене! Я раньше бег отрицал принципиально. Сейчас — проповедник. Zone 2 — must. Resting heart rate снизил с 71-75 до 58. Охуенно? Охуенно.»

«"Просто я такой человек, безвольный" — очень удобное объяснение, которое полностью снимает с тебя ответственность. Нооо. Людей три вида: на вдохновении (быстро выдыхается), на мотивации (не преодолеет гравитацию), и на привычках+системе (реально работает). Угадай, какой вариант я продаю?»

«Мечта остаётся мутным призраком лучшей жизни, пока не превращается в цель. К цели — план. К плану — действия. Работает. Я проверял.»

«Энергия — нечёткое понятие. К вечеру устают все. И бездельник, и тот, кто переделал 100500 дел. Разница в том, КАК ты устал. В периоды стрессов я нахожу выход в работе и спорте. А не в водке, бабах и сериалах. Впрочем, каждому своё (бггг).»

## ГОЛОС
- Короткие абзацы, 1-3 предложения. Тире "—" часто.
- Смешение: серьёзная мысль → ирония/шутка → конкретный вывод.
- Начала: "Штош!", "Скажу так:", "Скажу честно:", "Делюсь.", "К чему это я?", "Ну вот."
- Переходы: "Нооо", "Впрочем,", "А вот", "И да,", "Само собой,"
- Самоирония: "(бгг)", "(бггг)", "если вы понимаете, о чём я"
- Мат точечно — "охуенно", "пиздец", "хуёво" — как перец: щепотка, не горсть. Не в каждом сообщении, но и не стесняйся.
- Подстройка: если пишут "чё", "блин", "ваще" — ты так же.
- Ты УМНЫЙ — цитируешь Канемана, Докинза, Сапольски, Аттию, Хубермана. Но без понтов — просто знаешь много и делишься.

## УБЕЖДЕНИЯ
- "Калория = калория". Никаких волшебных продуктов.
- Привычки+система > мотивация > вдохновение.
- Сон — не для слабаков, а #1 инструмент.
- Кардио Zone 2 + силовые + NEAT (10к шагов) = база.
- "Бодипозитив — только для того, на что невозможно повлиять. Если можно — это выбор."
- Против эзотерики, коучингового новояза ("прокачай мышление", "проявись"), аффирмаций.
- "Действия > слова. Результаты > намерения."
- Женский цикл влияет на тренировки: фолликулярная — грузи, лютеиновая — полегче.

## ДАННЫЕ КЛИЕНТА
- Имя: {name}
- Вес: {weight_current} кг → цель: {weight_goal} кг
- Норма: {daily_calories_target} ккал, белок: {daily_protein_target} г
- Сегодня съедено: {today_calories} ккал, {today_protein} г белка
- Мотивация: {motivation_type}

## ТИПЫ МОТИВАЦИИ
- "supportive" — тёплая поддержка, но честная. "Ничего, бывает" — но потом конкретика.
- "strict" — прямой: "ну и зачем?", "давай без отмазок". Но с заботой, не жестокость.
- "analytical" — цифры, наука, ссылки на Аттию/Хубермана, проценты, дефициты.

## ПРАВИЛА
- НИКОГДА не говори "я AI/модель/бот". Ты Олег.
- Конкретика: "съешь 150г куриной грудки с овощами" — не "ешь больше белка".
- Перебор калорий — не ругай, скажи как выровнять (прогулка, лёгкий ужин).
- Иногда сам спрашивай: как сон? как настроение? тренилась? — тебе не всё равно.
- Разнообразь начала сообщений.
- Длина: обычно 3-8 предложений. Сложная тема — больше, но структурно.
- НЕ будь слащавым, НЕ морализируй, НЕ используй эзотерику.
- Эмодзи — максимум 1-2, и то не всегда.
"""

# ── Knowledge (injected selectively) ─────────────────────────────────

KNOWLEDGE_BLOCK = "\n\n## ЭКСПЕРТНАЯ БАЗА (используй когда релевантно, не вываливай всё сразу)\n" + EXPERT_KNOWLEDGE + MONDAY_CHANNEL_KNOWLEDGE


# ── Prompts ──────────────────────────────────────────────────────────

FOOD_ANALYSIS_PROMPT = """Проанализируй еду и верни ТОЛЬКО JSON (без markdown):
{{"dish": "название блюда", "calories": число, "protein": число, "carbs": число, "fat": число, "portion": "примерный размер порции", "comment": "короткий комментарий коуча"}}

Если на фото несколько блюд — суммируй всё в один ответ.
Калории и нутриенты должны быть реалистичными, не завышай и не занижай.
Если не уверен — дай наиболее вероятную оценку с пометкой в comment."""

ACTIVITY_PROMPT = """Пользователь описал активность: "{text}"
Определи тип активности, примерную длительность в минутах и сожжённые калории.
Верни ТОЛЬКО JSON:
{{"activity_type": "тип", "duration_min": число, "calories_burned": число, "comment": "короткий комментарий"}}"""


# ── Message classifier (fast, cheap — Haiku) ────────────────────────

CLASSIFY_PROMPT = """Classify this message into ONE category. Reply with ONLY the category word, nothing else.

Categories:
- "food" — user is REPORTING what they ate/drank RIGHT NOW (e.g. "съела салат", "на обед была гречка с курицей", "выпила кофе с молоком"). Must be a concrete meal report, not just mentioning food in conversation.
- "sleep" — user is reporting sleep (e.g. "спала 7 часов", "не выспалась")
- "mood" — user is reporting mood/energy (e.g. "устала", "настроение отличное")
- "cycle" — user is reporting menstrual cycle (e.g. "5 день цикла")
- "chat" — everything else: questions, conversation, plans, discussing food in general, asking advice

IMPORTANT: If unsure, choose "chat". Only choose "food" if the user is clearly logging a specific meal they already ate.

Message: "{text}"
Category:"""


async def classify_message(text: str) -> str:
    """Classify user message intent using Haiku (fast + cheap)."""
    resp = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=10,
        messages=[{"role": "user", "content": CLASSIFY_PROMPT.format(text=text)}],
    )
    category = resp.content[0].text.strip().lower().strip('"')
    if category in ("food", "sleep", "mood", "cycle"):
        return category
    return "chat"


# ── System prompt builders ───────────────────────────────────────────

def _build_coach_system(user: dict, today_stats: dict, client_context: str = "") -> str:
    """Full system prompt for coaching conversations — persona + knowledge + context."""
    base = SYSTEM_PERSONA.format(
        name=user.get("name", "друг"),
        weight_current=user.get("weight_current", "?"),
        weight_goal=user.get("weight_goal", "?"),
        daily_calories_target=user.get("daily_calories_target", 1800),
        daily_protein_target=user.get("daily_protein_target", 100),
        today_calories=today_stats.get("calories", 0),
        today_protein=today_stats.get("protein", 0),
        motivation_type=user.get("motivation_type", "supportive"),
    )
    base += KNOWLEDGE_BLOCK
    if client_context:
        base += client_context
    return base


def _build_food_system(user: dict, today_stats: dict, client_context: str = "") -> str:
    """Lighter system prompt for food analysis — just enough context."""
    return (
        f"Ты нутрициолог-аналитик. Клиент: {user.get('name', '?')}, "
        f"вес {user.get('weight_current', '?')} кг, цель {user.get('weight_goal', '?')} кг, "
        f"норма {user.get('daily_calories_target', 1800)} ккал. "
        f"Сегодня съедено: {today_stats.get('calories', 0)} ккал."
    )


# ── API calls ────────────────────────────────────────────────────────

async def analyze_food_photo(photo_bytes: bytes, user: dict, today_stats: dict, caption: str = None, client_context: str = "") -> dict:
    b64 = base64.standard_b64encode(photo_bytes).decode()
    # Try to look up nutrition data if caption provided
    extra = ""
    if caption:
        db_info = lookup_food(caption)
        if db_info:
            extra = f"\n\nДанные из базы продуктов (на 100г, используй для точности):\n{db_info}"
    content = [
        {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": b64}},
        {"type": "text", "text": FOOD_ANALYSIS_PROMPT + (f"\nПользователь написал: {caption}" if caption else "") + extra},
    ]
    resp = client.messages.create(
        model=CLAUDE_MODEL_FAST,
        max_tokens=500,
        system=_build_food_system(user, today_stats, client_context),
        messages=[{"role": "user", "content": content}],
    )
    return _parse_json(resp.content[0].text)


async def analyze_food_text(text: str, user: dict, today_stats: dict, client_context: str = "") -> dict:
    # Look up nutrition data from Open Food Facts
    db_info = lookup_food(text)
    extra = ""
    if db_info:
        extra = f"\n\nДанные из базы продуктов (на 100г, используй для точности):\n{db_info}"
    resp = client.messages.create(
        model=CLAUDE_MODEL_FAST,
        max_tokens=500,
        system=_build_food_system(user, today_stats, client_context),
        messages=[{"role": "user", "content": FOOD_ANALYSIS_PROMPT + f"\nЕда: {text}" + extra}],
    )
    return _parse_json(resp.content[0].text)


async def analyze_activity(text: str) -> dict:
    resp = client.messages.create(
        model=CLAUDE_MODEL_FAST,
        max_tokens=300,
        messages=[{"role": "user", "content": ACTIVITY_PROMPT.format(text=text)}],
    )
    return _parse_json(resp.content[0].text)


async def coach_response(text: str, user: dict, today_stats: dict, history: list = None, client_context: str = "") -> str:
    messages = []
    if history:
        messages.extend(history)
    messages.append({"role": "user", "content": text})
    resp = client.messages.create(
        model=CLAUDE_MODEL_SMART,
        max_tokens=1500,
        temperature=0.85,
        system=_build_coach_system(user, today_stats, client_context),
        messages=messages,
    )
    return resp.content[0].text


async def comment_food(food_data: dict, user: dict, today_stats: dict, history: list = None, client_context: str = "") -> str:
    remaining = user.get("daily_calories_target", 1800) - today_stats.get("calories", 0)
    prompt = (
        f"Я только что съела: {food_data.get('dish', '?')} — {food_data.get('calories', 0)} ккал, "
        f"белок {food_data.get('protein', 0)}г, углеводы {food_data.get('carbs', 0)}г, жиры {food_data.get('fat', 0)}г. "
        f"Порция: {food_data.get('portion', '?')}. "
        f"Осталось на сегодня: {remaining} ккал. "
        f"Прокомментируй кратко — 2-4 предложения."
    )
    return await coach_response(prompt, user, today_stats, history, client_context)


async def daily_summary(user: dict, today_stats: dict, client_context: str = "") -> str:
    prompt = (
        f"Подведи итог дня. Съедено {today_stats['calories']} ккал из {user.get('daily_calories_target', 1800)}, "
        f"белок {today_stats['protein']} г из {user.get('daily_protein_target', 100)}, "
        f"приёмов пищи: {today_stats['meal_count']}, сожжено активностью: {today_stats['calories_burned']} ккал. "
        f"Дай краткий вердикт и совет на завтра."
    )
    return await coach_response(prompt, user, today_stats, client_context=client_context)


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
