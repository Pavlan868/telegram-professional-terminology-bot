# main.py
# Версия 3.4: Полностью исправленная
import asyncio
import json
import logging
import os
import random
import signal
import sys
from asyncio import Lock
from datetime import datetime
from typing import Optional, Dict, Any

from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    Message, CallbackQuery, ReplyKeyboardMarkup, KeyboardButton,
    InlineKeyboardMarkup, InlineKeyboardButton
)

# Импортируем config - создай файл config.py или закомментируй эти строки
try:
    from config import BOT_TOKEN, ADMIN_IDS, UNLOCK_THRESHOLD
except ImportError:
    BOT_TOKEN = os.getenv("BOT_TOKEN", "")
    ADMIN_IDS = [int(x) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip().isdigit()]
    UNLOCK_THRESHOLD = float(os.getenv("UNLOCK_THRESHOLD", "0.8"))

from database import (
    init_db, register_user, get_user_profile, save_user_language, load_user_language,
    load_progress, save_progress, add_question_to_block, get_block_by_id,
    get_all_blocks_by_language, get_all_users_count, get_users_by_language
)

# === LOGGING ===
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[logging.FileHandler("bot.log", encoding="utf-8"), logging.StreamHandler()]
)
logger = logging.getLogger(__name__)

# === INIT ===
if not BOT_TOKEN:
    raise RuntimeError("❌ BOT_TOKEN не задан! Проверьте config.py или переменные окружения")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

try:
    with open("data.json", "r", encoding="utf-8") as f:
        DATA = json.load(f)
    logger.info(f"✓ Загружено {len(DATA.get('blocks', []))} учебных блоков")
except Exception as e:
    logger.error(f"❌ Ошибка загрузки data.json: {e}")
    DATA = {"blocks": []}

FIRST_BLOCK_ID = {"Python": 1, "C++": 6, "Java": 11, "JavaScript": 16, "Git": 21}
_user_locks: Dict[int, Lock] = {}

# === GAMIFICATION: ACHIEVEMENTS ===
ACHIEVEMENTS = {
    "first_block": {"id": "first_block", "name": "🌟 Первый шаг", "description": "Пройти первый блок", "icon": "🎯", "xp_reward": 50, "hidden": False},
    "perfect_block": {"id": "perfect_block", "name": "💎 Идеально!", "description": "Пройти блок без ошибок", "icon": "✨", "xp_reward": 100, "hidden": False},
    "speed_demon": {"id": "speed_demon", "name": "⚡ Скорострел", "description": "Пройти блок быстрее 2 минут", "icon": "💨", "xp_reward": 75, "hidden": False},
    "marathon": {"id": "marathon", "name": "🏃 Марафонец", "description": "Пройти 5 блоков подряд", "icon": "🏆", "xp_reward": 200, "hidden": False},
    "polyglot": {"id": "polyglot", "name": "🌍 Полиглот", "description": "Освоить 3 языка", "icon": "🎓", "xp_reward": 300, "hidden": False},
    "night_owl": {"id": "night_owl", "name": "🦉 Ночной программист", "description": "Учиться после 23:00", "icon": "🌙", "xp_reward": 50, "hidden": True},
    "early_bird": {"id": "early_bird", "name": "🐦 Ранняя пташка", "description": "Учиться до 7:00", "icon": "🌅", "xp_reward": 50, "hidden": True},
    "perfectionist": {"id": "perfectionist", "name": "💯 Перфекционист", "description": "10 блоков с 100% точностью", "icon": "👑", "xp_reward": 500, "hidden": False},
    "master_lang": {"id": "master_lang", "name": "🎖️ Мастер языка", "description": "Пройти все блоки языка", "icon": "🏅", "xp_reward": 400, "hidden": False},
    "legend": {"id": "legend", "name": "👑 ЛЕГЕНДА", "description": "Пройти ВСЕ блоки всех языков", "icon": "🏆", "xp_reward": 1000, "hidden": True}
}

# === LEVELS ===
LEVELS = [
    (0, "🌱 Новичок", "Только начинаешь путь"),
    (100, "📚 Студент", "Активно учишься"),
    (300, "⭐ Продвинутый", "Хорошие знания"),
    (600, "🎓 Эксперт", "Отличное понимание"),
    (1000, "🏆 Мастер", "Профессиональный уровень"),
    (1500, "💎 Гуру", "Глубокие знания"),
    (2500, "👑 Легенда", "Непревзойдённый мастер")
]

def get_level_by_xp(xp: int) -> tuple:
    current = LEVELS[0]
    for threshold, name, desc in LEVELS:
        if xp >= threshold:
            current = (threshold, name, desc)
        else:
            break
    return current

def get_next_level_xp(xp: int) -> Optional[int]:
    for threshold, _, _ in LEVELS[1:]:
        if xp < threshold:
            return threshold
    return None

def get_progress_bar(current: int, total: int, length: int = 10) -> str:
    if total <= 0:
        return f"{'░' * length} 0%"
    filled = int(length * current / total)
    percent = int((current / total) * 100)
    return f"{'█' * filled}{'░' * (length - filled)} {percent}%"

def get_daily_bonus(user_data: Dict) -> tuple:
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

def check_achievements(progress: Dict, lang: str, block_id: int, score: float, time_spent: int, lang_data: Dict) -> list:
    earned = []
    achieved_ids = [a["id"] for a in lang_data.get("achievements", [])]
    
    if "first_block" not in achieved_ids and len(progress.get(lang, {}).get("completed_blocks", [])) == 1:
        earned.append(ACHIEVEMENTS["first_block"])
    if "perfect_block" not in achieved_ids and score == 1.0:
        earned.append(ACHIEVEMENTS["perfect_block"])
    if "speed_demon" not in achieved_ids and time_spent < 120:
        earned.append(ACHIEVEMENTS["speed_demon"])
    if "marathon" not in achieved_ids and len(progress.get(lang, {}).get("completed_blocks", [])) >= 5:
        earned.append(ACHIEVEMENTS["marathon"])
    
    langs_with_blocks = [l for l in progress if len(progress[l].get("completed_blocks", [])) > 0]
    if "polyglot" not in achieved_ids and len(langs_with_blocks) >= 3:
        earned.append(ACHIEVEMENTS["polyglot"])
    
    hour = datetime.now().hour
    if "night_owl" not in achieved_ids and hour >= 23:
        earned.append(ACHIEVEMENTS["night_owl"])
    if "early_bird" not in achieved_ids and hour < 7:
        earned.append(ACHIEVEMENTS["early_bird"])
    
    perfect_count = sum(1 for a in lang_data.get("achievements", []) if a["id"] == "perfect_block")
    if "perfectionist" not in achieved_ids and perfect_count >= 10:
        earned.append(ACHIEVEMENTS["perfectionist"])
    
    if "master_lang" not in achieved_ids:
        lang_blocks = [b["id"] for b in DATA.get("blocks", []) if b.get("language") == lang]
        if lang_blocks and all(bid in progress.get(lang, {}).get("completed_blocks", []) for bid in lang_blocks):
            earned.append(ACHIEVEMENTS["master_lang"])
    
    all_blocks_ids = [b["id"] for b in DATA.get("blocks", [])]
    all_completed = []
    for l in progress:
        all_completed.extend(progress[l].get("completed_blocks", []))
    if "legend" not in achieved_ids and set(all_blocks_ids).issubset(set(all_completed)):
        earned.append(ACHIEVEMENTS["legend"])
    
    return earned

# === HELPERS ===
def get_user_lock(user_id: int) -> Lock:
    if user_id not in _user_locks:
        _user_locks[user_id] = Lock()
    return _user_locks[user_id]

async def async_load_progress(user_id: int) -> Dict:
    return await asyncio.to_thread(load_progress, user_id)

async def async_save_progress(user_id: int, progress_data: dict):
    lock = get_user_lock(user_id)
    async with lock:
        await asyncio.to_thread(save_progress, user_id, progress_data)

# === GLOBAL ERROR HANDLER ===
@dp.errors()
async def global_error_handler(update: types.Update, exception: Exception):
    logger.error(f"💥 [GLOBAL ERROR] {exception.__class__.__name__}: {exception}", exc_info=True)
    try:
        if isinstance(update, types.Message):
            await update.answer("⚠️ Техническая ошибка. Попробуйте /start.")
        elif isinstance(update, types.CallbackQuery):
            await update.answer("⚠️ Ошибка обработки", show_alert=True)
    except Exception as e:
        logger.warning(f"⚠️ Не удалось отправить сообщение об ошибке: {e}")
    return True

# === KEYBOARDS ===
def get_main_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="📚 Обучение"), KeyboardButton(text="🧠 Задание")],
        [KeyboardButton(text="🔁 Повторить обучение"), KeyboardButton(text="🧪 Повторить тест")],
        [KeyboardButton(text="🏆 Достижения"), KeyboardButton(text="👤 Профиль")],
        [KeyboardButton(text="⚙️ Настройки")]], resize_keyboard=True)

def get_language_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text=lang)] for lang in FIRST_BLOCK_ID.keys()],
                               resize_keyboard=True, one_time_keyboard=True)

# === START & REGISTRATION ===
@dp.message(Command("start"))
async def cmd_start(message: Message):
    user = message.from_user
    register_user(user.id, user.username, user.first_name, user.last_name)
    logger.info(f"👤 User {user.id} started bot")
    
    lang = load_user_language(user.id)
    if not lang:
        await message.answer(
            f"👋 <b>Привет, {user.first_name or 'Пользователь'}!</b>\n\n"
            f"🎓 Я помогу освоить профессиональную терминологию в программировании.\n"
            f"🎮 Зарабатывай XP, получай достижения, повышай уровень!\n\n"
            f"📌 <b>Выбери язык для старта:</b>",
            reply_markup=get_language_keyboard(), parse_mode="HTML"
        )
    else:
        await show_main_menu(message, user.id, lang)

@dp.message(F.text.in_(FIRST_BLOCK_ID.keys()))
async def handle_language_selection(message: Message):
    user_id = message.from_user.id
    selected_lang = message.text.strip()
    save_user_language(user_id, selected_lang)
    
    progress = await async_load_progress(user_id)
    
    if selected_lang not in progress:
        progress[selected_lang] = {
            "current_block": FIRST_BLOCK_ID[selected_lang],
            "completed_blocks": [],
            "current_attempt": None,
            "xp": 0,
            "achievements": [],
            "login_streak": 0,
            "last_login_date": None
        }
    
    user_data = progress[selected_lang]
    
    for key in ["xp", "achievements", "login_streak", "last_login_date"]:
        if key not in user_data:
            user_data[key] = 0 if key == "xp" else [] if key == "achievements" else 0 if key == "login_streak" else None
    
    bonus, streak, is_new = get_daily_bonus(user_data)
    
    msg = f"✅ <b>Выбран язык: {selected_lang}</b>\n\n"
    if is_new and bonus > 0:
        msg += f"🎁 <b>Ежедневный бонус!</b>\n"
        msg += f"🔥 Серия дней: {streak}\n"
        msg += f"💎 +{bonus} XP\n\n"
        user_data["last_login_date"] = datetime.now().strftime("%Y-%m-%d")
        user_data["login_streak"] = streak
        user_data["xp"] = user_data.get("xp", 0) + bonus
    
    msg += "📚 Начни обучение или проверь знания!"
    await async_save_progress(user_id, progress)
    await message.answer(msg, parse_mode="HTML", reply_markup=get_main_keyboard())
    logger.info(f"🔤 User {user_id} selected {selected_lang}")

async def show_main_menu(message: Message, user_id: int, lang: str):
    progress = await async_load_progress(user_id)
    lang_data = progress.get(lang, {})
    
    xp = lang_data.get("xp", 0)
    level_info = get_level_by_xp(xp)
    next_xp = get_next_level_xp(xp)
    completed = len(lang_data.get("completed_blocks", []))
    achievements_count = len(lang_data.get("achievements", []))
    
    if next_xp:
        current_level_xp = level_info[0]
        progress_in_level = xp - current_level_xp
        total_to_next = next_xp - current_level_xp
        bar = get_progress_bar(progress_in_level, total_to_next)
    else:
        bar = "░░░░░░░░░░ MAX"
    
    profile = get_user_profile(user_id)
    name = profile.get("first_name", "Пользователь") if profile else "Пользователь"
    
    msg = (f"📖 <b>Меню обучения ({lang})</b>\n\n"
           f"👤 {name}\n"
           f"🏅 {level_info[1]} ({level_info[0]} XP)\n"
           f"{bar}\n\n"
           f"📊 <b>Статистика:</b>\n"
           f"📚 Пройдено блоков: {completed}\n"
           f"🏆 Достижений: {achievements_count}\n"
           f"🔥 Серия дней: {lang_data.get('login_streak', 0)}\n\n"
           f"Выбери режим:")
    
    await message.answer(msg, parse_mode="HTML", reply_markup=get_main_keyboard())

# === 📚 ОБУЧЕНИЕ ===
@dp.message(F.text == "📚 Обучение")
async def handle_study_mode(message: Message):
    user_id = message.from_user.id
    lang = load_user_language(user_id)
    if not lang:
        await message.answer("⚠️ Сначала выберите язык программирования командой /start")
        return
    
    progress = await async_load_progress(user_id)
    lang_data = progress.get(lang, {})
    current_block_id = lang_data.get("current_block", FIRST_BLOCK_ID[lang])
    
    block = next((b for b in DATA["blocks"] if b["id"] == current_block_id), None)
    if not block:
        await message.answer("❌ Блок обучения не найден")
        return
    
    terms = block.get("terms", [])
    terms_text = "\n\n".join([f"🔹 <b>{t['term']}</b>\n{t.get('definition', '')}" for t in terms]) if terms else "📭 В этом блоке пока нет терминов"
    
    await message.answer(
        f"📚 <b>{block['title']}</b>\n\n"
        f"{block.get('description', '')}\n\n"
        f"{terms_text}\n\n"
        f"💡 Когда изучишь материал — переходи в раздел «🧠 Задание»",
        parse_mode="HTML"
    )

# === 🔁 ПОВТОРИТЬ ОБУЧЕНИЕ ===
@dp.message(F.text == "🔁 Повторить обучение")
async def repeat_study(message: Message):
    user_id = message.from_user.id
    lang = load_user_language(user_id)
    if not lang:
        await message.answer("⚠️ Выберите язык командой /start")
        return
    
    progress = await async_load_progress(user_id)
    lang_data = progress.get(lang, {})
    completed_blocks = lang_data.get("completed_blocks", [])
    current_block = lang_data.get("current_block", FIRST_BLOCK_ID[lang])
    
    all_blocks = get_all_blocks_by_language(lang)
    available = [b for b in all_blocks if b["id"] in completed_blocks or b["id"] == current_block]
    
    if not available:
        await message.answer("📭 Пока нет пройденных блоков. Сначала пройдите тест в разделе 🧠 Задание!")
        return
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text=f"{'✅' if b['id'] in completed_blocks else '📖'} #{b['id']} | {b['title']}",
            callback_data=f"repeat_block_{b['id']}"
        )] for b in available
    ])
    
    await message.answer(
        f"📚 <b>Повторение теории</b>\n\n"
        f"Выберите блок для просмотра:\n"
        f"✅ — пройдено\n"
        f"📖 — текущий",
        parse_mode="HTML", reply_markup=keyboard
    )

@dp.callback_query(F.data.startswith("repeat_block_"))
async def show_repeat_block(callback: CallbackQuery):
    await callback.answer()
    try:
        block_id = int(callback.data.split("_")[-1])
    except ValueError:
        await callback.message.edit_text("❌ Ошибка")
        return
    
    block = get_block_by_id(block_id)
    if not block:
        await callback.message.edit_text("❌ Блок не найден")
        return
    
    terms = block.get("terms", [])
    terms_text = "\n\n".join([f"🔹 <b>{t['term']}</b>\n{t.get('definition', '')}" for t in terms]) if terms else "📭"
    
    await callback.message.edit_text(
        f"📖 <b>{block['title']}</b> (ПОВТОРЕНИЕ)\n\n"
        f"{block.get('description', '')}\n\n"
        f"{terms_text}\n\n"
        f"💡 Вспомнил? Переходи в 🧠 Задание",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📋 К списку", callback_data="repeat_study_list")]
        ])
    )

@dp.callback_query(F.data == "repeat_study_list")
async def back_to_repeat_list(callback: CallbackQuery):
    await callback.answer()
    await repeat_study(callback.message)

# === 🧠 ЗАДАНИЕ ===
@dp.message(F.text == "🧠 Задание")
async def handle_quiz_mode(message: Message):
    user_id = message.from_user.id
    lang = load_user_language(user_id)
    if not lang:
        await message.answer("⚠️ Сначала выберите язык командой /start")
        return
    
    progress = await async_load_progress(user_id)
    lang_data = progress.get(lang, {})
    
    if lang_data.get("current_attempt"):
        await message.answer("❗ Сначала завершите текущий тест")
        return
    
    current_block_id = lang_data.get("current_block", FIRST_BLOCK_ID[lang])
    block = next((b for b in DATA["blocks"] if b["id"] == current_block_id), None)
    if not block:
        await message.answer("❌ Блок не найден")
        return
    
    tasks = block.get("tasks", [])
    if not tasks:
        await message.answer("📭 В этом блоке пока нет заданий")
        return
    
    attempt = {
        "block_id": current_block_id,
        "questions": random.sample(tasks, min(len(tasks), 5)),
        "current": 0,
        "correct": 0,
        "answers": [],
        "start_time": datetime.now().timestamp()
    }
    
    lang_data["current_attempt"] = attempt
    await async_save_progress(user_id, progress)
    await send_question(message, user_id, lang, attempt)

async def send_question(message: Message, user_id: int, lang: str, attempt: dict):
    idx = attempt["current"]
    questions = attempt["questions"]
    
    if idx >= len(questions):
        await finish_quiz(message, user_id, lang, attempt)
        return
    
    q = questions[idx]
    text = f"❓ <b>Вопрос {idx + 1}/{len(questions)}</b>\n\n{q['question']}"
    if q.get("code"):
        text += f"\n\n<code>{q['code']}</code>"
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"{i+1}. {opt}", callback_data=f"ans_{i}")]
        for i, opt in enumerate(q["options"])
    ])
    
    await message.answer(text, parse_mode="HTML", reply_markup=keyboard)

@dp.callback_query(F.data.startswith("ans_"))
async def handle_answer(callback: CallbackQuery):
    await callback.answer()
    user_id = callback.from_user.id
    lang = load_user_language(user_id)
    if not lang:
        return
    
    progress = await async_load_progress(user_id)
    lang_data = progress.get(lang, {})
    attempt = lang_data.get("current_attempt")
    
    if not attempt:
        await callback.message.edit_text("❌ Активная попытка не найдена")
        return
    
    try:
        answer_idx = int(callback.data.split("_")[1])
    except (IndexError, ValueError):
        await callback.answer("❌ Неверный формат ответа", show_alert=True)
        return
    
    q = attempt["questions"][attempt["current"]]
    is_correct = (answer_idx == q["correct"])
    
    attempt["answers"].append({"correct": is_correct})
    if is_correct:
        attempt["correct"] += 1
    
    streak = sum(1 for a in attempt["answers"][-3:] if a["correct"]) if len(attempt["answers"]) >= 3 else 0
    combo_text = f"\n\n🔥 <b>COMBO x{streak}!</b>" if streak >= 3 else ""
    
    feedback = "✅ Верно!" if is_correct else f"❌ Неверно.\n💡 {q.get('explanation', 'Изучи материал ещё раз')}"
    feedback += combo_text
    
    attempt["current"] += 1
    lang_data["current_attempt"] = attempt
    await async_save_progress(user_id, progress)
    
    if attempt["current"] < len(attempt["questions"]):
        await callback.message.edit_text(f"{feedback}\n\n➡️ Следующий вопрос...")
        await asyncio.sleep(1)
        await send_question(callback.message, user_id, lang, attempt)
    else:
        await callback.message.edit_text(f"{feedback}\n\n⏳ Подсчёт результатов...")
        await finish_quiz(callback.message, user_id, lang, attempt)

async def finish_quiz(message: Message, user_id: int, lang: str, attempt: dict):
    total = len(attempt["questions"])
    correct = attempt["correct"]
    score = correct / total if total > 0 else 0
    time_spent = int(datetime.now().timestamp() - attempt.get("start_time", 0))
    
    progress = await async_load_progress(user_id)
    lang_data = progress.get(lang, {})
    lang_data["current_attempt"] = None
    
    old_xp = lang_data.get("xp", 0)
    base_xp = int(score * 100)
    time_bonus = 20 if time_spent < 120 else 0
    new_xp = old_xp + base_xp + time_bonus
    
    old_level = get_level_by_xp(old_xp)
    leveled_up = False
    
    earned_achievements = check_achievements(progress, lang, attempt["block_id"], score, time_spent, lang_data)
    
    for ach in earned_achievements:
        if ach["id"] not in [a["id"] for a in lang_data.get("achievements", [])]:
            lang_data.setdefault("achievements", []).append({
                "id": ach["id"],
                "earned_at": datetime.now().isoformat()
            })
            new_xp += ach["xp_reward"]
    
    new_level = get_level_by_xp(new_xp)
    if old_level[0] != new_level[0]:
        leveled_up = True
    
    lang_data["xp"] = new_xp
    
    if attempt["block_id"] not in lang_data.get("completed_blocks", []):
        lang_data.setdefault("completed_blocks", []).append(attempt["block_id"])
    
    next_id = attempt["block_id"] + 1
    if next_id in [b["id"] for b in DATA["blocks"]] and score >= UNLOCK_THRESHOLD:
        lang_data["current_block"] = next_id
    
    await async_save_progress(user_id, progress)
    
    msg = (f"🏁 <b>Тест завершён!</b>\n\n"
           f"✅ Правильных ответов: {correct} из {total}\n"
           f"📊 Результат: {score*100:.1f}%\n"
           f"⏱️ Время: {time_spent}с\n"
           f"💎 Получено XP: +{base_xp + time_bonus}")
    
    if earned_achievements:
        msg += "\n\n🏆 <b>НОВЫЕ ДОСТИЖЕНИЯ:</b>\n"
        for ach in earned_achievements:
            msg += f"{ach['icon']} {ach['name']} (+{ach['xp_reward']} XP)\n"
    
    if leveled_up:
        msg += f"\n\n🆙 <b>НОВЫЙ УРОВЕНЬ!</b>\n"
        msg += f"🎉 {new_level[1]}\n"
        msg += f"📝 {new_level[2]}"
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔁 Пройти ещё раз", callback_data="retry_quiz")],
        [InlineKeyboardButton(text="📚 К теории", callback_data="back_to_study")]
    ])
    
    await message.answer(msg, parse_mode="HTML", reply_markup=keyboard)

@dp.callback_query(F.data == "retry_quiz")
async def retry_quiz_handler(callback: CallbackQuery):
    await callback.answer()
    await handle_quiz_mode(callback.message)

@dp.callback_query(F.data == "back_to_study")
async def back_to_study_handler(callback: CallbackQuery):
    await callback.answer()
    user_id = callback.from_user.id
    lang = load_user_language(user_id)
    if not lang:
        await callback.message.answer("⚠️ /start")
        return
    
    progress = await async_load_progress(user_id)
    lang_data = progress.get(lang, {})
    current_block_id = lang_data.get("current_block", FIRST_BLOCK_ID[lang])
    
    block = next((b for b in DATA["blocks"] if b["id"] == current_block_id), None)
    if not block:
        await callback.message.edit_text("❌ Блок не найден")
        return
    
    terms = block.get("terms", [])
    terms_text = "\n\n".join([f"🔹 <b>{t['term']}</b>\n{t.get('definition', '')}" for t in terms]) if terms else "📭"
    
    await callback.message.edit_text(
        f"📚 <b>{block['title']}</b>\n\n"
        f"{block.get('description', '')}\n\n"
        f"{terms_text}\n\n"
        f"💡 Изучил? Переходи в 🧠 Задание",
        parse_mode="HTML"
    )

@dp.message(F.text == "🧪 Повторить тест")
async def repeat_quiz(message: Message):
    user_id = message.from_user.id
    lang = load_user_language(user_id)
    if not lang:
        await message.answer("⚠️ Выберите язык командой /start")
        return
    
    progress = await async_load_progress(user_id)
    if lang in progress:
        progress[lang]["current_attempt"] = None
        await async_save_progress(user_id, progress)
    
    await handle_quiz_mode(message)

# === 🏆 ДОСТИЖЕНИЯ ===
@dp.message(F.text == "🏆 Достижения")
async def show_achievements(message: Message):
    user_id = message.from_user.id
    lang = load_user_language(user_id)
    if not lang:
        await message.answer("⚠️ /start")
        return
    
    progress = await async_load_progress(user_id)
    lang_data = progress.get(lang, {})
    earned_ids = [a["id"] for a in lang_data.get("achievements", [])]
    
    msg = "🏆 <b>ДОСТИЖЕНИЯ</b>\n\n"
    
    for ach_id in earned_ids:
        if ach_id in ACHIEVEMENTS:
            ach = ACHIEVEMENTS[ach_id]
            msg += f"{ach['icon']} <b>{ach['name']}</b>\n{ach['description']}\n\n"
    
    msg += "\n🔒 <b>Заблокировано:</b>\n\n"
    for ach_id, ach in ACHIEVEMENTS.items():
        if ach_id not in earned_ids:
            if ach.get("hidden"):
                msg += "❓ <i>???</i>\n"
            else:
                msg += f"🔒 {ach['name']}\n{ach['description']}\n\n"
    
    await message.answer(msg, parse_mode="HTML")

# === 👤 ПРОФИЛЬ ===
@dp.message(F.text == "👤 Профиль")
async def show_profile(message: Message):
    user_id = message.from_user.id
    profile = get_user_profile(user_id)
    lang = load_user_language(user_id)
    
    if not profile:
        await message.answer("❌ Профиль не найден. Попробуйте /start")
        return
    
    progress = await async_load_progress(user_id)
    lang_data = progress.get(lang, {}) if lang else {}
    
    xp = lang_data.get("xp", 0)
    level_info = get_level_by_xp(xp)
    completed = len(lang_data.get("completed_blocks", []))
    achievements = len(lang_data.get("achievements", []))
    streak = lang_data.get("login_streak", 0)
    
    msg = (f"👤 <b>Ваш профиль</b>\n\n"
           f"📛 {profile.get('first_name', 'Пользователь')}\n"
           f"🆔 <code>{user_id}</code>\n"
           f"🌐 Язык: {lang or 'не выбран'}\n\n"
           f"📊 <b>Прогресс:</b>\n"
           f"🏅 {level_info[1]} ({level_info[0]} XP)\n"
           f"📚 Пройдено блоков: {completed}\n"
           f"🏆 Достижений: {achievements}\n"
           f"🔥 Серия дней: {streak}\n\n"
           f"📝 {level_info[2]}")
    
    await message.answer(msg, parse_mode="HTML")

# === ⚙️ НАСТРОЙКИ ===
@dp.message(F.text == "⚙️ Настройки")
async def show_settings(message: Message):
    await message.answer(
        "⚙️ <b>Настройки:</b>\n\n"
        "• /start — сменить язык обучения\n"
        "• /admin — панель администратора (если есть доступ)\n"
        "• Напишите разработчику: @Pavlan868",
        parse_mode="HTML"
    )

# === ADMIN PANEL ===
def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS

@dp.message(Command("admin"))
async def cmd_admin(message: Message):
    if not is_admin(message.from_user.id):
        logger.warning(f"⚠️ Несанкционированный доступ к /admin от user_id={message.from_user.id}")
        await message.answer("❌ Доступ запрещён")
        return
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Добавить вопрос", callback_data="admin_add")],
        [InlineKeyboardButton(text="📊 Статистика", callback_data="admin_stats")]
    ])
    
    await message.answer("🔧 <b>Панель администратора</b>", reply_markup=keyboard, parse_mode="HTML")

class AdminAddQuestion(StatesGroup):
    entering_question = State()
    entering_options = State()
    entering_correct = State()
    entering_explanation = State()

@dp.callback_query(F.data == "admin_add")
async def admin_add_start(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    langs = list(set(b.get("language") for b in DATA.get("blocks", [])))
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=lang, callback_data=f"admin_add_lang_{lang}")] for lang in langs
    ])
    await callback.message.edit_text("📚 Выберите язык:", reply_markup=keyboard)

@dp.callback_query(F.data.startswith("admin_add_lang_"))
async def admin_select_block(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    lang = callback.data.split("_")[-1]
    blocks = get_all_blocks_by_language(lang)
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"#{b['id']}: {b['title'][:25]}", callback_data=f"admin_add_block_{b['id']}")]
        for b in blocks[:10]
    ])
    await state.update_data(admin_lang=lang)
    await callback.message.edit_text(f"📦 Выберите блок ({lang}):", reply_markup=keyboard)

@dp.callback_query(F.data.startswith("admin_add_block_"))
async def admin_enter_question(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    block_id = int(callback.data.split("_")[-1])
    await state.update_data(admin_block_id=block_id)
    await state.set_state(AdminAddQuestion.entering_question)
    await callback.message.edit_text("❓ <b>Введите текст вопроса:</b>", parse_mode="HTML")

@dp.message(AdminAddQuestion.entering_question)
async def admin_save_question(message: Message, state: FSMContext):
    await state.update_data(question_text=message.text)
    await state.set_state(AdminAddQuestion.entering_options)
    await message.answer("🔤 <b>Варианты ответов:</b>\nОтправьте через запятую:\n<code>Ответ 1,Ответ 2,Ответ 3</code>", parse_mode="HTML")

@dp.message(AdminAddQuestion.entering_options)
async def admin_save_options(message: Message, state: FSMContext):
    options = [opt.strip() for opt in message.text.split(",") if opt.strip()]
    if len(options) < 2:
        await message.answer("❌ Нужно минимум 2 варианта. Попробуйте снова:")
        return
    
    await state.update_data(options=options)
    await state.set_state(AdminAddQuestion.entering_correct)
    
    opts_str = "\n".join(f"{i+1}. {opt}" for i, opt in enumerate(options))
    await message.answer(f"✅ Варианты:\n{opts_str}\n\n🔢 <b>Введите номер правильного (1-{len(options)}):</b>", parse_mode="HTML")

@dp.message(AdminAddQuestion.entering_correct)
async def admin_save_correct(message: Message, state: FSMContext):
    try:
        correct_idx = int(message.text.strip()) - 1
        data = await state.get_data()
        options = data.get("options", [])
        
        if not (0 <= correct_idx < len(options)):
            await message.answer(f"❌ Введите число от 1 до {len(options)}")
            return
        
        await state.update_data(correct_index=correct_idx)
        await state.set_state(AdminAddQuestion.entering_explanation)
        await message.answer("💡 <b>Пояснение:</b>\nОтправьте текст или «-» для пропуска:")
        
    except ValueError:
        await message.answer("❌ Введите число")

@dp.message(AdminAddQuestion.entering_explanation)
async def admin_finish_add(message: Message, state: FSMContext):
    data = await state.get_data()
    
    question_payload = {
        "question": data.get("question_text", ""),
        "options": data.get("options", []),
        "correct": data.get("correct_index", 0),
        "explanation": message.text if message.text.strip() != "-" else "",
        "code": ""
    }
    
    success = add_question_to_block(data.get("admin_block_id"), question_payload)
    
    if success:
        await message.answer("✅ <b>Вопрос успешно добавлен!</b>", parse_mode="HTML")
        logger.info(f"🔧 Админ добавил вопрос в блок {data.get('admin_block_id')}")
    else:
        await message.answer("❌ Ошибка при сохранении вопроса")
    
    await state.clear()
    await cmd_admin(message)

@dp.callback_query(F.data == "admin_stats")
async def admin_show_stats(callback: CallbackQuery):
    await callback.answer()
    
    users_total = get_all_users_count()
    lang_stats = get_users_by_language()
    total_blocks = len(DATA.get("blocks", []))
    total_questions = sum(len(b.get("tasks", [])) for b in DATA.get("blocks", []))
    
    stats_text = (f"📊 <b>Статистика бота</b>\n\n"
                  f"👥 Пользователи: {users_total}\n"
                  f"📚 По языкам:\n")
    
    for lang, count in lang_stats.items():
        stats_text += f"  • {lang}: {count}\n"
    
    stats_text += f"\n📦 Контент:\n  • Блоков: {total_blocks}\n  • Вопросов: {total_questions}\n\n"
    stats_text += f"🔧 Админов: {len(ADMIN_IDS)}"
    
    await callback.message.answer(stats_text, parse_mode="HTML")

# === UNKNOWN MESSAGES ===
@dp.message()
async def handle_unknown(message: Message):
    user_id = message.from_user.id
    lang = load_user_language(user_id)
    
    current_state = await dp.storage.get_state(user_id=user_id)
    if current_state and current_state.startswith("Admin"):
        return
    
    if lang:
        await message.answer(
            "❓ Не распознано. Используйте кнопки меню:\n"
            "• /start — начать заново\n"
            "• /admin — панель администратора",
            reply_markup=get_main_keyboard()
        )
    else:
        await message.answer(
            "👋 Нажмите /start для начала работы",
            reply_markup=ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="/start")]], resize_keyboard=True)
        )

# === RUN ===
async def on_startup():
    logger.info("🚀 Бот запускается (v3.4)...")
    init_db()
    logger.info("✓ База данных инициализирована")
    
    for admin_id in ADMIN_IDS:
        try:
            await bot.send_message(admin_id, "✅ Бот запущен и готов к работе 🎮")
        except Exception as e:
            logger.warning(f"⚠️ Не удалось уведомить админа {admin_id}: {e}")

async def on_shutdown():
    logger.info("🛑 Бот завершает работу...")
    await bot.session.close()

async def main():
    dp.startup.register(on_startup)
    dp.shutdown.register(on_shutdown)
    
    if os.getenv("DISABLE_PORT_CHECK") == "true":
        logger.info("🔄 Render mode: polling active")
    
    logger.info("🔄 Запуск polling...")
    await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())

if __name__ == "__main__":
    def graceful_exit(signum, frame):
        logger.info("🛑 Получен сигнал завершения")
        sys.exit(0)
    
    signal.signal(signal.SIGTERM, graceful_exit)
    signal.signal(signal.SIGINT, graceful_exit)
    
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("👋 Остановка по Ctrl+C")
    except Exception as e:
        logger.error(f"💥 Критическая ошибка: {e}", exc_info=True)