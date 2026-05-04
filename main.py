# main.py
# Ядро Telegram-бота: стабильная версия с исправлениями
# Версия: 2.2 (Fixed: locked blocks, quiz loop, simple buttons)

import asyncio
import json
import logging
import os
import random
import signal
import sys
from asyncio import Lock
from typing import Optional, Dict, Any

from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    Message, CallbackQuery, ReplyKeyboardMarkup, KeyboardButton,
    InlineKeyboardMarkup, InlineKeyboardButton
)

from config import BOT_TOKEN, ADMIN_IDS, UNLOCK_THRESHOLD, MIN_QUESTIONS_PER_BLOCK
from database import (
    init_db, register_user, get_user_profile, is_user_registered,
    save_user_language, load_user_language, load_progress, save_progress,
    add_question_to_block, remove_question_from_block, get_block_by_id,
    get_all_blocks_by_language, get_question_stats, get_all_users_count, get_users_by_language
)

# === НАСТРОЙКА ЛОГИРОВАНИЯ ===
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.FileHandler("bot.log", encoding="utf-8"), logging.StreamHandler()]
)
logger = logging.getLogger(__name__)

# === ИНИЦИАЛИЗАЦИЯ БОТА ===
if not BOT_TOKEN:
    raise RuntimeError("❌ BOT_TOKEN не задан! Проверьте config.py и .env")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# === ГЛОБАЛЬНЫЕ ДАННЫЕ ===
try:
    with open("data.json", "r", encoding="utf-8") as f:
        DATA = json.load(f)
    logger.info(f"✓ Загружено {len(DATA.get('blocks', []))} учебных блоков")
except FileNotFoundError:
    logger.error("❌ Файл data.json не найден!")
    DATA = {"blocks": []}
except json.JSONDecodeError as e:
    logger.error(f"❌ Ошибка парсинга data.json: {e}")
    DATA = {"blocks": []}

FIRST_BLOCK_ID = {"Python": 1, "C++": 6, "Java": 11, "JavaScript": 16, "Git": 21}
_user_locks: Dict[int, Lock] = {}

def get_user_lock(user_id: int) -> Lock:
    if user_id not in _user_locks:
        _user_locks[user_id] = Lock()
    return _user_locks[user_id]

# === ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ===

async def async_load_progress(user_id: int) -> Dict:
    return await asyncio.to_thread(load_progress, user_id)

async def async_save_progress(user_id: int, progress_data: dict):
    """✅ FIX: Явное имя аргумента + сохранение после каждого изменения"""
    lock = get_user_lock(user_id)
    async with lock:
        await asyncio.to_thread(save_progress, user_id, progress_data)

def is_block_unlocked(progress: Dict, lang: str, block_id: int) -> bool:
    """Блок разблокирован, если он первый, пройден или следующий после последнего пройденного"""
    lang_data = progress.get(lang, {})
    completed = lang_data.get("completed_blocks", [])
    current = lang_data.get("current_block", FIRST_BLOCK_ID.get(lang, 1))
    return block_id in completed or block_id == current or (completed and block_id == max(completed) + 1)

def get_main_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📚 Обучение"), KeyboardButton(text="🧠 Задание")],
            [KeyboardButton(text="🔁 Повторить обучение"), KeyboardButton(text="🧪 Повторить тест")],
            [KeyboardButton(text="👤 Профиль"), KeyboardButton(text="⚙️ Настройки")]
        ],
        resize_keyboard=True,
        input_field_placeholder="Выберите действие"
    )

def get_language_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=lang)] for lang in FIRST_BLOCK_ID.keys()],
        resize_keyboard=True,
        one_time_keyboard=True
    )

# === FSM ДЛЯ АДМИН-ПАНЕЛИ ===
class AdminAddQuestion(StatesGroup):
    selecting_block = State()
    entering_question = State()
    entering_options = State()
    entering_correct = State()
    entering_explanation = State()

class AdminRemoveQuestion(StatesGroup):
    selecting_block = State()
    selecting_question = State()
    confirming = State()

# === ГЛОБАЛЬНЫЙ ОБРАБОТЧИК ОШИБОК ===
@dp.errors()
async def global_error_handler(update: types.Update, exception: Exception):
    logger.error(f"💥 [GLOBAL ERROR] {exception.__class__.__name__}: {exception}", exc_info=True)
    try:
        if isinstance(update, types.Message):
            await update.answer("⚠️ Техническая ошибка. Попробуйте /start.")
        elif isinstance(update, types.CallbackQuery):
            await update.answer("⚠️ Ошибка", show_alert=True)
    except:
        pass
    return True

# === ОБРАБОТЧИКИ: СТАРТ И РЕГИСТРАЦИЯ ===

@dp.message(Command("start"))
async def cmd_start(message: Message):
    user = message.from_user
    user_id = user.id
    register_user(user_id=user_id, username=user.username, first_name=user.first_name, last_name=user.last_name)
    logger.info(f"👤 Пользователь {user_id} (@{user.username}) запустил бота")
    
    lang = load_user_language(user_id)
    if not lang:
        await message.answer(
            f"👋 Привет, {user.first_name or 'Пользователь'}!\nВыберите язык:",
            reply_markup=get_language_keyboard()
        )
    else:
        await show_main_menu(message, user_id, lang)

@dp.message(F.text.in_(FIRST_BLOCK_ID.keys()))
async def handle_language_selection(message: Message):
    user_id = message.from_user.id
    selected_lang = message.text.strip()
    save_user_language(user_id, selected_lang)
    
    progress = await async_load_progress(user_id)
    if selected_lang not in progress:
        progress[selected_lang] = {"current_block": FIRST_BLOCK_ID[selected_lang], "completed_blocks": [], "current_attempt": None}
        await async_save_progress(user_id, progress)
    
    await message.answer(
        f"✅ Выбран: <b>{selected_lang}</b>\n📚 Начните обучение или проверьте знания.",
        parse_mode="HTML", reply_markup=get_main_keyboard()
    )
    logger.info(f"🔤 Пользователь {user_id} выбрал язык: {selected_lang}")

async def show_main_menu(message: Message, user_id: int, lang: str):
    progress = await async_load_progress(user_id)
    lang_data = progress.get(lang, {})
    completed = lang_data.get("completed_blocks", [])
    profile = get_user_profile(user_id)
    name = profile.get("first_name", "Пользователь") if profile else "Пользователь"
    stats = f"\n🏆 Пройдено: {len(completed)}" if completed else ""
    
    await message.answer(f"📖 Меню ({lang}){stats}\n👤 {name}, выбери режим:", reply_markup=get_main_keyboard(), parse_mode="HTML")

# === ПРОСТЫЕ КНОПКИ: ОБУЧЕНИЕ / ЗАДАНИЕ / ПОВТОР ===

@dp.message(F.text == "📚 Обучение")
async def handle_study_mode(message: Message):
    """✅ Показывает ТОЛЬКО текущий блок (как было изначально)"""
    user_id = message.from_user.id
    lang = load_user_language(user_id)
    if not lang:
        await message.answer("⚠️ Выберите язык: /start"); return
    
    progress = await async_load_progress(user_id)
    lang_data = progress.get(lang, {})
    current_block_id = lang_data.get("current_block", FIRST_BLOCK_ID[lang])
    
    block = next((b for b in DATA["blocks"] if b["id"] == current_block_id), None)
    if not block:
        await message.answer("❌ Блок не найден"); return
    
    terms = block.get("terms", [])
    terms_text = "\n\n".join([f"🔹 <b>{t['term']}</b>\n{t.get('definition', '')}" for t in terms]) if terms else "📭 Нет терминов"
    
    # Кнопка "Следующий блок" только если он разблокирован
    next_id = current_block_id + 1
    next_unlocked = next_id in [b["id"] for b in DATA["blocks"]] and is_block_unlocked(progress, lang, next_id)
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➡️ Следующий блок", callback_data=f"block_{next_id}")]
    ]) if next_unlocked else None
    
    await message.answer(
        f"📚 <b>{block['title']}</b>\n\n{block.get('description', '')}\n\n{terms_text}\n💡 Изучил? Переходи в 🧠 Задание",
        parse_mode="HTML", reply_markup=keyboard
    )

@dp.message(F.text == "🧠 Задание")
async def handle_quiz_mode(message: Message):
    """✅ Запускает тест по текущему блоку"""
    user_id = message.from_user.id
    lang = load_user_language(user_id)
    if not lang:
        await message.answer("⚠️ Выберите язык: /start"); return
    
    progress = await async_load_progress(user_id)
    lang_data = progress.get(lang, {})
    
    if lang_data.get("current_attempt"):
        await message.answer("❗ Завершите текущий тест"); return
    
    current_block_id = lang_data.get("current_block", FIRST_BLOCK_ID[lang])
    block = next((b for b in DATA["blocks"] if b["id"] == current_block_id), None)
    if not block:
        await message.answer("❌ Блок не найден"); return
    
    tasks = block.get("tasks", [])
    if not tasks:
        await message.answer("📭 Нет заданий в этом блоке"); return
    
    attempt = {
        "block_id": current_block_id,
        "questions": random.sample(tasks, min(len(tasks), 5)),
        "current": 0, "correct": 0, "answers": []
    }
    lang_data["current_attempt"] = attempt
    await async_save_progress(user_id, progress)  # ✅ Сохраняем перед стартом
    await send_question(message, user_id, lang, attempt)

async def send_question(message: Message, user_id: int, lang: str, attempt: dict):
    idx = attempt["current"]
    questions = attempt["questions"]
    
    if idx >= len(questions):
        await finish_quiz(message, user_id, lang, attempt); return
    
    q = questions[idx]
    text = f"❓ <b>Вопрос {idx+1}/{len(questions)}</b>\n\n{q['question']}"
    if q.get("code"): text += f"\n\n<code>{q['code']}</code>"
    
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
        await callback.message.edit_text("❌ Язык не выбран"); return
    
    progress = await async_load_progress(user_id)
    lang_data = progress.get(lang, {})
    attempt = lang_data.get("current_attempt")
    
    if not attempt:
        await callback.message.edit_text("❌ Нет активной попытки"); return
    
    try:
        answer_idx = int(callback.data.split("_")[1])
    except:
        await callback.answer("❌ Ошибка", show_alert=True); return
    
    q = attempt["questions"][attempt["current"]]
    is_correct = (answer_idx == q["correct"])
    
    attempt["answers"].append({"question_id": q["id"], "correct": is_correct})
    if is_correct: attempt["correct"] += 1
    
    feedback = "✅ Верно!" if is_correct else f"❌ Неверно.\n💡 {q.get('explanation', '')}"
    attempt["current"] += 1
    
    # ✅ КРИТИЧЕСКИЙ ФИКС: сохраняем прогресс ПОСЛЕ КАЖДОГО ответа!
    lang_data["current_attempt"] = attempt
    await async_save_progress(user_id, progress)
    
    if attempt["current"] < len(attempt["questions"]):
        await callback.message.edit_text(f"{feedback}\n\n➡️ Следующий...")
        await asyncio.sleep(1)
        await send_question(callback.message, user_id, lang, attempt)
    else:
        await callback.message.edit_text(f"{feedback}\n\n⏳ Итоги...")
        await finish_quiz(callback.message, user_id, lang, attempt)

async def finish_quiz(message: Message, user_id: int, lang: str, attempt: dict):
    total = len(attempt["questions"])
    correct = attempt["correct"]
    score = correct / total if total > 0 else 0
    
    progress = await async_load_progress(user_id)
    if lang in progress:
        progress[lang]["current_attempt"] = None  # Сбрасываем попытку
    
    block = get_block_by_id(attempt["block_id"])
    threshold = block.get("unlock_threshold", UNLOCK_THRESHOLD) if block else UNLOCK_THRESHOLD
    
    if lang in progress:
        lang_data = progress[lang]
        if attempt["block_id"] not in lang_data["completed_blocks"]:
            lang_data["completed_blocks"].append(attempt["block_id"])
        next_id = attempt["block_id"] + 1
        if next_id in [b["id"] for b in DATA["blocks"]] and score >= threshold:
            lang_data["current_block"] = next_id
            await message.answer("🎉 Следующий блок открыт!")
    
    await async_save_progress(user_id, progress)
    
    result = f"🏁 <b>Готово!</b>\n✅ {correct}/{total} ({score*100:.1f}%)\n🎯 Порог: {threshold*100:.0f}%\n\n"
    result += "✨ Новый блок!" if score >= threshold else "💪 Попробуй ещё раз!"
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔁 Ещё раз", callback_data="retry_quiz")],
        [InlineKeyboardButton(text="📚 К теории", callback_data="back_to_study")]
    ])
    await message.answer(result, parse_mode="HTML", reply_markup=keyboard)

@dp.callback_query(F.data == "retry_quiz")
async def retry_quiz_handler(callback: CallbackQuery):
    await callback.answer()
    await handle_quiz_mode(callback.message)

@dp.callback_query(F.data == "back_to_study")
async def back_to_study_handler(callback: CallbackQuery):
    await callback.answer()
    await handle_study_mode(callback.message)

@dp.message(F.text == "🔁 Повторить обучение")
async def repeat_study(message: Message):
    """✅ Просто показывает текущий блок заново"""
    user_id = message.from_user.id
    lang = load_user_language(user_id)
    if not lang:
        await message.answer("⚠️ /start"); return
    await handle_study_mode(message)

@dp.message(F.text == "🧪 Повторить тест")
async def repeat_quiz(message: Message):
    """✅ Сбрасывает попытку и запускает тест заново"""
    user_id = message.from_user.id
    lang = load_user_language(user_id)
    if not lang:
        await message.answer("⚠️ /start"); return
    
    progress = await async_load_progress(user_id)
    if lang in progress:
        progress[lang]["current_attempt"] = None
        await async_save_progress(user_id, progress)
    await handle_quiz_mode(message)

# === ПРОФИЛЬ И НАСТРОЙКИ ===

@dp.message(F.text == "👤 Профиль")
async def show_profile(message: Message):
    user_id = message.from_user.id
    profile = get_user_profile(user_id)
    lang = load_user_language(user_id)
    if not profile:
        await message.answer("❌ /start"); return
    
    progress = await async_load_progress(user_id)
    completed = len(progress.get(lang, {}).get("completed_blocks", [])) if lang else 0
    status = "🏆 Мастер" if completed >= 20 else "⭐ Продвинутый" if completed >= 10 else "🎓 Студент" if completed >= 5 else "🌱 Новичок"
    
    await message.answer(
        f"👤 <b>Профиль</b>\nID: <code>{user_id}</code>\nЯзык: {lang or '—'}\nСтатус: {status}\n📚 Пройдено: {completed}",
        parse_mode="HTML"
    )

@dp.message(F.text == "⚙️ Настройки")
async def show_settings(message: Message):
    await message.answer("⚙️ /start — сменить язык\n/admin — панель админа", reply_markup=ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="📋 Меню")]], resize_keyboard=True))

@dp.message(F.text == "📋 Меню")
async def back_to_main(message: Message):
    user_id = message.from_user.id
    lang = load_user_language(user_id)
    await (show_main_menu(message, user_id, lang) if lang else cmd_start(message))

# === НАВИГАЦИЯ ПО БЛОКАМ (только разблокированные) ===

@dp.callback_query(F.data == "blocks_list")
async def blocks_list_handler(callback: CallbackQuery):
    await callback.answer()
    user_id = callback.from_user.id
    lang = load_user_language(user_id)
    if not lang:
        await callback.message.answer("⚠️ /start"); return
    
    progress = await async_load_progress(user_id)
    all_blocks = get_all_blocks_by_language(lang)
    # ✅ ФИЛЬТР: только разблокированные блоки
    unlocked = [b for b in all_blocks if is_block_unlocked(progress, lang, b["id"])]
    
    if not unlocked:
        await callback.message.edit_text("📭 Пока нет доступных блоков")
        return
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"#{b['id']} | {b['title']}", callback_data=f"block_{b['id']}")]
        for b in unlocked
    ])
    
    try:
        await callback.message.edit_text(f"📚 Доступные блоки ({lang}):", reply_markup=keyboard)
    except:
        await callback.message.answer(f"📚 Доступные блоки ({lang}):", reply_markup=keyboard)

@dp.callback_query(F.data.startswith("block_"))
async def open_block_handler(callback: CallbackQuery):
    await callback.answer()
    try:
        block_id = int(callback.data.split("_")[1])
    except:
        await callback.message.edit_text("❌ Ошибка"); return
    
    block = get_block_by_id(block_id)
    if not block:
        await callback.message.edit_text("❌ Не найден"); return
    
    terms = block.get("terms", [])
    terms_text = "\n\n".join([f"🔹 <b>{t['term']}</b>\n{t.get('definition', '')}" for t in terms])
    
    try:
        await callback.message.edit_text(
            f"📖 <b>{block['title']}</b>\n\n{terms_text or '📭 Нет терминов'}\n💡 Изучил? 🧠 Задание",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="📋 Список", callback_data="blocks_list")]])
        )
    except:
        await callback.message.answer(f"📖 {block['title']}\n\n{terms_text or '📭'}", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="📋 Список", callback_data="blocks_list")]]))

# === АДМИН-ПАНЕЛЬ (сокращённо для стабильности) ===

def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS

@dp.message(Command("admin"))
async def cmd_admin(message: Message):
    if not is_admin(message.from_user.id):
        await message.answer("❌ Доступ запрещён"); return
    await message.answer("🔧 Админ-панель", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Добавить", callback_data="admin_add")],
        [InlineKeyboardButton(text="📊 Статистика", callback_data="admin_stats")]
    ]))

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
    keyboard = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=f"#{b['id']}: {b['title'][:20]}", callback_data=f"admin_add_block_{b['id']}")] for b in blocks[:10]])
    await state.update_data(admin_lang=lang)
    await callback.message.edit_text(f"📦 Блоки ({lang}):", reply_markup=keyboard)

@dp.callback_query(F.data.startswith("admin_add_block_"))
async def admin_enter_question(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    block_id = int(callback.data.split("_")[-1])
    await state.update_data(admin_block_id=block_id)
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
        await message.answer("❌ Минимум 2 варианта"); return
    await state.update_data(options=options)
    await state.set_state(AdminAddQuestion.entering_correct)
    await message.answer(f"✅ Варианты:\n" + "\n".join(f"{i+1}. {o}" for i, o in enumerate(options)) + f"\n\n🔢 Номер правильного (1-{len(options)}):")

@dp.message(AdminAddQuestion.entering_correct)
async def admin_save_correct(message: Message, state: FSMContext):
    try:
        idx = int(message.text.strip()) - 1
        data = await state.get_data()
        if not (0 <= idx < len(data["options"])):
            await message.answer(f"❌ 1-{len(data['options'])}"); return
        await state.update_data(correct_index=idx)
        await state.set_state(AdminAddQuestion.entering_explanation)
        await message.answer("💡 Пояснение (или «-»):")
    except:
        await message.answer("❌ Введите число")

@dp.message(AdminAddQuestion.entering_explanation)
async def admin_finish_add(message: Message, state: FSMContext):
    data = await state.get_data()
    payload = {"question": data["question_text"], "options": data["options"], "correct": data["correct_index"], "explanation": message.text if message.text != "-" else "", "code": ""}
    success = add_question_to_block(data["admin_block_id"], payload)
    await message.answer("✅ Добавлен!" if success else "❌ Ошибка")
    await state.clear()
    await cmd_admin(message)

@dp.callback_query(F.data == "admin_stats")
async def admin_show_stats(callback: CallbackQuery):
    await callback.answer()
    total_users = get_all_users_count()
    lang_stats = get_users_by_language()
    total_q = sum(len(b.get("tasks", [])) for b in DATA.get("blocks", []))
    await callback.message.answer(f"📊 Пользователей: {total_users}\n📚 По языкам:\n" + "\n".join(f"• {l}: {c}" for l, c in lang_stats.items()) + f"\n\n❓ Вопросов: {total_q}")

@dp.message()
async def handle_unknown(message: Message):
    lang = load_user_language(message.from_user.id)
    if await dp.storage.get_state(user_id=message.from_user.id) and (await dp.storage.get_state(user_id=message.from_user.id)).startswith("Admin"):
        return
    await message.answer("❓ Используйте кнопки или /start", reply_markup=get_main_keyboard() if lang else ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="/start")]], resize_keyboard=True))

# === ЗАПУСК ===

async def on_startup():
    logger.info("🚀 Запуск...")
    init_db()
    for aid in ADMIN_IDS:
        try: await bot.send_message(aid, "✅ Бот запущен")
        except: pass

async def on_shutdown():
    logger.info("🛑 Остановка...")
    await bot.session.close()

async def main():
    dp.startup.register(on_startup)
    dp.shutdown.register(on_shutdown)
    if os.getenv("DISABLE_PORT_CHECK") == "true":
        logger.info("🔄 Render mode: polling")
    logger.info("🔄 Polling...")
    await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())

if __name__ == "__main__":
    def graceful_exit(signum, frame):
        logger.info("🛑 Сигнал завершения")
        sys.exit(0)
    signal.signal(signal.SIGTERM, graceful_exit)
    signal.signal(signal.SIGINT, graceful_exit)
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("👋 Ctrl+C")
    except Exception as e:
        logger.error(f"💥 {e}", exc_info=True)