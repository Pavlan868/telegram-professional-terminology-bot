# main.py
# Версия 8.1 - ИСПРАВЛЕНИЕ: НОВЫЕ ВОПРОСЫ ПОЯВЛЯЮТСЯ СРАЗУ
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
from database import init_db, load_user_language, save_user_language, load_progress, save_progress, get_user_profile, get_block_by_id, add_question_to_block

logging.basicConfig(level=logging.INFO)

BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise ValueError("❌ BOT_TOKEN не задана!")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# 🔥 ЗАГРУЗКА ДАННЫХ
try:
    with open("data.json", "r", encoding="utf-8") as f:
        DATA = json.load(f)
except Exception as e:
    print(f"❌ Ошибка загрузки data.json: {e}")
    DATA = {"blocks": []}

def reload_data():
    """Принудительно обновляет DATA из файла на диске"""
    global DATA
    try:
        with open("data.json", "r", encoding="utf-8") as f:
            DATA = json.load(f)
        print("✅ Данные успешно обновлены в памяти")
    except Exception as e:
        print(f"❌ Ошибка обновления данных: {e}")

FIRST_BLOCK_ID = {"Python": 1, "C++": 6, "Java": 11, "JavaScript": 16, "Git": 21}
ADMIN_IDS = [int(x) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip().isdigit()]

ACHIEVEMENTS = {
    "first_block": {"id": "first_block", "name": "🌟 Первый шаг", "desc": "Пройти первый блок", "xp": 50},
    "perfect_block": {"id": "perfect_block", "name": "💎 Идеально!", "desc": "100% в блоке", "xp": 100},
    "speed_demon": {"id": "speed_demon", "name": "⚡ Скорострел", "desc": "Блок < 2 мин", "xp": 75},
    "marathon": {"id": "marathon", "name": "🏃 Марафонец", "desc": "5 блоков подряд", "xp": 200},
    "polyglot": {"id": "polyglot", "name": "🌍 Полиглот", "desc": "3 языка", "xp": 300},
}

LEVELS = [
    (0, "🌱 Новичок", "Только начинаешь"),
    (100, "📚 Студент", "Активно учишься"),
    (300, "⭐ Продвинутый", "Хорошие знания"),
    (600, "🎓 Эксперт", "Отличное понимание"),
    (1000, "🏆 Мастер", "Профессиональный уровень"),
    (2500, "👑 Легенда", "Непревзойдённый")
]

class AdminStates(StatesGroup):
    waiting_for_stats_id = State()
    adding_q_lang = State()
    adding_q_block = State()
    adding_q_text = State()
    adding_q_options = State()
    adding_q_correct = State()
    adding_q_explanation = State()

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
    current_block = lang_data.get("current_block", FIRST_BLOCK_ID[lang])
    completed_blocks = lang_data.get("completed_blocks", [])

    keyboard = [
        [KeyboardButton(text="📚 Обучение"), KeyboardButton(text="🧠 Задание")],
        [KeyboardButton(text="🔄 Сменить язык"), KeyboardButton(text="🏆 Достижения")],
    ]
    if current_block != FIRST_BLOCK_ID[lang] or completed_blocks:
        keyboard.append([KeyboardButton(text="🔁 Повторить обучение"), KeyboardButton(text="🧪 Повторить тест")])
    if is_admin(uid):
        keyboard.append([KeyboardButton(text="⚙️ Админка")])
    return ReplyKeyboardMarkup(keyboard=keyboard, resize_keyboard=True)

def get_language_keyboard():
    return ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="🐍 Python"), KeyboardButton(text="CppClass C++")],
        [KeyboardButton(text="☕ Java"), KeyboardButton(text="📜 JavaScript")],
        [KeyboardButton(text="🌱 Git")]], resize_keyboard=True)

def get_answer_buttons():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="1", callback_data="ans_1")],
        [InlineKeyboardButton(text="2", callback_data="ans_2")],
        [InlineKeyboardButton(text="3", callback_data="ans_3")]
    ])

@dp.message(Command("start"))
async def start(message: Message):
    uid = message.from_user.id
    lang = load_user_language(uid)
    if lang is None:
        await message.answer("👋 **Привет!** Выбери язык:", reply_markup=get_language_keyboard())
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
    bar = get_progress_bar(xp - level_info[0], next_level_xp - level_info[0]) if next_level_xp else "░"*10 + " MAX"
    
    msg = (f"📖 **Меню ({lang})**\n\n"
           f"🏅 {level_info[1]} ({level_info[0]} XP)\n{bar}\n\n"
           f"📊 **Статистика:**\n📚 Пройдено: {completed}\n🏆 Достижений: {achievements_count}\n🔥 Серия: {lang_data.get('login_streak', 0)} дн.\n\nВыбери режим:")
    await message.answer(msg, parse_mode=None, reply_markup=get_main_keyboard(uid))

@dp.message(lambda m: m.text in ["🐍 Python", "CppClass C++", "☕ Java", "📜 JavaScript", "🌱 Git"])
async def handle_language_selection(message: Message):
    uid = message.from_user.id
    lang_map = {"🐍 Python": "Python", "CppClass C++": "C++", "☕ Java": "Java", "📜 JavaScript": "JavaScript", "🌱 Git": "Git"}
    lang = lang_map.get(message.text)
    if not lang: return
    save_user_language(uid, lang)
    progress = load_progress(uid)
    user_data = ensure_user_data(progress, lang)
    bonus, streak, is_new = get_daily_bonus(user_data)
    if is_new and bonus > 0:
        user_data["last_login_date"] = datetime.now().strftime("%Y-%m-%d")
        user_data["login_streak"] = streak
        user_data["xp"] += bonus
        await message.answer(f"🎁 **Бонус!** +{bonus} XP")
    await async_save_progress(uid, progress)
    await show_main_menu(message, uid, lang)

@dp.message(lambda m: m.text == "🔄 Сменить язык")
async def change_language(message: Message):
    uid = message.from_user.id
    progress = load_progress(uid)
    lang = load_user_language(uid)
    if lang and progress.get(lang, {}).get("current_attempt"):
        await message.answer("❗ Сначала заверши тест.")
        return
    await message.answer("📌 **Выбери язык:**", reply_markup=get_language_keyboard())

@dp.message(lambda m: m.text == "📚 Обучение")
async def learn(message: Message):
    uid = message.from_user.id
    lang = load_user_language(uid)
    if not lang: return await message.answer("Сначала выбери язык!", reply_markup=get_language_keyboard())
    progress = load_progress(uid)
    lang_data = ensure_user_data(progress, lang)
    block = next((b for b in DATA["blocks"] if b["id"] == lang_data.get("current_block", FIRST_BLOCK_ID[lang]) and b["language"] == lang), None)
    if not block or not block.get("terms"): return await message.answer("📭 Нет терминов.")
    terms_text = "\n\n".join([f"**{t['term']}**\n_{t['definition']}_\n```\n{t['example']}\n```" for t in block["terms"]])
    await message.answer(f"📘 **{block['title']}**\n\n{terms_text}", parse_mode=None)

@dp.message(lambda m: m.text == "🏆 Достижения")
async def show_achievements(message: Message):
    uid = message.from_user.id
    lang = load_user_language(uid)
    if not lang: return await message.answer("Сначала выбери язык!", reply_markup=get_language_keyboard())
    progress = load_progress(uid)
    lang_data = ensure_user_data(progress, lang)
    earned_ids = [a["id"] for a in lang_data.get("achievements", [])]
    msg = "🏆 **ДОСТИЖЕНИЯ**\n\n"
    for ach_id in earned_ids:
        if ach_id in ACHIEVEMENTS:
            msg += f"{ACHIEVEMENTS[ach_id]['name']}\n_{ACHIEVEMENTS[ach_id]['desc']}_\n\n"
    if not earned_ids: msg += "📭 Пока нет.\n\n"
    msg += "\n🔒 **Заблокировано:**\n"
    for ach_id, ach in ACHIEVEMENTS.items():
        if ach_id not in earned_ids: msg += f"🔒 {ach['name']}\n"
    await message.answer(msg, parse_mode=None)

@dp.message(lambda m: m.text == "🧠 Задание")
async def task(message: Message):
    uid = message.from_user.id
    lang = load_user_language(uid)
    if not lang: return await message.answer("Сначала выбери язык!", reply_markup=get_language_keyboard())
    progress = load_progress(uid)
    lang_data = ensure_user_data(progress, lang)
    if lang_data.get("current_attempt"): return await message.answer("❗ Тест уже идет.")
    current_block_id = lang_data.get("current_block", FIRST_BLOCK_ID[lang])
    
    block = next((b for b in DATA["blocks"] if b["id"] == current_block_id and b["language"] == lang), None)
    if not block or not block.get("tasks"): return await message.answer("📭 Нет заданий.")
    
    tasks = block.get("tasks", [])
    selected = random.sample(tasks, min(5, len(tasks)))
    new_attempt = {"block_id": current_block_id, "questions": selected, "index": 0, "correct": 0, "total": len(selected), "mode": "block", "start_time": datetime.now().timestamp()}
    lang_data["current_attempt"] = new_attempt
    await async_save_progress(uid, progress)
    q = selected[0]
    code = f"```\n{q['code']}\n```" if q.get("code") else ""
    text = f"❓ **Вопрос 1/{len(selected)}**\n\n{q['question']}\n\n{code}\n\n" + "\n".join([f"{i+1}. {opt}" for i, opt in enumerate(q["options"])])
    await message.answer(text, parse_mode=None, reply_markup=get_answer_buttons())

@dp.message(lambda m: m.text == "🔁 Повторить обучение")
async def repeat_learn(message: Message):
    uid = message.from_user.id
    lang = load_user_language(uid)
    if not lang: return await message.answer("Сначала выбери язык!", reply_markup=get_language_keyboard())
    progress = load_progress(uid)
    lang_data = ensure_user_data(progress, lang)
    if lang_data.get("current_attempt"): return await message.answer("❗ Сначала заверши тест.")
    completed = lang_data.get("completed_blocks", [])
    current_block = lang_data.get("current_block", FIRST_BLOCK_ID[lang])
    blocks_to_show = [b for b in DATA["blocks"] if b["language"] == lang and b["id"] in set(completed + [current_block])]
    if not blocks_to_show: return await message.answer("📭 Нет тем.")
    buttons = [[InlineKeyboardButton(text=block["title"], callback_data=f"repeat_block_{block['id']}")] for block in blocks_to_show]
    await message.answer("📚 **Повторение:**", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))

@dp.callback_query(lambda c: c.data.startswith("repeat_block_"))
async def handle_repeat_block_selection(callback: CallbackQuery):
    await callback.answer()
    uid = callback.from_user.id
    lang = load_user_language(uid)
    try: block_id = int(callback.data.split("_")[-1])
    except: return await callback.answer("❌ Ошибка.")
    block = next((b for b in DATA["blocks"] if b["id"] == block_id and b["language"] == lang), None)
    if not block or not block.get("terms"): return await callback.message.answer("📭 Нет терминов.")
    terms_text = "\n\n".join([f"**{t['term']}**\n_{t['definition']}_\n```\n{t['example']}\n```" for t in block["terms"]])
    await callback.message.answer(f"📘 **{block['title']}**\n\n{terms_text}", parse_mode=None)

@dp.message(lambda m: m.text == "🧪 Повторить тест")
async def repeat_test(message: Message):
    uid = message.from_user.id
    lang = load_user_language(uid)
    if not lang: return await message.answer("Сначала выбери язык!", reply_markup=get_language_keyboard())
    progress = load_progress(uid)
    lang_data = ensure_user_data(progress, lang)
    if lang_data.get("current_attempt"): return await message.answer("❗ Тест уже идет.")
    completed = lang_data.get("completed_blocks", [])
    current_block = lang_data.get("current_block", FIRST_BLOCK_ID[lang])
    all_block_ids = set(completed + [current_block])
    
    all_questions = []
    for block in DATA["blocks"]:
        if block["language"] == lang and block["id"] in all_block_ids and block.get("tasks"):
            all_questions.extend(block["tasks"])
    
    if not all_questions: return await message.answer("📭 Нет вопросов.")
    
    selected = random.sample(all_questions, min(10, len(all_questions)))
    new_attempt = {"block_id": -1, "questions": selected, "index": 0, "correct": 0, "total": len(selected), "mode": "repeat", "start_time": datetime.now().timestamp()}
    lang_data["current_attempt"] = new_attempt
    await async_save_progress(uid, progress)
    q = selected[0]
    code = f"```\n{q['code']}\n```" if q.get("code") else ""
    text = f"❓ **Вопрос 1/{len(selected)}**\n\n{q['question']}\n\n{code}\n\n" + "\n".join([f"{i+1}. {opt}" for i, opt in enumerate(q["options"])])
    await message.answer(text, parse_mode=None, reply_markup=get_answer_buttons())

@dp.callback_query(lambda c: c.data.startswith("ans_"))
async def handle_inline_answer(callback: CallbackQuery):
    await callback.answer()
    uid = callback.from_user.id
    lang = load_user_language(uid)
    if not lang: return
    progress = load_progress(uid)
    lang_data = ensure_user_data(progress, lang)
    attempt = lang_data.get("current_attempt")
    if not attempt: return await callback.message.answer("❌ Нет теста.")
    idx = attempt["index"]
    if idx >= attempt["total"]: return
    q = attempt["questions"][idx]
    is_correct = (int(callback.data.split("_")[1]) - 1 == q["correct"])
    if is_correct:
        attempt["correct"] += 1
        await callback.message.answer("✅ **Верно!**", parse_mode=None)
    else:
        await callback.message.answer(f"❌ **Нет.** Правильно: {q['options'][q['correct']]}\n\n💡 {q['explanation']}", parse_mode=None)
    attempt["index"] += 1
    await async_save_progress(uid, progress)
    if attempt["index"] < attempt["total"]:
        q_next = attempt["questions"][attempt["index"]]
        code = f"```\n{q_next['code']}\n```" if q_next.get("code") else ""
        text = f"❓ {q_next['question']}\n\n{code}\n\n" + "\n".join([f"{i+1}. {opt}" for i, opt in enumerate(q_next["options"])])
        await callback.message.answer(text, parse_mode=None, reply_markup=get_answer_buttons())
    else:
        await finish_quiz(callback.message, uid, lang, attempt)

async def finish_quiz(message, uid, lang, attempt):
    correct = attempt["correct"]
    total = attempt["total"]
    score = correct / total
    time_spent = int(datetime.now().timestamp() - attempt.get("start_time", 0))
    progress = load_progress(uid)
    lang_data = ensure_user_data(progress, lang)
    lang_data["current_attempt"] = None
    
    lang_data["total_answered"] = lang_data.get("total_answered", 0) + total
    lang_data["total_correct"] = lang_data.get("total_correct", 0) + correct
    
    old_xp = lang_data.get("xp", 0)
    base_xp = int(score * 100)
    time_bonus = 20 if time_spent < 120 else 0
    new_xp = old_xp + base_xp + time_bonus
    
    earned = []
    achieved_ids = [a["id"] for a in lang_data.get("achievements", [])]
    if "first_block" not in achieved_ids and len(lang_data.get("completed_blocks", [])) == 0: earned.append(ACHIEVEMENTS["first_block"])
    if "perfect_block" not in achieved_ids and score == 1.0: earned.append(ACHIEVEMENTS["perfect_block"])
    if "speed_demon" not in achieved_ids and time_spent < 120: earned.append(ACHIEVEMENTS["speed_demon"])
    
    for ach in earned:
        if ach["id"] not in achieved_ids:
            lang_data.setdefault("achievements", []).append({"id": ach["id"], "earned_at": datetime.now().isoformat()})
            new_xp += ach["xp"]
    
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
    
    msg = (f"🏁 **Готово!**\n✅ {correct}/{total}\n📊 {score*100:.0f}%\n⏱️ {time_spent}с\n💎 XP: +{base_xp + time_bonus}\n🎯 **Точность: {accuracy:.1f}%**")
    if earned: msg += "\n\n🏆 **ДОСТИЖЕНИЯ:**\n" + "\n".join([f"{a['name']} (+{a['xp']} XP)" for a in earned])
    if leveled_up: msg += f"\n\n🆙 **НОВЫЙ УРОВЕНЬ!**\n{new_level[1]}"
    await message.answer(msg, parse_mode=None)
    await show_main_menu(message, uid, lang)

@dp.message(lambda m: m.text == "⚙️ Админка")
async def admin_panel(message: Message):
    uid = message.from_user.id
    if not is_admin(uid): return await message.answer("❌ Доступ запрещён")
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Добавить вопрос", callback_data="admin_add")],
        [InlineKeyboardButton(text="📊 Статистика ID", callback_data="admin_stats_req")],
        [InlineKeyboardButton(text="🧹 Сброс прогресса", callback_data="admin_reset")],
        [InlineKeyboardButton(text="🔙 В меню", callback_data="admin_back")]
    ])
    await message.answer("🔧 **Админ-панель**", reply_markup=keyboard)

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
    await callback.message.answer("♻️ **Прогресс сброшен!**")
    await show_main_menu(callback.message, uid, lang)

@dp.callback_query(lambda c: c.data == "admin_stats_req")
async def admin_stats_req(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await callback.message.answer("🆔 **Введите ID пользователя:**")
    await state.set_state(AdminStates.waiting_for_stats_id)

@dp.message(AdminStates.waiting_for_stats_id)
async def admin_show_stats(message: Message, state: FSMContext):
    try:
        target_uid = int(message.text)
    except:
        await message.answer("❌ Введите числовой ID."); return
    
    profile = get_user_profile(target_uid)
    if not profile:
        await message.answer("❌ Пользователь не найден."); return
    
    progress = load_progress(target_uid)
    lang = profile.get("language")
    lang_data = ensure_user_data(progress, lang) if lang else {}
    
    xp = lang_data.get("xp", 0)
    level = get_level(xp)
    completed = len(lang_data.get("completed_blocks", []))
    total_ans = lang_data.get("total_answered", 0)
    total_corr = lang_data.get("total_correct", 0)
    accuracy = (total_corr / total_ans * 100) if total_ans > 0 else 0
    
    msg = (f"👤 **Профиль #{target_uid}**\n"
           f"📛 {profile.get('first_name') or '—'}\n"
           f"🌐 Язык: {lang or '—'}\n"
           f"🏅 Уровень: {level[1]} ({xp} XP)\n"
           f"📚 Блоков: {completed}\n"
           f"🎯 Точность: {accuracy:.1f}%\n"
           f"📊 Ответов: {total_ans}")
    
    await message.answer(msg, parse_mode=None)
    await state.clear()

@dp.callback_query(lambda c: c.data == "admin_add")
async def admin_add_start(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    langs = list(set(b.get("language") for b in DATA.get("blocks", [])))
    keyboard = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=l, callback_data=f"admin_add_lang_{l}")] for l in langs])
    await callback.message.edit_text("📚 **Выбери язык:**", reply_markup=keyboard)
    await state.set_state(AdminStates.adding_q_lang)

@dp.callback_query(AdminStates.adding_q_lang, lambda c: c.data.startswith("admin_add_lang_"))
async def admin_add_lang(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    lang = callback.data.split("_")[-1]
    await state.update_data(lang=lang)
    blocks = [b for b in DATA.get("blocks", []) if b.get("language") == lang]
    keyboard = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=f"#{b['id']} {b['title'][:15]}", callback_data=f"admin_add_block_{b['id']}")] for b in blocks])
    await callback.message.edit_text(f"📦 **Блоки ({lang}):**", reply_markup=keyboard)
    await state.set_state(AdminStates.adding_q_block)

@dp.callback_query(AdminStates.adding_q_block, lambda c: c.data.startswith("admin_add_block_"))
async def admin_add_block(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    block_id = int(callback.data.split("_")[-1])
    await state.update_data(block_id=block_id)
    await callback.message.answer("📝 **Введите текст вопроса:**")
    await state.set_state(AdminStates.adding_q_text)

@dp.message(AdminStates.adding_q_text)
async def admin_add_text(message: Message, state: FSMContext):
    await state.update_data(question=message.text)
    await message.answer("🔤 **Варианты (через запятую):**\nПример: `A,B,C`")
    await state.set_state(AdminStates.adding_q_options)

@dp.message(AdminStates.adding_q_options)
async def admin_add_options(message: Message, state: FSMContext):
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
        await message.answer("💡 **Пояснение (или '-'):**")
        await state.set_state(AdminStates.adding_q_explanation)
    except: await message.answer("❌ Ошибка ввода.")

@dp.message(AdminStates.adding_q_explanation)
async def admin_add_finish(message: Message, state: FSMContext):
    data = await state.get_data()
    new_q = {
        "question": data["question"],
        "options": data["options"],
        "correct": data["correct"],
        "explanation": message.text if message.text != "-" else "",
        "code": ""
    }
    
    success = add_question_to_block(data["block_id"], new_q)
    
    if success:
        reload_data()  # 🔥 КЛЮЧЕВОЕ ИСПРАВЛЕНИЕ: обновляем память бота
        await message.answer(f"✅ **Вопрос добавлен в блок #{data['block_id']}!**\n💾 Появится в тестах сразу.")
    else:
        await message.answer("❌ Ошибка при сохранении вопроса.")
    
    await state.clear()
    keyboard = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="➕ Ещё", callback_data="admin_add")], [InlineKeyboardButton(text="🔙 В меню", callback_data="admin_back")]])
    await message.answer("🔧 **Админка**", reply_markup=keyboard)

@dp.message(~StateFilter('*'))
async def handle_unknown(message: Message):
    lang = load_user_language(message.from_user.id)
    if lang:
        await message.answer("❓ Используй кнопки или /start", reply_markup=get_main_keyboard(message.from_user.id))
    else:
        await message.answer("👋 Нажми /start", reply_markup=ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="/start")]], resize_keyboard=True))

async def main():
    init_db()
    print("✅ Бот запущен.")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())