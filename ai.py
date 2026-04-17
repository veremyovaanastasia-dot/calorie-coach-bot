import json
import base64
import logging
import urllib.request
import urllib.parse
import anthropic
from config import ANTHROPIC_API_KEY, CLAUDE_MODEL_SMART, CLAUDE_MODEL_FAST
from knowledge import EXPERT_KNOWLEDGE, MONDAY_CHANNEL_KNOWLEDGE, PHYSICAL_NUTRITION_NORMS, COACHING_METHODOLOGY

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

KNOWLEDGE_BLOCK = "\n\n## НОРМАТИВЫ ФИЗИКЛА (используй АКТИВНО — это твоя программа, напоминай клиенту о нормах)\n" + PHYSICAL_NUTRITION_NORMS + "\n\n## КОУЧИНГ ПО ЗАВИСИМОСТИ ОТ СЛАДКОГО И РПП (применяй АКТИВНО — это твоя методология)\n" + COACHING_METHODOLOGY + "\n\n## ЭКСПЕРТНАЯ БАЗА (используй когда релевантно, не вываливай всё сразу)\n" + EXPERT_KNOWLEDGE + MONDAY_CHANNEL_KNOWLEDGE


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
- "correction" — user is CORRECTING a previous food entry (e.g. "нет, не яичница, а салат", "это было неправильно, я ела...", "ты перепутал, у меня было...", "не X а Y"). They mention wrong food AND correct food.
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
    if category in ("food", "correction", "sleep", "mood", "cycle"):
        return category
    return "chat"


# ── Coaching trigger detection ────────────────────────────────────────

def _detect_coaching_triggers(client_context: str, today_stats: dict, user: dict) -> str:
    """Analyze client data and return coaching hints for the AI."""
    if not client_context:
        return ""
    hints = []
    ctx_lower = client_context.lower()

    # NOTE: do NOT flag sweets in food log — only flag if client explicitly asks for help
    # Sweet pattern detection removed: logging chocolate is just logging, not a cry for help

    # Bad mood
    if any(w in ctx_lower for w in ["плохое", "грустн", "стресс", "тревог", "устал", "апати", "раздраж"]):
        hints.append("ПАТТЕРН: плохое настроение → спроси про эмоциональное переедание, предложи HALT check")

    # Poor sleep
    if "сон" in ctx_lower or "спал" in ctx_lower:
        import re
        sleep_match = re.search(r'(\d+[.,]?\d*)\s*ч', ctx_lower)
        if sleep_match:
            hours = float(sleep_match.group(1).replace(",", "."))
            if hours < 6:
                hints.append(f"ПАТТЕРН: сон {hours}ч (мало!) → недосып = +28% тяга к сладкому (грелин↑, лептин↓)")

    # Luteal phase
    if "лютеиновая" in ctx_lower:
        hints.append("ПАТТЕРН: лютеиновая фаза → прогестерон↓ серотонин↓ → мозг просит сахар. Это НОРМАЛЬНО, предупреди клиента")

    # Low protein
    prot_target = user.get("daily_protein_target", 100)
    prot_eaten = today_stats.get("protein", 0)
    if today_stats.get("meal_count", 0) >= 2 and prot_eaten < prot_target * 0.4:
        hints.append(f"ПАТТЕРН: мало белка ({prot_eaten}г из {prot_target}г) → мало сытости = импульсивные перекусы. Напомни добавить белок")

    # Skipped meals — only mention gently, don't interrogate
    # (evening checkin handles this separately)

    if not hints:
        return ""
    return "\n\n## КОУЧИНГОВЫЕ ТРИГГЕРЫ (действуй!)\n" + "\n".join(f"⚠️ {h}" for h in hints)


# ── System prompt builders ───────────────────────────────────────────

def _build_coach_system(user: dict, today_stats: dict, client_context: str = "", today_meals: list = None) -> list:
    """Full system prompt with caching — static part cached, dynamic part fresh."""
    # Static part: persona template + knowledge (same for all users, cacheable)
    static = SYSTEM_PERSONA.split("## ДАННЫЕ КЛИЕНТА")[0] + KNOWLEDGE_BLOCK

    # Format today's meal list
    meals_str = ""
    if today_meals:
        meal_lines = []
        for m in today_meals:
            meal_lines.append(f"  • {m['description']} — {m['calories']} ккал (Б{m['protein']}г У{m['carbs']}г Ж{m['fat']}г)")
        meals_str = "\n" + "\n".join(meal_lines)

    # Dynamic part: client data + today stats + historical context
    dynamic = f"""## ДАННЫЕ КЛИЕНТА
- Имя: {user.get("name", "друг")}
- Вес: {user.get("weight_current", "?")} кг → цель: {user.get("weight_goal", "?")} кг
- Норма: {user.get("daily_calories_target", 1800)} ккал, белок: {user.get("daily_protein_target", 100)} г
- Сегодня съедено: {today_stats.get("calories", 0)} ккал, {today_stats.get("protein", 0)} г белка ({today_stats.get("meal_count", 0)} приёмов)
- Мотивация: {user.get("motivation_type", "supportive")}
- Сегодняшние приёмы пищи:{meals_str if meals_str else " пока нет"}

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

## ПОЗИТИВНОЕ ПОДКРЕПЛЕНИЕ
Замечай хорошее — но ТОЛЬКО когда реально есть за что. Без натяжки, без дежурных "молодец".
- Хвали через ФАКТ, не через оценку: "80г белка к обеду — серьёзно" лучше чем "молодец!"
- Не хвали за каждую запись еды — это быстро обесценивается
- Если реально крутой выбор (рыба, овощи, хороший баланс) — отметь, но вскользь, одной фразой
- Если прогресс виден в цифрах — покажи цифру: "третий день в дефиците" > "ты на верном пути!"
- НЕ ТЯНИ похвалу за уши. Если нечего отметить — просто прокомментируй нейтрально.
- Избегай банальщины: "горжусь тобой", "так держать", "ты умничка". Это звучит как бот, а не как Олег.

## ВАЖНО: ПОДСЧЁТ КАЛОРИЙ И ЕДА ЗА ДЕНЬ
- ЕДИНСТВЕННЫЙ ИСТОЧНИК ПРАВДЫ о сегодняшней еде — это "Сегодняшние приёмы пищи" в ДАННЫХ КЛИЕНТА выше.
- Если спрашивают "что я ела сегодня" / "проанализируй день" — бери ТОЛЬКО из этого списка. НЕ из чата.
- Цифры калорий/белка/углеводов — ТОЛЬКО из "ДАННЫЕ КЛИЕНТА". ТОЧКА.
- В истории чата могут быть сообщения за прошлые дни (помечены датой [ГГГГ-ММ-ДД]) — это СТАРЫЕ данные, ИГНОРИРУЙ их при подсчётах.
- Каждый день подсчёт начинается с нуля.

## КОУЧИНГ ПО СЛАДКОМУ И ПЕРЕЕДАНИЮ — ВАЖНЫЕ ГРАНИЦЫ

ГЛАВНОЕ ПРАВИЛО: если клиент ПРОСТО ЗАПИСЫВАЕТ ЕДУ (даже шоколад, торт, конфеты) — это ПРОСТО ЗАПИСЬ. Прокомментируй нейтрально-позитивно как любую другую еду. НЕ НАДО:
- Указывать на "паттерн"
- Спрашивать "что случилось?"
- Проводить HALT check
- Говорить "два шоколада за день — это уже..."
- Превращать запись еды в интервенцию
Шоколадка — это просто шоколадка. Записала — молодец что записала. Точка.

КОУЧИНГ ВКЛЮЧАЕТСЯ ТОЛЬКО КОГДА КЛИЕНТ САМ:
- Просит помощи: "помоги не сорваться", "что делать с тягой"
- Жалуется на срыв: "опять переела", "не могу остановиться", "сорвалась"
- Выражает вину: "я ужасная", "зачем я это съела", "день пропал"
- Прямо спрашивает: "почему меня тянет на сладкое?"

ТОГДА (и только тогда) используй техники из методологии:
→ Urge surfing, HALT check, chain analysis — мягко, без допроса
→ "Срыв — это данные, не провал"
→ Когнитивная реструктуризация если себя ругает
→ НЕ ругай, НЕ стыди, НЕ читай лекции
"""
    if client_context:
        dynamic += client_context

    # Inject coaching triggers based on client data
    coaching_hints = _detect_coaching_triggers(client_context, today_stats, user)
    if coaching_hints:
        dynamic += coaching_hints

    return [
        {"type": "text", "text": static, "cache_control": {"type": "ephemeral"}},
        {"type": "text", "text": dynamic},
    ]


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


async def coach_response(text: str, user: dict, today_stats: dict, history: list = None, client_context: str = "", today_meals: list = None) -> str:
    messages = []
    if history:
        messages.extend(history)
    messages.append({"role": "user", "content": text})
    resp = client.messages.create(
        model=CLAUDE_MODEL_SMART,
        max_tokens=1500,
        temperature=0.85,
        system=_build_coach_system(user, today_stats, client_context, today_meals),
        messages=messages,
    )
    return resp.content[0].text


async def comment_food(food_data: dict, user: dict, today_stats: dict, history: list = None, client_context: str = "", today_meals: list = None) -> str:
    remaining = user.get("daily_calories_target", 1800) - today_stats.get("calories", 0)
    prompt = (
        f"Я только что съела: {food_data.get('dish', '?')} — {food_data.get('calories', 0)} ккал, "
        f"белок {food_data.get('protein', 0)}г, углеводы {food_data.get('carbs', 0)}г, жиры {food_data.get('fat', 0)}г. "
        f"Порция: {food_data.get('portion', '?')}. "
        f"Осталось на сегодня: {remaining} ккал. "
        f"Прокомментируй кратко — 2-4 предложения."
    )
    return await coach_response(prompt, user, today_stats, history, client_context, today_meals)


async def daily_summary(user: dict, today_stats: dict, client_context: str = "", today_meals: list = None) -> str:
    prompt = (
        f"Подведи итог дня. Съедено {today_stats['calories']} ккал из {user.get('daily_calories_target', 1800)}, "
        f"белок {today_stats['protein']} г из {user.get('daily_protein_target', 100)}, "
        f"приёмов пищи: {today_stats['meal_count']}, сожжено активностью: {today_stats['calories_burned']} ккал. "
        f"Дай краткий вердикт и совет на завтра."
    )
    return await coach_response(prompt, user, today_stats, client_context=client_context, today_meals=today_meals)


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
