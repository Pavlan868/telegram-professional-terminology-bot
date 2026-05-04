# main.py
# ФИНАЛЬНАЯ ВЕРСИЯ 4.1 - ИСПРАВЛЕНЫ ВСЕ ОШИБКИ
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

# === CONFIG ===
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
    raise RuntimeError("❌ BOT_TOKEN не задан!")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

try:
    with open("data.json", "r", encoding="utf-8") as f:
        DATA = json.load(f)
    logger.info(f"✓ Загружено {len(DATA.get('blocks', []))} блоков")
except Exception as e:
    logger.error(f"❌ Ошибка data.json: {e}")
    DATA = {"blocks": []}

FIRST_BLOCK_ID = {"Python": 1, "C++": 6, "Java": 11, "JavaScript": 16, "Git": 21}
_user_locks: Dict[int, Lock] = {}

# === ACHIEVEMENTS ===
ACHIEVEMENTS = {
    "first_block": {"id": "first_block", "name": "🌟 Первый шаг", "description": "Пройти первый блок", "icon": "🎯", "xp_reward": 50},
    "perfect_block": {"id": "perfect_block", "name": "💎 Идеально!", "description": "Пройти блок без ошибок", "icon": "✨", "xp_reward": 100},
    "speed_demon": {"id": "speed_demon", "name": "⚡ Скорострел", "description": "Пройти блок быстрее 2 минут", "icon": "💨", "xp_reward": 75},
    "marathon": {"id": "marathon", "name": "🏃 Марафонец", "description": "Пройти 5 блоков подряд", "icon": "🏆", "xp_reward": 200},
    "polyglot": {"id": "polyglot", "name": "🌍 Полиглот", "description": "Освоить 3 языка", "icon": "🎓", "xp_reward": 300},
}

# === LEVELS ===
LEVELS = [
    (0, "🌱 Новичок", "Только начинаешь"),
    (100, "📚 Студент", "Активно учишься"),
    (300, "⭐ Продвинутый", "Хорошие знания"),
    (600, "🎓 Эксперт", "Отличное понимание"),
    (1000, "🏆 Мастер", "Профессиональный уровень"),
    (2500, "👑 Легенда", "Непревзойдённый")
]

def get_level_by_xp(xp: int) -> tuple:
    current = LEVELS[0]
    for threshold, name, desc in LEVELS:
        if xp >= threshold:
            current = (threshold, name, desc)
    return current

def get_progress_bar(current: int, total: int, length: int = 10) -> str:
    if total <= 0:
        return f"{'░' * length} 0%"
    filled = int(length * current / total)
    return f"{'█' * filled}{'░' * (length - filled)} {int((current/total)*100)}%"

def get_daily_bonus(user_data: Dict) -> tuple:
    """Возвращает (bonus_xp, streak_days, is_new_day)"""
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

def ensure_user_data(progress: Dict, lang: str) -> Dict:
    """Гарантирует наличие всех ключей в данных пользователя"""
    if lang not in progress:
        progress[lang] = {
            "current_block": FIRST_BLOCK_ID.get(lang, 1),
            "completed_blocks": [],
            "current_attempt": None,
            "xp": 0,
            "achievements": [],
            "login_streak": 0,
            "last_login_date": None
        }
    
    user_data = progress[lang]
    defaults = {
        "xp": 0,
        "achievements": [],
        "login_streak": 0,
        "last_login_date": None,
        "current_block": FIRST_BLOCK_ID.get(lang, 1),
        "completed_blocks": [],
        "current_attempt": None
    }
    
    for key, default_value in defaults.items():
        if key not in user_data:
            user_data[key] = default_value
    
    return user_data

# === ERROR HANDLER ===
@dp.errors()
async def global_error_handler(update: types.Update, exception: Exception):
    logger.error(f"💥 ERROR: {exception}", exc_info=True)
    try:
        if isinstance(update, types.Message):
            await update.answer(f"⚠️ Ошибка: {str(exception)[:100]}")
        elif isinstance(update, types.CallbackQuery):
            await update.answer(f"⚠️ Ошибка: {str(exception)[:100]}", show_alert=True)
    except:
        pass
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

# === START ===
@dp.message(Command("start"))
async def cmd_start(message: Message):
    try:
        user = message.from_user
        register_user(user.id, user.username, user.first_name, user.last_name)
        
        lang = load_user_language(user.id)
        
        if not lang:
            await message.answer(
                f"👋 <b>Привет, {user.first_name or 'Пользователь'}!</b>\n\n"
                f"🎓 Я помогу освоить терминологию программирования\n"
                f"🎮 Получай XP, достижения, повышай уровень!\n\n"
                f"📌 <b>Выбери язык:</b>",
                reply_markup=get_language_keyboard(), parse_mode="HTML"
            )
        else:
            progress = await async_load_progress(user.id)
            ensure_user_data(progress, lang)
            await async_save_progress(user.id, progress)
            await show_main_menu(message, user.id, lang)
            
    except Exception as e:
        logger.error(f"Error in /start: {e}", exc_info=True)
        await message.answer(f"⚠️ Ошибка: {e}")

@dp.message(F.text.in_(FIRST_BLOCK_ID.keys()))
async def handle_language_selection(message: Message):
    try:
        user_id = message.from_user.id
        selected_lang = message.text.strip()
        
        save_user_language(user_id, selected_lang)
        progress = await async_load_progress(user_id)
        user_data = ensure_user_data(progress, selected_lang)
        
        bonus, streak, is_new = get_daily_bonus(user_data)
        if is_new and bonus > 0:
            user_data["last_login_date"] = datetime.now().strftime("%Y-%m-%d")
            user_data["login_streak"] = streak
            user_data["xp"] += bonus
            await message.answer(f"🎁 <b>Ежедневный бонус!</b>\n🔥 Серия: {streak} дн.\n💎 +{bonus} XP", parse_mode="HTML")
        
        await async_save_progress(user_id, progress)
        
        await message.answer(
            f"✅ <b>Выбран: {selected_lang}</b>\n\n"
            f"📚 Начни обучение или проверь знания!",
            parse_mode="HTML", reply_markup=get_main_keyboard()
        )
        
        logger.info(f"User {user_id} selected {selected_lang}")
        
    except Exception as e:
        logger.error(f"Error in language selection: {e}", exc_info=True)
        await message.answer(f"⚠️ Ошибка выбора языка: {e}")

async def show_main_menu(message: Message, user_id: int, lang: str):
    try:
        progress = await async_load_progress(user_id)
        lang_data = ensure_user_data(progress, lang)
        
        xp = lang_data.get("xp", 0)
        level_info = get_level_by_xp(xp)
        completed = len(lang_data.get("completed_blocks", []))
        achievements_count = len(lang_data.get("achievements", []))
        
        next_level_xp = None
        for threshold, _, _ in LEVELS[1:]:
            if xp < threshold:
                next_level_xp = threshold
                break
        
        if next_level_xp:
            current_level_xp = level_info[0]
            bar = get_progress_bar(xp - current_level_xp, next_level_xp - current_level_xp)
        else:
            bar = "░░░░░░░░░░ MAX"
        
        profile = get_user_profile(user_id)
        name = profile.get("first_name", "Пользователь") if profile else "Пользователь"
        
        msg = (f"📖 <b>Меню ({lang})</b>\n\n"
               f"👤 {name}\n"
               f"🏅 {level_info[1]} ({level_info[0]} XP)\n"
               f"{bar}\n\n"
               f"📊 <b>Статистика:</b>\n"
               f"📚 Пройдено: {completed}\n"
               f"🏆 Достижений: {achievements_count}\n"
               f"🔥 Серия: {lang_data.get('login_streak', 0)}\n\n"
               f"Выбери режим:")
        
        await message.answer(msg, parse_mode="HTML", reply_markup=get_main_keyboard())
        
    except Exception as e:
        logger.error(f"Error showing menu: {e}", exc_info=True)
        await message.answer(f"⚠️ Ошибка: {e}")

# === STUDY MODE ===
@dp.message(F.text == "📚 Обучение")
async def handle_study_mode(message: Message):
    try:
        user_id = message.from_user.id
        lang = load_user_language(user_id)
        
        if not lang:
            await message.answer("⚠️ Сначала выберите язык: /start")
            return
        
        progress = await async_load_progress(user_id)
        lang_data = ensure_user_data(progress, lang)
        current_block_id = lang_data.get("current_block", FIRST_BLOCK_ID[lang])
        
        block = next((b for b in DATA["blocks"] if b["id"] == current_block_id), None)
        if not block:
            await message.answer("❌ Блок не найден")
            return
        
        terms = block.get("terms", [])
        terms_text = "\n\n".join([f"🔹 <b>{t['term']}</b>\n{t.get('definition', '')}" for t in terms]) if terms else "📭 Нет терминов"
        
        await message.answer(
            f"📚 <b>{block['title']}</b>\n\n"
            f"{block.get('description', '')}\n\n"
            f"{terms_text}\n\n"
            f"💡 Изучил? Переходи в 🧠 Задание",
            parse_mode="HTML"
        )
        
    except Exception as e:
        logger.error(f"Error in study mode: {e}", exc_info=True)
        await message.answer(f"⚠️ Ошибка: {e}")

# === REPEAT STUDY ===
@dp.message(F.text == "🔁 Повторить обучение")
async def repeat_study(message: Message):
    try:
        user_id = message.from_user.id
        lang = load_user_language(user_id)
        
        if not lang:
            await message.answer("⚠️ /start")
            return
        
        progress = await async_load_progress(user_id)
        lang_data = ensure_user_data(progress, lang)
        completed_blocks = lang_data.get("completed_blocks", [])
        current_block = lang_data.get("current_block", FIRST_BLOCK_ID[lang])
        
        all_blocks = get_all_blocks_by_language(lang)
        available = [b for b in all_blocks if b["id"] in completed_blocks or b["id"] == current_block]
        
        if not available:
            await message.answer("📭 Пока нет пройденных блоков")
            return
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(
                text=f"{'✅' if b['id'] in completed_blocks else '📖'} #{b['id']} | {b['title']}",
                callback_data=f"repeat_block_{b['id']}"
            )] for b in available
        ])
        
        await message.answer(f"📚 <b>Повторение</b>\nВыберите блок:", parse_mode="HTML", reply_markup=keyboard)
        
    except Exception as e:
        logger.error(f"Error in repeat study: {e}", exc_info=True)
        await message.answer(f"⚠️ Ошибка: {e}")

@dp.callback_query(F.data.startswith("repeat_block_"))
async def show_repeat_block(callback: CallbackQuery):
    try:
        await callback.answer()
        block_id = int(callback.data.split("_")[-1])
        
        block = get_block_by_id(block_id)
        if not block:
            await callback.message.edit_text("❌ Блок не найден")
            return
        
        terms = block.get("terms", [])
        terms_text = "\n\n".join([f"🔹 <b>{t['term']}</b>\n{t.get('definition', '')}" for t in terms]) if terms else "📭"
        
        await callback.message.edit_text(
            f"📖 <b>{block['title']}</b>\n\n{terms_text}\n\n💡 Вспомнил? 🧠 Задание",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="📋 Назад", callback_data="repeat_study_list")]])
        )
        
    except Exception as e:
        logger.error(f"Error showing repeat block: {e}", exc_info=True)
        await callback.answer(f"⚠️ Ошибка: {e}", show_alert=True)

@dp.callback_query(F.data == "repeat_study_list")
async def back_to_repeat_list(callback: CallbackQuery):
    await callback.answer()
    await repeat_study(callback.message)

# === QUIZ MODE ===
@dp.message(F.text == "🧠 Задание")
async def handle_quiz_mode(message: Message):
    try:
        user_id = message.from_user.id
        lang = load_user_language(user_id)
        
        if not lang:
            await message.answer("⚠️ /start")
            return
        
        progress = await async_load_progress(user_id)
        lang_data = ensure_user_data(progress, lang)
        
        if lang_data.get("current_attempt"):
            await message.answer("❗ Завершите текущий тест")
            return
        
        current_block_id = lang_data.get("current_block", FIRST_BLOCK_ID[lang])
        block = next((b for b in DATA["blocks"] if b["id"] == current_block_id), None)
        if not block:
            await message.answer("❌ Блок не найден")
            return
        
        tasks = block.get("tasks", [])
        if not tasks:
            await message.answer("📭 Нет заданий")
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
        
    except Exception as e:
        logger.error(f"Error in quiz mode: {e}", exc_info=True)
        await message.answer(f"⚠️ Ошибка: {e}")

async def send_question(message: Message, user_id: int, lang: str, attempt: dict):
    try:
        idx = attempt["current"]
        questions = attempt["questions"]
        
        if idx >= len(questions):
            await finish_quiz(message, user_id, lang, attempt)
            return
        
        q = questions[idx]
        text = f"❓ <b>Вопрос {idx+1}/{len(questions)}</b>\n\n{q['question']}"
        if q.get("code"):
            text += f"\n\n<code>{q['code']}</code>"
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=f"{i+1}. {opt}", callback_data=f"ans_{i}")]
            for i, opt in enumerate(q["options"])
        ])
        
        await message.answer(text, parse_mode="HTML", reply_markup=keyboard)
    except Exception as e:
        logger.error(f"Error sending question: {e}", exc_info=True)

@dp.callback_query(F.data.startswith("ans_"))
async def handle_answer(callback: CallbackQuery):
    try:
        await callback.answer()
        user_id = callback.from_user.id
        lang = load_user_language(user_id)
        
        if not lang:
            return
        
        progress = await async_load_progress(user_id)
        lang_data = ensure_user_data(progress, lang)
        attempt = lang_data.get("current_attempt")
        
        if not attempt:
            await callback.message.edit_text("❌ Нет активной попытки")
            return
        
        answer_idx = int(callback.data.split("_")[1])
        q = attempt["questions"][attempt["current"]]
        is_correct = (answer_idx == q["correct"])
        
        attempt["answers"].append({"correct": is_correct})
        if is_correct:
            attempt["correct"] += 1
        
        streak = sum(1 for a in attempt["answers"][-3:] if a["correct"]) if len(attempt["answers"]) >= 3 else 0
        combo = f"\n\n🔥 COMBO x{streak}!" if streak >= 3 else ""
        
        feedback = "✅ Верно!" if is_correct else f"❌ Неверно\n💡 {q.get('explanation', '')}"
        feedback += combo
        
        attempt["current"] += 1
        lang_data["current_attempt"] = attempt
        await async_save_progress(user_id, progress)
        
        if attempt["current"] < len(attempt["questions"]):
            await callback.message.edit_text(f"{feedback}\n\n➡️ Следующий...")
            await asyncio.sleep(1)
            await send_question(callback.message, user_id, lang, attempt)
        else:
            await callback.message.edit_text(f"{feedback}\n\n⏳ Итоги...")
            await finish_quiz(callback.message, user_id, lang, attempt)
            
    except Exception as e:
        logger.error(f"Error handling answer: {e}", exc_info=True)
        await callback.answer(f"⚠️ Ошибка: {e}", show_alert=True)

async def finish_quiz(message: Message, user_id: int, lang: str, attempt: dict):
    try:
        total = len(attempt["questions"])
        correct = attempt["correct"]
        score = correct / total if total > 0 else 0
        time_spent = int(datetime.now().timestamp() - attempt.get("start_time", 0))
        
        progress = await async_load_progress(user_id)
        lang_data = ensure_user_data(progress, lang)
        lang_data["current_attempt"] = None
        
        old_xp = lang_data.get("xp", 0)
        base_xp = int(score * 100)
        time_bonus = 20 if time_spent < 120 else 0
        new_xp = old_xp + base_xp + time_bonus
        
        earned = []
        achieved_ids = [a["id"] for a in lang_data.get("achievements", [])]
        
        if "first_block" not in achieved_ids and len(lang_data.get("completed_blocks", [])) == 0:
            earned.append(ACHIEVEMENTS["first_block"])
        if "perfect_block" not in achieved_ids and score == 1.0:
            earned.append(ACHIEVEMENTS["perfect_block"])
        if "speed_demon" not in achieved_ids and time_spent < 120:
            earned.append(ACHIEVEMENTS["speed_demon"])
        
        for ach in earned:
            if ach["id"] not in achieved_ids:
                lang_data.setdefault("achievements", []).append({"id": ach["id"], "earned_at": datetime.now().isoformat()})
                new_xp += ach["xp_reward"]
        
        old_level = get_level_by_xp(old_xp)
        new_level = get_level_by_xp(new_xp)
        leveled_up = old_level[0] != new_level[0]
        
        lang_data["xp"] = new_xp
        
        if attempt["block_id"] not in lang_data.get("completed_blocks", []):
            lang_data.setdefault("completed_blocks", []).append(attempt["block_id"])
        
        next_id = attempt["block_id"] + 1
        if next_id in [b["id"] for b in DATA["blocks"]] and score >= UNLOCK_THRESHOLD:
            lang_data["current_block"] = next_id
        
        await async_save_progress(user_id, progress)
        
        msg = (f"🏁 <b>Готово!</b>\n\n"
               f"✅ {correct}/{total}\n"
               f"📊 {score*100:.0f}%\n"
               f"⏱️ {time_spent}с\n"
               f"💎 XP: +{base_xp + time_bonus}")
        
        if earned:
            msg += "\n\n🏆 <b>ДОСТИЖЕНИЯ:</b>\n"
            for a in earned:
                msg += f"{a['icon']} {a['name']} (+{a['xp_reward']} XP)\n"
        
        if leveled_up:
            msg += f"\n\n🆙 <b>НОВЫЙ УРОВЕНЬ!</b>\n{new_level[1]}"
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔁 Ещё раз", callback_data="retry_quiz")],
            [InlineKeyboardButton(text="📚 К теории", callback_data="back_to_study")]
        ])
        
        await message.answer(msg, parse_mode="HTML", reply_markup=keyboard)
        
    except Exception as e:
        logger.error(f"Error finishing quiz: {e}", exc_info=True)
        await message.answer(f"⚠️ Ошибка: {e}")

@dp.callback_query(F.data == "retry_quiz")
async def retry_quiz_handler(callback: CallbackQuery):
    await callback.answer()
    await handle_quiz_mode(callback.message)

@dp.callback_query(F.data == "back_to_study")
async def back_to_study_handler(callback: CallbackQuery):
    await callback.answer()
    await handle_study_mode(callback.message)

@dp.message(F.text == "🧪 Повторить тест")
async def repeat_quiz(message: Message):
    try:
        user_id = message.from_user.id
        lang = load_user_language(user_id)
        
        if not lang:
            await message.answer("⚠️ /start")
            return
        
        progress = await async_load_progress(user_id)
        if lang in progress:
            progress[lang]["current_attempt"] = None
            await async_save_progress(user_id, progress)
        
        await handle_quiz_mode(message)
        
    except Exception as e:
        logger.error(f"Error in repeat quiz: {e}", exc_info=True)
        await message.answer(f"⚠️ Ошибка: {e}")

# === ACHIEVEMENTS ===
@dp.message(F.text == "🏆 Достижения")
async def show_achievements(message: Message):
    try:
        user_id = message.from_user.id
        lang = load_user_language(user_id)
        
        if not lang:
            await message.answer("⚠️ /start")
            return
        
        progress = await async_load_progress(user_id)
        lang_data = ensure_user_data(progress, lang)
        earned_ids = [a["id"] for a in lang_data.get("achievements", [])]
        
        msg = "🏆 <b>ДОСТИЖЕНИЯ</b>\n\n"
        
        for ach_id in earned_ids:
            if ach_id in ACHIEVEMENTS:
                ach = ACHIEVEMENTS[ach_id]
                msg += f"{ach['icon']} <b>{ach['name']}</b>\n{ach['description']}\n\n"
        
        if not earned_ids:
            msg += "📭 Пока нет достижений. Пройди первый тест!\n\n"
        
        msg += "\n🔒 <b>Заблокировано:</b>\n"
        for ach_id, ach in ACHIEVEMENTS.items():
            if ach_id not in earned_ids:
                msg += f"🔒 {ach['name']}\n"
        
        await message.answer(msg, parse_mode="HTML")
        
    except Exception as e:
        logger.error(f"Error showing achievements: {e}", exc_info=True)
        await message.answer(f"⚠️ Ошибка: {e}")

# === PROFILE ===
@dp.message(F.text == "👤 Профиль")
async def show_profile(message: Message):
    try:
        user_id = message.from_user.id
        profile = get_user_profile(user_id)
        lang = load_user_language(user_id)
        
        if not profile:
            await message.answer("❌ /start")
            return
        
        progress = await async_load_progress(user_id)
        lang_data = ensure_user_data(progress, lang) if lang else {}
        
        xp = lang_data.get("xp", 0)
        level_info = get_level_by_xp(xp)
        completed = len(lang_data.get("completed_blocks", []))
        achievements = len(lang_data.get("achievements", []))
        streak = lang_data.get("login_streak", 0)
        
        msg = (f"👤 <b>Профиль</b>\n\n"
               f"📛 {profile.get('first_name', 'Пользователь')}\n"
               f"🆔 <code>{user_id}</code>\n"
               f"🌐 Язык: {lang or 'не выбран'}\n\n"
               f"📊 <b>Прогресс:</b>\n"
               f"🏅 {level_info[1]} ({level_info[0]} XP)\n"
               f"📚 Пройдено: {completed}\n"
               f"🏆 Достижений: {achievements}\n"
               f"🔥 Серия: {streak}\n\n"
               f"📝 {level_info[2]}")
        
        await message.answer(msg, parse_mode="HTML")
        
    except Exception as e:
        logger.error(f"Error showing profile: {e}", exc_info=True)
        await message.answer(f"⚠️ Ошибка: {e}")

# === SETTINGS ===
@dp.message(F.text == "⚙️ Настройки")
async def show_settings(message: Message):
    await message.answer(
        "⚙️ <b>Настройки</b>\n\n"
        "/start — сменить язык\n"
        "/admin — админка\n\n"
        "Разработчик: @Pavlan868",
        parse_mode="HTML"
    )

# === ADMIN ===
def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS

@dp.message(Command("admin"))
async def cmd_admin(message: Message):
    if not is_admin(message.from_user.id):
        await message.answer("❌ Доступ запрещён")
        return
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Добавить", callback_data="admin_add")],
        [InlineKeyboardButton(text="📊 Статистика", callback_data="admin_stats")]
    ])
    
    await message.answer("🔧 <b>Админка</b>", reply_markup=keyboard, parse_mode="HTML")

class AdminAddQuestion(StatesGroup):
    entering_question = State()
    entering_options = State()
    entering_correct = State()
    entering_explanation = State()

@dp.callback_query(F.data == "admin_add")
async def admin_add_start(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    langs = list(set(b.get("language") for b in DATA.get("blocks", [])))
    keyboard = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=l, callback_data=f"admin_add_lang_{l}")] for l in langs])
    await callback.message.edit_text("📚 Выберите язык:", reply_markup=keyboard)

@dp.callback_query(F.data.startswith("admin_add_lang_"))
async def admin_select_block(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    lang = callback.data.split("_")[-1]
    blocks = get_all_blocks_by_language(lang)
    keyboard = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=f"#{b['id']}", callback_data=f"admin_add_block_{b['id']}")] for b in blocks[:10]])
    await state.update_data(admin_lang=lang)
    await callback.message.edit_text(f"📦 Блоки:", reply_markup=keyboard)

@dp.callback_query(F.data.startswith("admin_add_block_"))
async def admin_enter_question(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.update_data(admin_block_id=int(callback.data.split("_")[-1]))
    await state.set_state(AdminAddQuestion.entering_question)
    await callback.message.edit_text("❓ Введите вопрос:")

@dp.message(AdminAddQuestion.entering_question)
async def admin_save_question(message: Message, state: FSMContext):
    await state.update_data(question_text=message.text)
    await state.set_state(AdminAddQuestion.entering_options)
    await message.answer("🔤 Варианты через запятую:")

@dp.message(AdminAddQuestion.entering_options)
async def admin_save_options(message: Message, state: FSMContext):
    options = [o.strip() for o in message.text.split(",") if o.strip()]
    if len(options) < 2:
        await message.answer("❌ Минимум 2")
        return
    await state.update_data(options=options)
    await state.set_state(AdminAddQuestion.entering_correct)
    await message.answer(f"🔢 Номер правильного (1-{len(options)}):")

@dp.message(AdminAddQuestion.entering_correct)
async def admin_save_correct(message: Message, state: FSMContext):
    try:
        idx = int(message.text.strip()) - 1
        data = await state.get_data()
        if not (0 <= idx < len(data["options"])):
            return
        await state.update_data(correct_index=idx)
        await state.set_state(AdminAddQuestion.entering_explanation)
        await message.answer("💡 Пояснение (или «-»):")
    except:
        await message.answer("❌ Число")

@dp.message(AdminAddQuestion.entering_explanation)
async def admin_finish_add(message: Message, state: FSMContext):
    data = await state.get_data()
    payload = {"question": data["question_text"], "options": data["options"], 
               "correct": data["correct_index"], "explanation": message.text if message.text != "-" else "", "code": ""}
    success = add_question_to_block(data["admin_block_id"], payload)
    await message.answer("✅ Добавлен!" if success else "❌ Ошибка")
    await state.clear()
    await cmd_admin(message)

@dp.callback_query(F.data == "admin_stats")
async def admin_show_stats(callback: CallbackQuery):
    await callback.answer()
    total = get_all_users_count()
    langs = get_users_by_language()
    q_total = sum(len(b.get("tasks", [])) for b in DATA.get("blocks", []))
    await callback.message.answer(f"📊 Пользователей: {total}\n" + 
                                  "\n".join(f"• {l}: {c}" for l, c in langs.items()) + 
                                  f"\n\n❓ Вопросов: {q_total}")

# === UNKNOWN ===
@dp.message()
async def handle_unknown(message: Message):
    state = await dp.storage.get_state(user_id=message.from_user.id)
    if state and state.startswith("Admin"):
        return
    
    lang = load_user_language(message.from_user.id)
    if lang:
        await message.answer("❓ Используйте кнопки или /start", reply_markup=get_main_keyboard())
    else:
        await message.answer("👋 Нажмите /start", reply_markup=ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="/start")]], resize_keyboard=True))

# === RUN ===
async def on_startup():
    logger.info("🚀 Запуск v4.1...")
    init_db()
    for aid in ADMIN_IDS:
        try:
            await bot.send_message(aid, "✅ Бот запущен 🎮")
        except:
            pass

async def on_shutdown():
    logger.info("🛑 Остановка...")
    await bot.session.close()

async def main():
    dp.startup.register(on_startup)
    dp.shutdown.register(on_shutdown)
    
    if os.getenv("DISABLE_PORT_CHECK") == "true":
        logger.info("🔄 Render mode")
    
    logger.info("🔄 Polling...")
    await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())

if __name__ == "__main__":
    def graceful_exit(signum, frame):
        logger.info("🛑 Сигнал")
        sys.exit(0)
    
    signal.signal(signal.SIGTERM, graceful_exit)
    signal.signal(signal.SIGINT, graceful_exit)
    
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("👋 Ctrl+C")
    except Exception as e:
        logger.error(f"💥 {e}", exc_info=True)