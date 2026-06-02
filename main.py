import asyncio
import json
import logging
import os
import random
from datetime import datetime
from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from database import (
    init_db, load_user_language, save_user_language,
    load_progress, save_progress, get_user_profile,
    get_block_by_id, add_question_to_block, delete_question_from_block,
    get_all_users_stats, get_all_users_list, get_inactive_users_count
)
from aiogram import F

logging.basicConfig(level=logging.INFO)

BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise ValueError("❌ BOT_TOKEN не задана!")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# Загрузка data.json
DATA = {"blocks": []}
try:
    with open("data.json", "r", encoding="utf-8") as f:
        DATA = json.load(f)
    print(f"✅ Загружено блоков: {len(DATA.get('blocks', []))}")
except Exception as e:
    print(f"❌ Ошибка загрузки data.json: {e}")
    DATA = {"blocks": []}

def reload_data():
    global DATA
    try:
        with open("data.json", "r", encoding="utf-8") as f:
            DATA = json.load(f)
        print("✅ Данные обновлены в памяти")
    except Exception as e:
        print(f"❌ Ошибка обновления данных: {e}")

FIRST_BLOCK_ID = {"Python": 1, "C++": 6, "Java": 11, "JavaScript": 16, "Git": 21}
ADMIN_IDS = [int(x.strip()) for x in os.getenv("ADMIN_IDS","").split(",") if x.strip().isdigit()]

ACHIEVEMENTS = {
    "first_block": {"id": "first_block", "name": "🌟 Первый шаг", "desc": "Пройти первый учебный блок", "xp": 50},
    "polyglot": {"id": "polyglot", "name": "🌍 Полиглот", "desc": "Начать изучение 3 разных языков", "xp": 150},
    "master_all": {"id": "master_all", "name": "👑 Мастер кода", "desc": "Пройти все блоки по всем языкам", "xp": 500},
    "speed_learner": {"id": "speed_learner", "name": "⚡ Скоростной ученик", "desc": "Пройти блок быстрее 60 секунд", "xp": 75},
    "marathon": {"id": "marathon", "name": "🏃 Марафонец", "desc": "Пройти 10 блоков подряд без перерыва", "xp": 200},
    "perfect_block": {"id": "perfect_block", "name": "💎 Идеально!", "desc": "100% правильных ответов в блоке", "xp": 100},
    "sharp_eye": {"id": "sharp_eye", "name": "🎯 Острый глаз", "desc": "5 блоков подряд с точностью >90%", "xp": 175},
    "no_mistakes": {"id": "no_mistakes", "name": "🛡️ Безупречный", "desc": "20 вопросов подряд без ошибок", "xp": 250},
    "hardcore": {"id": "hardcore", "name": "🔥 Хардкор", "desc": "Пройти блок, где все вопросы сложности Hard", "xp": 300},
    "comeback_king": {"id": "comeback_king", "name": "🔄 Король возвращения", "desc": "Исправить 3 ошибки подряд после серии провалов", "xp": 125},
    "daily_streak_3": {"id": "daily_streak_3", "name": "📅 Три дня подряд", "desc": "Заходить в бота 3 дня подряд", "xp": 60},
    "daily_streak_7": {"id": "daily_streak_7", "name": "🗓️ Недельный челлендж", "desc": "Заходить в бота 7 дней подряд", "xp": 150},
    "daily_streak_30": {"id": "daily_streak_30", "name": "🏆 Месяц с ботом", "desc": "Заходить в бота 30 дней подряд", "xp": 500},
    "early_bird": {"id": "early_bird", "name": "🌅 Ранняя пташка", "desc": "Пройти блок до 9 утра", "xp": 40},
    "night_owl": {"id": "night_owl", "name": "🦉 Ночной кодёр", "desc": "Пройти блок после 23:00", "xp": 40},
    "language_explorer": {"id": "language_explorer", "name": "🌐 Исследователь языков", "desc": "Попробовать вопросы по всем 5 языкам", "xp": 200},
    "git_master": {"id": "git_master", "name": "🌿 Git-гуру", "desc": "Пройти все блоки по Git", "xp": 180},
    "python_pro": {"id": "python_pro", "name": "🐍 Python-профи", "desc": "Пройти все блоки по Python", "xp": 180},
    "cpp_warrior": {"id": "cpp_warrior", "name": "⚙️ C++ Воин", "desc": "Пройти все блоки по C++", "xp": 180},
    "java_champion": {"id": "java_champion", "name": "☕ Java-чемпион", "desc": "Пройти все блоки по Java", "xp": 180},
    "first_admin": {"id": "first_admin", "name": "🔧 Первый админ", "desc": "Воспользоваться админ-панелью", "xp": 30},
    "question_creator": {"id": "question_creator", "name": "✍️ Создатель вопросов", "desc": "Добавить свой первый вопрос через админку", "xp": 100},
    "helper": {"id": "helper", "name": "🤝 Помощник", "desc": "Просмотреть объяснения к 50 вопросам", "xp": 80},
    "curious": {"id": "curious", "name": "🔍 Любопытный", "desc": "Прочитать все термины в блоке перед тестом", "xp": 50},
    "lucky_guess": {"id": "lucky_guess", "name": "🍀 Везунчик", "desc": "Угадать 5 сложных вопросов подряд с первой попытки", "xp": 90},
    "second_chance": {"id": "second_chance", "name": "🔄 Второй шанс", "desc": "Улучшить результат в блоке при повторном прохождении", "xp": 70},
    "level_up_10": {"id": "level_up_10", "name": "📈 Десятый уровень", "desc": "Достичь уровня 'Эксперт'", "xp": 200},
    "xp_hunter": {"id": "xp_hunter", "name": "💰 Охотник за XP", "desc": "Набрать 1000 XP", "xp": 150},
    "knowledge_seeker": {"id": "knowledge_seeker", "name": "🧠 Искатель знаний", "desc": "Ответить на 100 вопросов", "xp": 200},
    "legend": {"id": "legend", "name": "👑 Легенда", "desc": "Получить все остальные достижения", "xp": 1000}
}

LEVELS = [
    (0, "🌱 Новичок", "Только начинаешь"),
    (500, "📚 Студент", "Активно учишься"),
    (1500, "⭐ Продвинутый", "Хорошие знания"),
    (3000, "🎓 Эксперт", "Отличное понимание"),
    (6000, "🏆 Мастер", "Профессиональный уровень"),
    (10000, "👑 Легенда", "Непревзойдённый")
]

class AdminStates(StatesGroup):
    waiting_for_stats_id = State()
    adding_q_lang = State()
    adding_q_block = State()
    adding_q_text = State()
    adding_q_options = State()
    adding_q_correct = State()
    adding_q_explanation = State()
    adding_q_correct_text = State() # Для текстовых вопросов
    del_lang = State()
    del_block = State()
    del_id = State()

class GlossaryStates(StatesGroup):
    searching = State()

def get_level(xp):
    current = LEVELS[0]
    for threshold, name, desc in LEVELS:
        if xp >= threshold:
            current = (threshold, name, desc)
    return current

def get_progress_bar(current, total, length=10):
    if total <= 0: return "░" * length + " 0%"
    filled = int(length * current / total)
    return "█" * filled + "░" * (length - filled) + f" {int((current/total)*100)}%"

async def async_load_progress(user_id):
    loop = asyncio.get_event_loop()
    from functools import partial
    return await loop.run_in_executor(None, partial(load_progress, user_id))

async def async_save_progress(user_id, data):
    loop = asyncio.get_event_loop()
    from functools import partial
    await loop.run_in_executor(None, partial(save_progress, user_id, data))

def is_admin(user_id):
    return user_id in ADMIN_IDS

def get_daily_bonus(user_data):
    last_login = user_data.get("last_login_date")
    current_date = datetime.now().strftime("%Y-%m-%d")
    streak = user_data.get("login_streak", 0)
    if last_login != current_date:
        if last_login:
            try:
                last_date = datetime.strptime(last_login, "%Y-%m-%d")
                days_diff = (datetime.now() - last_date).days
                streak = streak + 1 if days_diff == 1 else 1
            except:
                streak = 1
        else:
            streak = 1
        return (10 * streak, streak, True)
    return (0, streak, False)

def ensure_user_data(progress, lang):
    lang = lang.strip()
    if lang not in progress:
        progress[lang] = {
            "current_block": FIRST_BLOCK_ID.get(lang, 1),
            "completed_blocks": [],
            "current_attempt": None,
            "xp": 0,
            "achievements": [],
            "login_streak": 0,
            "last_login_date": None,
            "total_correct": 0,
            "total_answered": 0
        }
    user_data = progress[lang]
    defaults = {"xp": 0, "achievements": [], "login_streak": 0, "last_login_date": None, "total_correct": 0, "total_answered": 0}
    for key, val in defaults.items():
        if key not in user_data:
            user_data[key] = val
    return user_data

def get_main_keyboard(uid):
    lang = load_user_language(uid)
    if not lang:
        return get_language_keyboard()
    progress = load_progress(uid)
    lang_data = ensure_user_data(progress, lang)
    current_block = lang_data.get("current_block", FIRST_BLOCK_ID.get(lang.strip(), 1))
    completed_blocks = lang_data.get("completed_blocks", [])
    keyboard = [
        [KeyboardButton(text="📚 Обучение"), KeyboardButton(text="🧠 Задание")],
        [KeyboardButton(text="📖 Справочник"), KeyboardButton(text="🏆 Достижения")],
        [KeyboardButton(text="🔄 Сменить язык"), KeyboardButton(text="📋 Инструкция")],
    ]
    if current_block != FIRST_BLOCK_ID.get(lang.strip(), 1) or completed_blocks:
        keyboard.append([KeyboardButton(text="🔁 Повторить обучение"), KeyboardButton(text="🧪 Повторить тест")])
    if is_admin(uid):
        keyboard.append([KeyboardButton(text="⚙️ Админка")])
    return ReplyKeyboardMarkup(keyboard=keyboard, resize_keyboard=True)

def get_language_keyboard():
    return ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="🐍 Python"), KeyboardButton(text="⚙️ C++")],
        [KeyboardButton(text="☕ Java"), KeyboardButton(text="📜 JavaScript")],
        [KeyboardButton(text="🌱 Git")]], resize_keyboard=True)

def get_answer_buttons():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="1️⃣", callback_data="ans_1"),
         InlineKeyboardButton(text="2️⃣", callback_data="ans_2"),
         InlineKeyboardButton(text="3️⃣", callback_data="ans_3")]
    ])

@dp.message(Command("start"))
async def start(message: Message):
    uid = message.from_user.id
    lang = load_user_language(uid)
    if lang is None:
        await message.answer(" Привет! Выбери язык:", reply_markup=get_language_keyboard())
    else:
        await show_main_menu(message, uid, lang)

async def show_main_menu(message, uid, lang):
    progress = load_progress(uid)
    lang_data = ensure_user_data(progress, lang)
    xp = lang_data.get("xp", 0)
    level_info = get_level(xp)
    completed = len(lang_data.get("completed_blocks", []))
    achievements_count = len(lang_data.get("achievements", []))
    next_level_xp = None
    for threshold, _, _ in LEVELS[1:]:
        if xp < threshold:
            next_level_xp = threshold
            break
    bar = get_progress_bar(xp - level_info[0], next_level_xp - level_info[0]) if next_level_xp else "░"*10 + " MAX "
    msg = (f"📖 Меню ({lang})\n"
           f"🏅 {level_info[1]} ({level_info[0]} XP)\n{bar}\n"
           f" Статистика:\n"
           f"📚 Пройдено: {completed}\n"
           f"🏆 Достижений: {achievements_count}\n"
           f"🔥 Серия: {lang_data.get('login_streak', 0)} дн.\n"
           f"Выбери режим: ")
    await message.answer(msg, parse_mode=None, reply_markup=get_main_keyboard(uid))

@dp.message(lambda m: m.text.strip() in ["🐍 Python", "⚙️ C++", "☕ Java", "📜 JavaScript", "🌱 Git"])
async def handle_language_selection(message: Message):
    uid = message.from_user.id
    lang_map = {"🐍 Python": "Python", "⚙️ C++": "C++", "☕ Java": "Java", "📜 JavaScript": "JavaScript", "🌱 Git": "Git"}
    lang = lang_map.get(message.text.strip())
    if not lang: return
    progress = load_progress(uid)
    if lang not in progress or not progress[lang].get("completed_blocks"):
        await message.answer(
            "✅ Отличный выбор!\n"
            "📌 Что делать дальше:\n"
            "1️⃣ Нажми «📚 Обучение» — изучи термины блока\n"
            "2️⃣ Нажми «🧠 Задание» — ответь на вопросы\n"
            "3️⃣ Повторяй материал, чтобы закрепить знания!\n"
            "💡 В любой момент нажми «📋 Инструкция» для подробной справки.",
            parse_mode=None
        )
    save_user_language(uid, lang)
    user_data = ensure_user_data(progress, lang)
    bonus, streak, is_new = get_daily_bonus(user_data)
    if is_new and bonus > 0:
        user_data["last_login_date"] = datetime.now().strftime("%Y-%m-%d")
        user_data["login_streak"] = streak
        user_data["xp"] += bonus
        await message.answer(f"🎁 Бонус! +{bonus} XP")
    await async_save_progress(uid, progress)
    await show_main_menu(message, uid, lang)

@dp.message(lambda m: m.text.strip() == "🔄 Сменить язык")
async def change_language(message: Message):
    uid = message.from_user.id
    progress = load_progress(uid)
    lang = load_user_language(uid)
    if lang and progress.get(lang, {}).get("current_attempt"):
        await message.answer("❗ Сначала заверши тест.")
        return
    await message.answer("📌 Выбери язык:", reply_markup=get_language_keyboard())

@dp.message(lambda m: m.text.strip() == "📚 Обучение")
async def learn(message: Message):
    uid = message.from_user.id
    lang = load_user_language(uid)
    if not lang: return await message.answer("Сначала выбери язык!", reply_markup=get_language_keyboard())
    progress = load_progress(uid)
    lang_data = ensure_user_data(progress, lang)
    block = next((b for b in DATA["blocks"] if b["id"] == lang_data.get("current_block", FIRST_BLOCK_ID.get(lang, 1)) and b.get("language", "").strip() == lang), None)
    if not block or not block.get("terms"): return await message.answer("📭 Нет терминов.")
    terms_text = "\n\n".join([f"**{t['term']}**\n_{t['definition']}_\n`\n{t['example']}\n`" for t in block["terms"]])
    await message.answer(f"📘 **{block['title']}**\n{terms_text}", parse_mode=None)

@dp.message(lambda m: m.text.strip() == "📖 Справочник")
async def glossary_start(message: Message, state: FSMContext):
    await message.answer("🔍 Справочник терминов\n\nВведите название термина или часть определения для поиска:", parse_mode=None)
    await state.set_state(GlossaryStates.searching)

@dp.message(GlossaryStates.searching)
async def glossary_search(message: Message, state: FSMContext):
    query = message.text.lower().strip()
    found = []
    for block in DATA.get("blocks", []):
        for term in block.get("terms", []):
            if query in term.get("term", "").lower() or query in term.get("definition", "").lower():
                found.append(term)
    if found:
        text = f"🔍 **Найдено: {len(found)}**\n\n"
        for t in found[:10]:
            text += f"**{t['term']}**\n_{t['definition']}_\n\n"
        if len(found) > 10: text += "...и ещё несколько\n"
        await message.answer(text, parse_mode=None)
    else:
        await message.answer("❌ **Ничего не найдено**\nПопробуйте другой запрос.", parse_mode=None)
    await state.clear()

@dp.message(lambda m: m.text.strip() == "📋 Инструкция")
async def show_instructions(message: Message):
    instructions = (
        "📘 КАК ПОЛЬЗОВАТЬСЯ БОТОМ\n\n"
        "🔹 Шаг 1: Выбери язык\nНажми на кнопку с языком, чтобы начать обучение.\n\n"
        "🔹 Шаг 2: Изучи теорию\n• Нажми «📚 Обучение»\n• Прочитай термины и примеры кода\n\n"
        "🔹 Шаг 3: Пройди тест\n• Нажми «🧠 Задание»\n• Ответь на вопросы (кнопки или текст)\n• Цветные значки показывают сложность\n  🟢 Easy — 10 XP\n  🟡 Medium — 20 XP\n  🔴 Hard — 30 XP\n\n"
        "🔹 Шаг 4: Повторяй и закрепляй\n• После теста блок разблокируется для повторения\n• Используй «🔁 Повторить обучение» для теории\n• Используй «🧪 Повторить тест» для практики\n\n"
        "🏆 Система прогресса\n• За правильные ответы даются XP\n• Набирай XP, чтобы повышать уровень:\n  🌱 Новичок → 📚 Студент → ⭐ Продвинутый → 🎓 Эксперт → 🏆 Мастер → 👑 Легенда\n• Открывай достижения за особые успехи!\n\n"
        "💡 Советы\n1. Не спеши — сначала изучи термины.\n2. Читай объяснения к ошибкам.\n3. Собирай достижения.\n4. Меняй языки, чтобы стать полиглотом.\n\n"
        "❓ Возникли вопросы? Используй кнопки меню или напиши /start."
    )
    await message.answer(instructions, parse_mode=None)

@dp.message(lambda m: m.text.strip() == "🏆 Достижения")
async def show_achievements(message: Message):
    uid = message.from_user.id
    lang = load_user_language(uid)
    if not lang: return await message.answer("Сначала выбери язык!", reply_markup=get_language_keyboard())
    progress = load_progress(uid)
    lang_data = ensure_user_data(progress, lang)
    earned_ids = [a["id"] for a in lang_data.get("achievements", [])]
    msg = "  ДОСТИЖЕНИЯ\n\n"
    if earned_ids:
        msg += "✅ Получено:\n"
        for ach_id in earned_ids:
            if ach_id in ACHIEVEMENTS:
                ach = ACHIEVEMENTS[ach_id]
                msg += f"{ach['name']}\n_{ach['desc']}\n\n"
    else:
        msg += "📭 Пока нет полученных достижений.\n\n"
    msg += "\n  Заблокировано:\n"
    for ach_id, ach in ACHIEVEMENTS.items():
        if ach_id not in earned_ids:
            msg += f"🔒 {ach['name']}\n_{ach['desc']}\n\n"
    await message.answer(msg, parse_mode=None)

@dp.message(lambda m: m.text.strip() == "🧠 Задание")
async def task(message: Message):
    uid = message.from_user.id
    lang = load_user_language(uid)
    if not lang: return await message.answer("Сначала выбери язык!", reply_markup=get_language_keyboard())
    progress = load_progress(uid)
    lang_data = ensure_user_data(progress, lang)
    if lang_data.get("current_attempt"): return await message.answer("❗ Тест уже идет.")
    current_block_id = lang_data.get("current_block", FIRST_BLOCK_ID.get(lang, 1))
    block = next((b for b in DATA["blocks"] if b["id"] == current_block_id and b.get("language", "").strip() == lang), None)
    if not block or not block.get("tasks"): return await message.answer("📭 Нет заданий.")

    tasks = block.get("tasks", [])
    selected = random.sample(tasks, min(5, len(tasks)))
    new_attempt = {"block_id": current_block_id, "questions": selected, "index": 0, "correct": 0, "total": len(selected), "mode": "block", "start_time": datetime.now().timestamp(), "answers": []}
    lang_data["current_attempt"] = new_attempt
    await async_save_progress(uid, progress)
    await send_question(message, selected[0], 0, selected)

async def send_question(target, question, index, questions_list):
    code = f" `\n{question['code']}\n` " if question.get("code") else ""
    diff = question.get("difficulty", "easy")
    diff_icon = {"easy": "🟢", "medium": "🟡", "hard": "🔴"}.get(diff, "⚪")
    if question.get("options"):
        text = f"{diff_icon} **Вопрос {index+1}/{len(questions_list)}**\n\n{question['question']}\n\n{code}\n\n" + \
               "\n".join([f"{i+1}. {opt}" for i, opt in enumerate(question["options"])])
        if isinstance(target, CallbackQuery):
            await target.message.answer(text, parse_mode=None, reply_markup=get_answer_buttons())
        else:
            await target.answer(text, parse_mode=None, reply_markup=get_answer_buttons())
    else:
        text = f"{diff_icon} **Вопрос {index+1}/{len(questions_list)}**\n\n{question['question']}\n\n{code}\n\n✍️ **Введите ответ текстом:**"
        if isinstance(target, CallbackQuery):
            await target.message.answer(text, parse_mode=None)
        else:
            await target.answer(text, parse_mode=None)

@dp.message(lambda m: m.text.strip() == "🔁 Повторить обучение")
async def repeat_learn(message: Message):
    uid = message.from_user.id
    lang = load_user_language(uid)
    if not lang: return await message.answer("Сначала выбери язык!", reply_markup=get_language_keyboard())
    progress = load_progress(uid)
    lang_data = ensure_user_data(progress, lang)
    if lang_data.get("current_attempt"): return await message.answer("❗ Сначала заверши тест.")
    completed = lang_data.get("completed_blocks", [])
    current_block = lang_data.get("current_block", FIRST_BLOCK_ID.get(lang, 1))
    blocks_to_show = [b for b in DATA["blocks"] if b.get("language", "").strip() == lang and b["id"] in set(completed + [current_block])]
    if not blocks_to_show: return await message.answer("📭 Нет тем.")
    buttons = [[InlineKeyboardButton(text=block["title"], callback_data=f"repeat_block_{block['id']}")] for block in blocks_to_show]
    await message.answer("📚 **Повторение:** ", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))

@dp.callback_query(lambda c: c.data.startswith("repeat_block_"))
async def handle_repeat_block_selection(callback: CallbackQuery):
    await callback.answer()
    uid = callback.from_user.id
    lang = load_user_language(uid)
    try: block_id = int(callback.data.split("_")[-1])
    except: return await callback.answer("❌ Ошибка.")
    block = next((b for b in DATA["blocks"] if b["id"] == block_id and b.get("language", "").strip() == lang), None)
    if not block or not block.get("terms"): return await callback.message.answer("📭 Нет терминов.")
    terms_text = "\n\n".join([f"**{t['term']}**\n_{t['definition']}_\n```\n{t['example']}\n```" for t in block["terms"]])
    await callback.message.answer(f"📘 **{block['title']}**\n{terms_text}", parse_mode=None)

@dp.message(lambda m: m.text.strip() == "🧪 Повторить тест")
async def repeat_test(message: Message):
    uid = message.from_user.id
    lang = load_user_language(uid)
    if not lang: return await message.answer("Сначала выбери язык!", reply_markup=get_language_keyboard())
    progress = load_progress(uid)
    lang_data = ensure_user_data(progress, lang)
    if lang_data.get("current_attempt"): return await message.answer("❗ Тест уже идет.")
    completed = lang_data.get("completed_blocks", [])
    current_block = lang_data.get("current_block", FIRST_BLOCK_ID.get(lang, 1))
    all_block_ids = set(completed + [current_block])
    all_questions = []
    for block in DATA["blocks"]:
        if block.get("language", "").strip() == lang and block["id"] in all_block_ids and block.get("tasks"):
            all_questions.extend(block["tasks"])
    if not all_questions: return await message.answer("📭 Нет вопросов.")
    selected = random.sample(all_questions, min(10, len(all_questions)))
    new_attempt = {"block_id": -1, "questions": selected, "index": 0, "correct": 0, "total": len(selected), "mode": "repeat", "start_time": datetime.now().timestamp(), "answers": []}
    lang_data["current_attempt"] = new_attempt
    await async_save_progress(uid, progress)
    await send_question(message, selected[0], 0, selected)

@dp.callback_query(lambda c: c.data.startswith("ans_"))
async def handle_inline_answer(callback: CallbackQuery):
    await callback.answer()
    uid = callback.from_user.id
    lang = load_user_language(uid)
    if not lang: return
    progress = load_progress(uid)
    lang_data = ensure_user_data(progress, lang)
    attempt = lang_data.get("current_attempt")
    if not attempt: return
    idx = attempt["index"]
    if idx >= attempt["total"]: return
    q = attempt["questions"][idx]
    is_correct = (int(callback.data.split("_")[1]) - 1 == q.get("correct", 0))
    attempt["answers"].append(is_correct)
    if is_correct:
        attempt["correct"] += 1
        await callback.message.answer("✅ **Верно!**", parse_mode=None)
    else:
        await callback.message.answer(f"❌ **Нет.** Правильно: {q['options'][q['correct']]}\n💡 {q['explanation']}", parse_mode=None)
    attempt["index"] += 1
    await async_save_progress(uid, progress)
    if attempt["index"] < attempt["total"]:
        await send_question(callback, attempt["questions"][attempt["index"]], attempt["index"], attempt["questions"])
    else:
        await finish_quiz(callback.message, uid, lang, attempt)

@dp.message(lambda m: m.text.strip() == "⚙️ Админка")
async def admin_panel(message: Message):
    uid = message.from_user.id
    if not is_admin(uid):
        return await message.answer("❌ Доступ запрещён")
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Добавить вопрос", callback_data="admin_add")],
        [InlineKeyboardButton(text=" Удалить вопрос", callback_data="admin_del_req")],
        [InlineKeyboardButton(text=" Статистика по ID", callback_data="admin_stats_req")],
        [InlineKeyboardButton(text="📊 Статистика всех", callback_data="admin_stats_all")],
        [InlineKeyboardButton(text="👥 Список пользователей", callback_data="admin_all_users")], # НОВАЯ КНОПКА
        [InlineKeyboardButton(text="🧹 Сброс прогресса", callback_data="admin_reset")],
        [InlineKeyboardButton(text="🔙 В меню", callback_data="admin_back")]
    ])
    await message.answer("🔧 **Админ-панель** ", reply_markup=keyboard)

@dp.message(F.text)
async def handle_text_answer(message: Message):
    if message.text.startswith("/") or message.text.strip() in ["📚 Обучение", "🧠 Задание", "📖 Справочник", "🏆 Достижения", "🔄 Сменить язык", "🔁 Повторить обучение", "🧪 Повторить тест", "⚙️ Админка", "📋 Инструкция"]:
        return
    uid = message.from_user.id
    lang = load_user_language(uid)
    if not lang: return
    progress = load_progress(uid)
    lang_data = ensure_user_data(progress, lang)
    attempt = lang_data.get("current_attempt")
    if not attempt: return
    idx = attempt["index"]
    if idx >= attempt["total"]: return
    q = attempt["questions"][idx]
    if q.get("options"): return
    user_answer = message.text.strip().lower()
    correct_answer = q.get("correct_text", "").lower()
    is_correct = (user_answer == correct_answer)
    attempt["answers"].append(is_correct)
    if is_correct:
        attempt["correct"] += 1
        await message.answer("✅ **Верно!**", parse_mode=None)
    else:
        await message.answer(f"❌ **Нет.** Правильный ответ: `{q['correct_text']}`\n💡 {q['explanation']}", parse_mode=None)
    attempt["index"] += 1
    await async_save_progress(uid, progress)
    if attempt["index"] < attempt["total"]:
        await send_question(message, attempt["questions"][attempt["index"]], attempt["index"], attempt["questions"])
    else:
        await finish_quiz(message, uid, lang, attempt)

async def finish_quiz(message, uid, lang, attempt):
    total = attempt["total"]
    correct = attempt["correct"]
    score = correct / total
    time_spent = int(datetime.now().timestamp() - attempt.get("start_time", 0))
    progress = load_progress(uid)
    lang_data = ensure_user_data(progress, lang)
    lang_data["current_attempt"] = None
    lang_data["total_answered"] = lang_data.get("total_answered", 0) + total
    lang_data["total_correct"] = lang_data.get("total_correct", 0) + correct

    old_xp = lang_data.get("xp", 0)
    xp_earned = 0
    hard_correct = 0
    consecutive_hard_correct = 0

    for i, q in enumerate(attempt["questions"]):
        if i < len(attempt["answers"]) and attempt["answers"][i]:
            diff = q.get("difficulty", "easy")
            if diff == "hard":
                xp_earned += 30
                consecutive_hard_correct += 1
                hard_correct += 1
            elif diff == "medium": xp_earned += 20; consecutive_hard_correct = 0
            else: xp_earned += 10; consecutive_hard_correct = 0

    time_bonus = 20 if time_spent < 120 else 0
    new_xp = old_xp + xp_earned + time_bonus
    earned = []
    achieved_ids = [a["id"] for a in lang_data.get("achievements", [])]
    if "first_block" not in achieved_ids and len(lang_data.get("completed_blocks", [])) == 0: earned.append(ACHIEVEMENTS["first_block"])
    if "perfect_block" not in achieved_ids and score == 1.0: earned.append(ACHIEVEMENTS["perfect_block"])
    if "speed_learner" not in achieved_ids and time_spent < 60: earned.append(ACHIEVEMENTS["speed_learner"])
    if "hardcore" not in achieved_ids and hard_correct == total: earned.append(ACHIEVEMENTS["hardcore"])
    if "lucky_guess" not in achieved_ids and consecutive_hard_correct >= 5: earned.append(ACHIEVEMENTS["lucky_guess"])
    if "early_bird" not in achieved_ids and datetime.now().hour < 9: earned.append(ACHIEVEMENTS["early_bird"])
    if "night_owl" not in achieved_ids and datetime.now().hour >= 23: earned.append(ACHIEVEMENTS["night_owl"])
    if "knowledge_seeker" not in achieved_ids and lang_data.get("total_answered", 0) >= 100: earned.append(ACHIEVEMENTS["knowledge_seeker"])
    if "xp_hunter" not in achieved_ids and new_xp >= 1000: earned.append(ACHIEVEMENTS["xp_hunter"])
    if "level_up_10" not in achieved_ids and get_level(new_xp)[1] == "🎓 Эксперт": earned.append(ACHIEVEMENTS["level_up_10"])

    for ach in earned:
        if ach["id"] not in achieved_ids:
            lang_data.setdefault("achievements", []).append({"id": ach["id"], "earned_at": datetime.now().isoformat()})
            new_xp += ach["xp"]
            
    if len(lang_data.get("achievements", [])) >= len(ACHIEVEMENTS) - 1 and "legend" not in achieved_ids:
        lang_data["achievements"].append({"id": "legend", "earned_at": datetime.now().isoformat()})
        new_xp += 1000
        
    old_level = get_level(old_xp)
    new_level = get_level(new_xp)
    leveled_up = old_level[0] != new_level[0]
    lang_data["xp"] = new_xp

    if attempt.get("mode") == "block" and attempt["block_id"] != -1:
        if attempt["block_id"] not in lang_data.get("completed_blocks", []):
            lang_data.setdefault("completed_blocks", []).append(attempt["block_id"])
        next_id = attempt["block_id"] + 1
        if next_id in [b["id"] for b in DATA["blocks"]] and score >= 0.8:
            lang_data["current_block"] = next_id
            
    await async_save_progress(uid, progress)
    total_ans = lang_data.get("total_answered", 0)
    total_corr = lang_data.get("total_correct", 0)
    accuracy = (total_corr / total_ans * 100) if total_ans > 0 else 0

    msg = (f"🏁 **Готово!**\n✅ {correct}/{total}\n📊 {score*100:.0f}%\n⏱️ {time_spent}с\n💎 XP: +{xp_earned + time_bonus}\n**Точность: {accuracy:.1f}%**")
    if earned: msg += "\n\n🏆 **НОВЫЕ ДОСТИЖЕНИЯ:**\n" + "\n".join([f"{a['name']} (+{a['xp']} XP)" for a in earned])
    if leveled_up: msg += f"\n\n**НОВЫЙ УРОВЕНЬ!**\n{new_level[1]}"
    await message.answer(msg, parse_mode=None)
    await show_main_menu(message, uid, lang)



@dp.callback_query(lambda c: c.data == "admin_back")
async def admin_back(callback: CallbackQuery):
    await callback.answer()
    await show_main_menu(callback.message, callback.from_user.id, load_user_language(callback.from_user.id))

@dp.callback_query(lambda c: c.data == "admin_reset")
async def admin_reset(callback: CallbackQuery):
    await callback.answer()
    uid = callback.from_user.id
    lang = load_user_language(uid)
    if not lang: return await callback.message.answer("❌ Сначала выбери язык.")
    progress = load_progress(uid)
    progress[lang] = {"current_block": FIRST_BLOCK_ID.get(lang, 1), "completed_blocks": [], "current_attempt": None, "xp": 0, "achievements": [], "login_streak": 0, "last_login_date": None, "total_correct": 0, "total_answered": 0}
    save_progress(uid, progress)
    await callback.message.answer("♻️ Прогресс сброшен!")
    await show_main_menu(callback.message, uid, lang)

@dp.callback_query(lambda c: c.data == "admin_stats_req")
async def admin_stats_req(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await callback.message.answer("🆔 Введите ID пользователя:")
    await state.set_state(AdminStates.waiting_for_stats_id)

@dp.message(AdminStates.waiting_for_stats_id)
async def admin_show_stats(message: Message, state: FSMContext):
    try: target_uid = int(message.text)
    except: await message.answer("❌ Введите числовой ID."); return
    profile = get_user_profile(target_uid)
    if not profile: await message.answer("❌ Пользователь не найден."); return
    progress = load_progress(target_uid)
    lang = profile.get("language")
    lang_data = ensure_user_data(progress, lang) if lang else {}
    xp = lang_data.get("xp", 0)
    level = get_level(xp)
    completed = len(lang_data.get("completed_blocks", []))
    total_ans = lang_data.get("total_answered", 0)
    total_corr = lang_data.get("total_correct", 0)
    accuracy = (total_corr / total_ans * 100) if total_ans > 0 else 0
    msg = (f"👤 **Профиль #{target_uid}**\n📛 {profile.get('first_name') or '—'}\n🌐 Язык: {lang or '—'}\n🏅 Уровень: {level[1]} ({xp} XP)\n📚 Блоков: {completed}\n🎯 Точность: {accuracy:.1f}%\n📊 Ответов: {total_ans}")
    await message.answer(msg, parse_mode=None)
    await state.clear()

@dp.callback_query(lambda c: c.data == "admin_all_users")
async def admin_all_users(callback: CallbackQuery):
    await callback.answer()
    users = get_all_users_list(limit=20)
    if not users:
        await callback.message.answer("Список пользователей пуст.")
        return
    
    text = "**Последние 20 пользователей:**\n\n"
    
    # Собираем кнопки как список списков
    keyboard_buttons = []
    for u in users:
        name = u.get("first_name") or u.get("username") or f"ID:{u['user_id']}"
        keyboard_buttons.append([InlineKeyboardButton(text=f"{name}", callback_data=f"admin_view_user_{u['user_id']}")])
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=keyboard_buttons)
    await callback.message.answer(text, reply_markup=keyboard)

@dp.callback_query(lambda c: c.data.startswith("admin_view_user_"))
async def admin_view_user(callback: CallbackQuery):
    await callback.answer()
    try: uid = int(callback.data.split("_")[-1])
    except: return
    profile = get_user_profile(uid)
    if not profile: await callback.message.answer("❌ Пользователь не найден."); return
    progress = load_progress(uid)
    lang = profile.get("language")
    lang_data = ensure_user_data(progress, lang) if lang else {}
    xp = lang_data.get("xp", 0)
    level = get_level(xp)
    completed = len(lang_data.get("completed_blocks", []))
    total_ans = lang_data.get("total_answered", 0)
    total_corr = lang_data.get("total_correct", 0)
    accuracy = (total_corr / total_ans * 100) if total_ans > 0 else 0
    msg = (f"👤 **Профиль #{uid}**\n📛 {profile.get('first_name') or '—'}\n🌐 Язык: {lang or '—'}\n🏅 Уровень: {level[1]} ({xp} XP)\n📚 Блоков: {completed}\n🎯 Точность: {accuracy:.1f}%\n📊 Ответов: {total_ans}")
    await callback.message.answer(msg, parse_mode=None)

@dp.callback_query(lambda c: c.data == "admin_inactive")
async def admin_inactive(callback: CallbackQuery):
    await callback.answer()
    stats = get_all_users_stats()
    inactive = stats.get("inactive", [])
    if not inactive: await callback.message.answer("✅ Нет неактивных пользователей за последние 7 дней."); return
    text = "🔔 **Неактивные пользователи (>7 дней):**\n\n"
    for u in inactive[:10]:
        name = u.get("first_name") or u.get("username") or f"ID:{u['user_id']}"
        last = u.get("last_seen", "неизвестно")
        text += f"• {name} (был: {last})\n"
    await callback.message.answer(text)

@dp.callback_query(lambda c: c.data == "admin_add")
async def admin_add_start(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    langs = list(set(b.get("language", "").strip() for b in DATA.get("blocks", []) if b.get("language")))
    keyboard = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=l, callback_data=f"admin_add_lang_{l}")] for l in langs])
    await callback.message.edit_text(" Выбери язык:", reply_markup=keyboard)
    await state.set_state(AdminStates.adding_q_lang)

@dp.callback_query(AdminStates.adding_q_lang, lambda c: c.data.startswith("admin_add_lang_"))
async def admin_add_lang(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    lang = callback.data.removeprefix("admin_add_lang_").strip()
    await state.update_data(lang=lang)
    blocks = [b for b in DATA.get("blocks", []) if b.get("language", "").strip() == lang]
    keyboard = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=f"#{b['id']} {b['title'][:15]}", callback_data=f"admin_add_block_{b['id']}")] for b in blocks])
    await callback.message.edit_text(f"📦 Блоки ({lang}):", reply_markup=keyboard)
    await state.set_state(AdminStates.adding_q_block)

@dp.callback_query(AdminStates.adding_q_block, lambda c: c.data.startswith("admin_add_block_"))
async def admin_add_block(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    block_id = int(callback.data.split("_")[-1])
    await state.update_data(block_id=block_id)
    await callback.message.answer("📝 Введите текст вопроса:")
    await state.set_state(AdminStates.adding_q_text)

@dp.message(AdminStates.adding_q_text)
async def admin_add_text(message: Message, state: FSMContext):
    await state.update_data(question=message.text)
    await message.answer("🔤 Варианты (через запятую):\nПример: `A,B,C`\nЕсли вопрос текстовый, напиши `-`")
    await state.set_state(AdminStates.adding_q_options)

@dp.message(AdminStates.adding_q_options)
async def admin_add_options(message: Message, state: FSMContext):
    if message.text.strip() == "-":
        await message.answer("✍️ **Введите правильный ответ (текст):**")
        await state.set_state(AdminStates.adding_q_correct_text)
        return
    options = [o.strip() for o in message.text.split(",") if o.strip()]
    if len(options) < 2: return await message.answer("❌ Минимум 2 варианта.")
    await state.update_data(options=options)
    await message.answer(f"🔢 **Номер правильного (1-{len(options)}):**")
    await state.set_state(AdminStates.adding_q_correct)

@dp.message(AdminStates.adding_q_correct)
async def admin_add_correct(message: Message, state: FSMContext):
    try:
        idx = int(message.text) - 1
        data = await state.get_data()
        if not (0 <= idx < len(data["options"])): return await message.answer(f"❌ Число от 1 до {len(data['options'])}.")
        await state.update_data(correct=idx)
        await message.answer("💡 Пояснение (или '-'):")
        await state.set_state(AdminStates.adding_q_explanation)
    except: await message.answer("❌ Ошибка ввода.")

@dp.message(AdminStates.adding_q_correct_text)
async def admin_add_correct_text_handler(message: Message, state: FSMContext):
    await state.update_data(correct_text=message.text.strip())
    await message.answer("💡 Пояснение (или '-'):")
    await state.set_state(AdminStates.adding_q_explanation)

@dp.message(AdminStates.adding_q_explanation)
async def admin_add_finish(message: Message, state: FSMContext):
    data = await state.get_data()
    explanation = message.text if message.text.strip() != "-" else ""
    
    new_q = {
        "question": data["question"],
        "options": data.get("options", []),
        "correct": data.get("correct", 0),
        "explanation": explanation,
        "code": "",
        "difficulty": "medium",
        "correct_text": data.get("correct_text", "")
    }
    success = add_question_to_block(data["block_id"], new_q)
    if success:
        reload_data()
        await message.answer(f"✅ **Вопрос добавлен в блок #{data['block_id']}!**")
    else:
        await message.answer("❌ Ошибка при сохранении вопроса.")
    await state.clear()
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Ещё", callback_data="admin_add")], 
        [InlineKeyboardButton(text="🔙 В меню", callback_data="admin_back")]
    ])
    await message.answer("🔧 **Админка**", reply_markup=keyboard)

@dp.callback_query(lambda c: c.data == "admin_del_req")
async def admin_del_start(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    langs = list(set(b.get("language", "").strip() for b in DATA.get("blocks", []) if b.get("language")))
    keyboard = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=l, callback_data=f"admin_del_lang_{l}")] for l in langs])
    await callback.message.edit_text("❌ Удаление: Выбери язык:", reply_markup=keyboard)
    await state.set_state(AdminStates.del_lang)

@dp.callback_query(AdminStates.del_lang, lambda c: c.data.startswith("admin_del_lang_"))
async def admin_del_lang(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    lang = callback.data.removeprefix("admin_del_lang_").strip()
    await state.update_data(lang=lang)
    blocks = [b for b in DATA.get("blocks", []) if b.get("language", "").strip() == lang]
    keyboard = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=f"#{b['id']} {b['title'][:15]}", callback_data=f"admin_del_block_{b['id']}")] for b in blocks])
    await callback.message.edit_text(f"📦 Удаление: Выбери блок ({lang}):", reply_markup=keyboard)
    await state.set_state(AdminStates.del_block)

@dp.callback_query(AdminStates.del_block, lambda c: c.data.startswith("admin_del_block_"))
async def admin_del_block(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    block_id = int(callback.data.split("_")[-1])
    await state.update_data(block_id=block_id)
    block = get_block_by_id(block_id)
    tasks = block.get("tasks", []) if block else []
    if not tasks:
        await callback.message.answer(" В этом блоке нет вопросов.")
        await state.clear()
        return
    text = "🗑️ Выбери ID вопроса для удаления:\n\n"
    for q in tasks:
        text += f"🆔 ID: {q['id']} | {q['question'][:30]}...\n"
    text += "\n👇 Напиши ID вопроса, который нужно удалить:"
    await callback.message.answer(text, parse_mode=None)
    await state.set_state(AdminStates.del_id)

@dp.message(AdminStates.del_id)
async def admin_del_id(message: Message, state: FSMContext):
    try: q_id = int(message.text)
    except: await message.answer("❌ Введите числовой ID вопроса."); return
    data = await state.get_data()
    success = delete_question_from_block(data["block_id"], q_id)
    if success:
        reload_data()
        await message.answer(f"✅ Вопрос #{q_id} удален!")
    else:
        await message.answer(f"❌ Вопрос #{q_id} не найден.")
    await state.clear()
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Удалить ещё", callback_data="admin_del_req")], 
        [InlineKeyboardButton(text="🔙 В меню", callback_data="admin_back")]
    ])
    await message.answer("Админка", reply_markup=keyboard)

@dp.message(~StateFilter('*'))
async def handle_unknown(message: Message):
    lang = load_user_language(message.from_user.id)
    if lang:
        await message.answer("❓ Используй кнопки или /start", reply_markup=get_main_keyboard(message.from_user.id))
    else:
        await message.answer("Нажми /start", reply_markup=ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="/start")]], resize_keyboard=True))

async def main():
    init_db()
    print("✅ Бот запущен.")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())