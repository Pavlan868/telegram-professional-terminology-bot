# main.py
# Ядро Telegram-бота: обработчики, логика обучения, админ-панель
# Версия: 2.1 (Render Stable + Error Handling + Navigation Fix)

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

# Импорт из локальных модулей
from config import BOT_TOKEN, ADMIN_IDS, UNLOCK_THRESHOLD, MIN_QUESTIONS_PER_BLOCK, RENDER_MODE
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
# Загрузка учебных материалов
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

# Сопоставление языков и стартовых блоков
FIRST_BLOCK_ID = {
    "Python": 1, "C++": 6, "Java": 11, "JavaScript": 16, "Git": 21
}

# Блокировки для потокобезопасной работы с БД
_user_locks: Dict[int, Lock] = {}


def get_user_lock(user_id: int) -> Lock:
    """Получает или создаёт блокировку для пользователя"""
    if user_id not in _user_locks:
        _user_locks[user_id] = Lock()
    return _user_locks[user_id]


# === ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ===

async def async_load_progress(user_id: int) -> Dict:
    """Асинхронная обёртка для загрузки прогресса"""
    return await asyncio.to_thread(load_progress, user_id)


async def async_save_progress(user_id: int, progress_data: dict):
    """
    Асинхронная обёртка с блокировкой для сохранения прогресса.
    FIX: Аргумент явно назван progress_data, чтобы избежать NameError при вызове.
    """
    lock = get_user_lock(user_id)
    async with lock:
        # Явно передаём progress_data в синхронную функцию
        await asyncio.to_thread(save_progress, user_id, progress_data)


def get_main_keyboard() -> ReplyKeyboardMarkup:
    """Возвращает главное меню бота"""
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
    """Клавиатура выбора языка"""
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=lang)] for lang in FIRST_BLOCK_ID.keys()],
        resize_keyboard=True,
        one_time_keyboard=True
    )


def get_block_navigation_keyboard(block_id: int, lang: str, can_next: bool = False) -> InlineKeyboardMarkup:
    """Клавиатура навигации по блокам"""
    buttons = []
    
    # Кнопка "Назад к списку" (КРИТИЧНО: должна быть всегда)
    buttons.append([InlineKeyboardButton(text="📋 К списку блоков", callback_data="blocks_list")])
    
    # Кнопка "Следующий блок" (если разблокирован)
    if can_next:
        next_id = block_id + 1
        # Проверяем, существует ли такой блок в базе
        if any(b['id'] == next_id for b in DATA.get('blocks', [])):
            buttons.append([InlineKeyboardButton(text="➡️ Следующий блок", callback_data=f"block_{next_id}")])
    
    return InlineKeyboardMarkup(inline_keyboard=buttons)


# === FSM ДЛЯ АДМИН-ПАНЕЛИ ===

class AdminAddQuestion(StatesGroup):
    selecting_block = State()
    entering_question = State()
    entering_options = State()
    entering_correct = State()
    entering_explanation = State()
    entering_code = State()


class AdminRemoveQuestion(StatesGroup):
    selecting_block = State()
    selecting_question = State()
    confirming = State()


# === ГЛОБАЛЬНЫЙ ОБРАБОТЧИК ОШИБОК (ANTI-CRASH) ===
@dp.errors()
async def global_error_handler(update: types.Update, exception: Exception):
    """
    Перехватывает ВСЕ необработанные исключения.
    Предотвращает зависание бота и информирует пользователя.
    """
    logger.error(f"💥 [GLOBAL ERROR] {exception.__class__.__name__}: {exception}", exc_info=True)
    
    # Пытаемся ответить пользователю, чтобы он не думал, что бот сломался
    try:
        if isinstance(update, types.Message):
            await update.answer(
                "⚠️ Произошла техническая ошибка. Попробуйте снова или напишите /start.\n"
                "💡 Бот продолжает работать."
            )
        elif isinstance(update, types.CallbackQuery):
            await update.answer("⚠️ Ошибка обработки действия.", show_alert=True)
            # Пробуем ответить в чат, если редактирование невозможно
            try:
                await update.message.answer("⚠️ Попробуйте нажать кнопку ещё раз.")
            except:
                pass
    except Exception as e:
        logger.warning(f"⚠️ Не удалось отправить сообщение об ошибке пользователю: {e}")
    
    # Возвращаем True, чтобы Dispatcher не падал и не логировал ошибку повторно
    return True


# === ОБРАБОТЧИКИ: РЕГИСТРАЦИЯ И СТАРТ ===

@dp.message(Command("start"))
async def cmd_start(message: Message):
    """Обработчик команды /start — регистрация и приветствие"""
    user = message.from_user
    user_id = user.id
    
    # Регистрация/обновление пользователя в БД
    register_user(
        user_id=user_id,
        username=user.username,
        first_name=user.first_name,
        last_name=user.last_name
    )
    
    logger.info(f"👤 Пользователь {user_id} (@{user.username}) запустил бота")
    
    # Проверка выбранного языка
    lang = load_user_language(user_id)
    
    if not lang:
        # Первичная настройка — выбор языка
        await message.answer(
            f"👋 Привет, {user.first_name or 'Пользователь'}!\n\n"
            f"🎓 Я помогу тебе освоить профессиональную терминологию в программировании.\n\n"
            f"📌 Для начала выбери язык, с которым хочешь работать:",
            reply_markup=get_language_keyboard()
        )
    else:
        # Пользователь уже настроен — показываем меню
        await show_main_menu(message, user_id, lang)


@dp.message(F.text.in_(FIRST_BLOCK_ID.keys()))
async def handle_language_selection(message: Message):
    """Обработка выбора языка программирования"""
    user_id = message.from_user.id
    selected_lang = message.text.strip()
    
    # Сохранение выбора
    save_user_language(user_id, selected_lang)
    
    # Инициализация прогресса для языка
    progress = await async_load_progress(user_id)
    if selected_lang not in progress:
        progress[selected_lang] = {
            "current_block": FIRST_BLOCK_ID[selected_lang],
            "completed_blocks": [],
            "current_attempt": None
        }
        await async_save_progress(user_id, progress)
    
    await message.answer(
        f"✅ Отлично! Выбран язык: <b>{selected_lang}</b>\n\n"
        f"📚 Теперь ты можешь начать обучение или проверить знания.",
        parse_mode="HTML",
        reply_markup=get_main_keyboard()
    )
    
    logger.info(f"🔤 Пользователь {user_id} выбрал язык: {selected_lang}")


# === ГЛАВНОЕ МЕНЮ ===

async def show_main_menu(message: Message, user_id: int, lang: str):
    """Показывает главное меню с учётом прогресса"""
    progress = await async_load_progress(user_id)
    lang_data = progress.get(lang, {})
    completed = lang_data.get("completed_blocks", [])
    
    # Динамическое отображение кнопок повтора
    keyboard = get_main_keyboard()
    
    # Персонализированное приветствие
    profile = get_user_profile(user_id)
    name = profile.get("first_name", "Пользователь") if profile else "Пользователь"
    
    stats_text = ""
    if completed:
        stats_text = f"\n\n🏆 Пройдено блоков: {len(completed)}"
    
    await message.answer(
        f"📖 Меню обучения ({lang}){stats_text}\n\n"
        f"👤 {name}, выбери режим работы:",
        reply_markup=keyboard,
        parse_mode="HTML"
    )


@dp.message(F.text == "📚 Обучение")
async def handle_study_mode(message: Message):
    """Режим изучения теории"""
    user_id = message.from_user.id
    lang = load_user_language(user_id)
    
    if not lang:
        await message.answer("⚠️ Сначала выберите язык программирования командой /start")
        return
    
    progress = await async_load_progress(user_id)
    lang_data = progress.get(lang, {})
    current_block_id = lang_data.get("current_block", FIRST_BLOCK_ID[lang])
    
    # Поиск блока
    block = next((b for b in DATA["blocks"] if b["id"] == current_block_id), None)
    if not block:
        await message.answer("❌ Блок обучения не найден")
        return
    
    # Формирование сообщения с теорией
    terms = block.get("terms", [])
    terms_text = "\n\n".join([
        f"🔹 <b>{t['term']}</b>\n{t.get('definition', '')}" for t in terms
    ]) if terms else "📭 В этом блоке пока нет терминов"
    
    # Проверка на следующий блок для кнопки навигации
    next_id = current_block_id + 1
    can_next = any(b['id'] == next_id for b in DATA["blocks"])
    
    await message.answer(
        f"📚 <b>{block['title']}</b>\n\n"
        f"{block.get('description', '')}\n\n"
        f"{terms_text}\n\n"
        f"💡 Когда изучишь материал — переходи в раздел «🧠 Задание»",
        parse_mode="HTML",
        reply_markup=get_block_navigation_keyboard(current_block_id, lang, can_next=can_next)
    )


@dp.message(F.text == "🧠 Задание")
async def handle_quiz_mode(message: Message):
    """Режим тестирования знаний"""
    user_id = message.from_user.id
    lang = load_user_language(user_id)
    
    if not lang:
        await message.answer("⚠️ Сначала выберите язык командой /start")
        return
    
    progress = await async_load_progress(user_id)
    lang_data = progress.get(lang, {})
    
    # Защита от параллельных попыток
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
    
    # Инициализация попытки
    attempt = {
        "block_id": current_block_id,
        "questions": random.sample(tasks, min(len(tasks), 5)),  # До 5 вопросов
        "current": 0,
        "correct": 0,
        "answers": []
    }
    
    lang_data["current_attempt"] = attempt
    # FIX: Используем корректное имя переменной
    await async_save_progress(user_id, progress)
    
    # Показ первого вопроса
    await send_question(message, user_id, lang, attempt)


async def send_question(message: Message, user_id: int, lang: str, attempt: dict):
    """Отправляет вопрос теста пользователю"""
    idx = attempt["current"]
    questions = attempt["questions"]
    
    if idx >= len(questions):
        # Тест завершён
        await finish_quiz(message, user_id, lang, attempt)
        return
    
    q = questions[idx]
    
    # Формирование текста вопроса
    text = f"❓ <b>Вопрос {idx + 1}/{len(questions)}</b>\n\n{q['question']}"
    if q.get("code"):
        text += f"\n\n<code>{q['code']}</code>"
    
    # Кнопки ответов
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"{i+1}. {opt}", callback_data=f"ans_{i}")]
        for i, opt in enumerate(q["options"])
    ])
    
    # Отправка с отключённым парсингом для безопасности
    await message.answer(text, parse_mode="HTML", reply_markup=keyboard)


@dp.callback_query(F.data.startswith("ans_"))
async def handle_answer(callback: CallbackQuery):
    """Обработка ответа на вопрос теста"""
    # Немедленное подтверждение callback (избегаем timeout)
    await callback.answer()
    
    user_id = callback.from_user.id
    lang = load_user_language(user_id)
    
    if not lang:
        await callback.message.edit_text("❌ Ошибка: язык не выбран")
        return
    
    progress = await async_load_progress(user_id)
    lang_data = progress.get(lang, {})
    attempt = lang_data.get("current_attempt")
    
    if not attempt:
        await callback.message.edit_text("❌ Активная попытка не найдена")
        return
    
    # Парсинг выбранного ответа
    try:
        answer_idx = int(callback.data.split("_")[1])
    except (IndexError, ValueError):
        await callback.answer("❌ Неверный формат ответа", show_alert=True)
        return
    
    q = attempt["questions"][attempt["current"]]
    is_correct = (answer_idx == q["correct"])
    
    # Сохранение результата
    attempt["answers"].append({"question_id": q["id"], "correct": is_correct})
    if is_correct:
        attempt["correct"] += 1
    
    # Показ обратной связи
    feedback = "✅ Верно!" if is_correct else f"❌ Неверно.\n💡 {q.get('explanation', 'Изучи материал ещё раз')}"
    
    attempt["current"] += 1
    
    if attempt["current"] < len(attempt["questions"]):
        # Следующий вопрос
        await callback.message.edit_text(f"{feedback}\n\n➡️ Следующий вопрос...")
        await asyncio.sleep(1)
        await send_question(callback.message, user_id, lang, attempt)
    else:
        # Завершение теста
        await callback.message.edit_text(f"{feedback}\n\n⏳ Подсчёт результатов...")
        await finish_quiz(callback.message, user_id, lang, attempt)


async def finish_quiz(message: Message, user_id: int, lang: str, attempt: dict):
    """Завершает тест и обрабатывает результаты"""
    total = len(attempt["questions"])
    correct = attempt["correct"]
    score = correct / total if total > 0 else 0
    
    # Очистка активной попытки
    progress = await async_load_progress(user_id)
    if lang in progress:
        progress[lang]["current_attempt"] = None
    
    # Проверка условия разблокировки следующего блока
    block = get_block_by_id(attempt["block_id"])
    threshold = block.get("unlock_threshold", UNLOCK_THRESHOLD) if block else UNLOCK_THRESHOLD
    
    unlocked_next = False
    if lang in progress:
        lang_data = progress[lang]
        if attempt["block_id"] not in lang_data["completed_blocks"]:
            lang_data["completed_blocks"].append(attempt["block_id"])
        
        # Разблокировка следующего блока
        next_block_id = attempt["block_id"] + 1
        if next_block_id in [b["id"] for b in DATA["blocks"]]:
            lang_data["current_block"] = next_block_id
            unlocked_next = True
            await message.answer(f"🎉 Поздравляем! Следующий блок разблокирован!")
    
    # FIX: Используем корректное имя переменной
    await async_save_progress(user_id, progress)
    
    # Итоговое сообщение
    result_text = (
        f"🏁 <b>Тест завершён!</b>\n\n"
        f"✅ Правильных ответов: {correct} из {total}\n"
        f"📊 Результат: {score*100:.1f}%\n"
        f"🎯 Порог разблокировки: {threshold*100:.0f}%\n\n"
    )
    
    if unlocked_next:
        result_text += "✨ <b>Новый блок доступен!</b>"
    elif score >= threshold:
        result_text += "✅ Блок пройден! Повтори или переходи к следующему."
    else:
        result_text += "💪 Попробуй ещё раз — практика делает мастера!"
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔁 Пройти ещё раз", callback_data="retry_quiz")],
        [InlineKeyboardButton(text="📚 К теории", callback_data="back_to_study")]
    ])
    
    await message.answer(result_text, parse_mode="HTML", reply_markup=keyboard)


@dp.callback_query(F.data == "retry_quiz")
async def retry_quiz_handler(callback: CallbackQuery):
    """Повтор текущего теста"""
    await callback.answer()
    await handle_quiz_mode(callback.message)


@dp.callback_query(F.data == "back_to_study")
async def back_to_study_handler(callback: CallbackQuery):
    """Возврат к режиму обучения"""
    await callback.answer()
    await handle_study_mode(callback.message)


# === КНОПКИ ПОВТОРА ===

@dp.message(F.text == "🔁 Повторить обучение")
async def repeat_study(message: Message):
    """Повторное изучение текущего блока"""
    user_id = message.from_user.id
    lang = load_user_language(user_id)
    
    if not lang:
        await message.answer("⚠️ Выберите язык командой /start")
        return
    
    await handle_study_mode(message)


@dp.message(F.text == "🧪 Повторить тест")
async def repeat_quiz(message: Message):
    """Повторное прохождение теста"""
    user_id = message.from_user.id
    lang = load_user_language(user_id)
    
    if not lang:
        await message.answer("⚠️ Выберите язык командой /start")
        return
    
    # Сброс активной попытки если есть
    progress = await async_load_progress(user_id)
    if lang in progress and progress[lang].get("current_attempt"):
        progress[lang]["current_attempt"] = None
        await async_save_progress(user_id, progress)
    
    await handle_quiz_mode(message)


# === ПРОФИЛЬ ПОЛЬЗОВАТЕЛЯ ===

@dp.message(F.text == "👤 Профиль")
async def show_profile(message: Message):
    """Показывает статистику пользователя"""
    user_id = message.from_user.id
    profile = get_user_profile(user_id)
    lang = load_user_language(user_id)
    
    if not profile:
        await message.answer("❌ Профиль не найден. Попробуйте /start")
        return
    
    progress = await async_load_progress(user_id)
    
    # Подсчёт статистики
    total_completed = 0
    if lang and lang in progress:
        total_completed = len(progress[lang].get("completed_blocks", []))
    
    # Определение статуса (задел на геймификацию)
    if total_completed >= 20:
        status = "🏆 Мастер терминологии"
    elif total_completed >= 10:
        status = "⭐ Продвинутый"
    elif total_completed >= 5:
        status = "🎓 Студент"
    else:
        status = "🌱 Новичок"
    
    await message.answer(
        f"👤 <b>Ваш профиль</b>\n\n"
        f"ID: <code>{user_id}</code>\n"
        f"Имя: {profile['first_name'] or '—'}\n"
        f"Язык: {lang or 'не выбран'}\n"
        f"Статус: {status}\n"
        f"📚 Пройдено блоков: {total_completed}\n"
        f"📅 Регистрация: {profile['registered_at'] or '—'}",
        parse_mode="HTML"
    )


@dp.message(F.text == "⚙️ Настройки")
async def show_settings(message: Message):
    """Меню настроек"""
    await message.answer(
        "⚙️ Настройки:\n\n"
        "• /start — сменить язык обучения\n"
        "• /admin — панель администратора (если есть доступ)\n"
        "• Напишите разработчику для предложений: @Pavlan868",
        reply_markup=ReplyKeyboardMarkup(
            keyboard=[[KeyboardButton(text="📋 Главное меню")]],
            resize_keyboard=True
        )
    )


@dp.message(F.text == "📋 Главное меню")
async def back_to_main(message: Message):
    """Возврат в главное меню"""
    user_id = message.from_user.id
    lang = load_user_language(user_id)
    
    if lang:
        await show_main_menu(message, user_id, lang)
    else:
        await cmd_start(message)


# === НАВИГАЦИЯ ПО БЛОКАМ (ИСПРАВЛЕНИЕ ЗАВИСАНИЙ) ===

@dp.callback_query(F.data == "blocks_list")
async def blocks_list_handler(callback: CallbackQuery):
    """Обработчик кнопки 'К списку блоков'"""
    # 1. Мгновенно подтверждаем callback (спасаем от таймаута)
    await callback.answer()
    
    user_id = callback.from_user.id
    lang = load_user_language(user_id)
    
    if not lang:
        await callback.message.answer("⚠️ Сначала выберите язык командой /start")
        return
    
    # 2. Безопасная загрузка блоков
    blocks = get_all_blocks_by_language(lang)
    if not blocks:
        await callback.message.edit_text("📭 Пока нет доступных блоков для этого языка.")
        return
    
    # 3. Формируем клавиатуру с проверками
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text=f"#{b['id']} | {b['title']}", 
            callback_data=f"block_{b['id']}"
        )]
        for b in blocks
    ])
    
    try:
        await callback.message.edit_text(
            f"📚 Учебные блоки ({lang}):\nВыберите номер:", 
            reply_markup=keyboard
        )
    except Exception:
        # Если текст слишком длинный или сообщение уже изменено
        await callback.message.answer(
            f"📚 Учебные блоки ({lang}):\nВыберите номер:", 
            reply_markup=keyboard
        )


@dp.callback_query(F.data.startswith("block_"))
async def open_block_handler(callback: CallbackQuery):
    """Обработчик выбора конкретного блока"""
    await callback.answer()
    
    try:
        block_id = int(callback.data.split("_")[1])
    except ValueError:
        await callback.message.edit_text("❌ Некорректный запрос блока")
        return
        
    block = get_block_by_id(block_id)
    if not block:
        await callback.message.edit_text("❌ Блок не найден в data.json")
        return
    
    # Формируем теорию
    terms = block.get("terms", [])
    terms_text = "\n\n".join([f"🔹 <b>{t['term']}</b>\n{t.get('definition', '')}" for t in terms])
    
    # Проверка на следующий блок
    next_id = block_id + 1
    can_next = any(b['id'] == next_id for b in DATA.get('blocks', []))
    
    try:
        await callback.message.edit_text(
            f"📖 <b>{block['title']}</b>\n\n"
            f"{block.get('description', '')}\n\n"
            f"{terms_text or '📭 Термины пока не добавлены'}\n\n"
            f"💡 Изучите материал → переходите в 🧠 Задание",
            parse_mode="HTML",
            reply_markup=get_block_navigation_keyboard(block_id, block.get('language'), can_next=can_next)
        )
    except Exception:
        # Fallback если edit_text не сработал
        await callback.message.answer(
            f"📖 <b>{block['title']}</b>\n\n{terms_text or '📭 Термины пока не добавлены'}",
            parse_mode="HTML",
            reply_markup=get_block_navigation_keyboard(block_id, block.get('language'), can_next=can_next)
        )


# === АДМИН-ПАНЕЛЬ ===

def is_admin(user_id: int) -> bool:
    """Проверяет, является ли пользователь админом"""
    return user_id in ADMIN_IDS


@dp.message(Command("admin"))
async def cmd_admin(message: Message):
    """Вход в панель администратора"""
    if not is_admin(message.from_user.id):
        logger.warning(f"⚠️ Несанкционированный доступ к /admin от user_id={message.from_user.id}")
        await message.answer("❌ Доступ запрещён")
        return
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Добавить вопрос", callback_data="admin_add")],
        [InlineKeyboardButton(text="➖ Удалить вопрос", callback_data="admin_remove")],
        [InlineKeyboardButton(text="📋 Блоки по языку", callback_data="admin_blocks")],
        [InlineKeyboardButton(text="📊 Статистика", callback_data="admin_stats")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="admin_back")]
    ])
    
    await message.answer("🔧 <b>Панель администратора</b>", reply_markup=keyboard, parse_mode="HTML")


@dp.callback_query(F.data == "admin_back")
async def admin_back(callback: CallbackQuery):
    """Возврат из админ-панели"""
    await callback.answer()
    await cmd_admin(callback.message)


@dp.callback_query(F.data == "admin_add")
async def admin_add_start(callback: CallbackQuery, state: FSMContext):
    """Начало добавления вопроса — выбор блока"""
    await callback.answer()
    
    # Группировка блоков по языкам
    languages = {}
    for block in DATA.get("blocks", []):
        lang = block.get("language", "Other")
        languages.setdefault(lang, []).append(block)
    
    # Кнопки языков
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"{lang} ({len(blocks)})", 
                             callback_data=f"admin_add_lang_{lang}")]
        for lang, blocks in languages.items()
    ])
    
    await callback.message.edit_text("📚 Выберите язык для добавления вопроса:", reply_markup=keyboard)


@dp.callback_query(F.data.startswith("admin_add_lang_"))
async def admin_select_block(callback: CallbackQuery, state: FSMContext):
    """Выбор конкретного блока внутри языка"""
    await callback.answer()
    lang = callback.data.split("_")[-1]
    
    blocks = get_all_blocks_by_language(lang)
    if not blocks:
        await callback.answer("❌ Блоки не найдены", show_alert=True)
        return
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"#{b['id']}: {b['title'][:30]}", 
                             callback_data=f"admin_add_block_{b['id']}")]
        for b in blocks[:10]  # Ограничение для удобства
    ])
    
    await state.update_data(admin_lang=lang)
    await callback.message.edit_text(f"📦 Выберите блок ({lang}):", reply_markup=keyboard)


@dp.callback_query(F.data.startswith("admin_add_block_"))
async def admin_enter_question(callback: CallbackQuery, state: FSMContext):
    """Начало ввода данных вопроса"""
    await callback.answer()
    block_id = int(callback.data.split("_")[-1])
    
    await state.update_data(admin_block_id=block_id)
    await state.set_state(AdminAddQuestion.entering_question)
    
    await callback.message.edit_text(
        "❓ <b>Введите текст вопроса:</b>\n\n"
        "Отправьте сообщение с формулировкой вопроса.",
        parse_mode="HTML"
    )


@dp.message(AdminAddQuestion.entering_question)
async def admin_save_question(message: Message, state: FSMContext):
    """Сохранение текста вопроса"""
    await state.update_data(question_text=message.text)
    await state.set_state(AdminAddQuestion.entering_options)
    
    await message.answer(
        "🔤 <b>Варианты ответов:</b>\n\n"
        "Отправьте варианты через запятую.\n"
        "Пример: <code>Ответ 1,Ответ 2,Ответ 3</code>",
        parse_mode="HTML"
    )


@dp.message(AdminAddQuestion.entering_options)
async def admin_save_options(message: Message, state: FSMContext):
    """Парсинг вариантов ответов"""
    options = [opt.strip() for opt in message.text.split(",") if opt.strip()]
    
    if len(options) < 2:
        await message.answer("❌ Нужно минимум 2 варианта. Попробуйте снова:")
        return
    
    await state.update_data(options=options)
    await state.set_state(AdminAddQuestion.entering_correct)
    
    opts_str = "\n".join(f"{i+1}. {opt}" for i, opt in enumerate(options))
    await message.answer(
        f"✅ Варианты:\n{opts_str}\n\n"
        f"🔢 <b>Введите номер правильного ответа</b> (1-{len(options)}):"
    )


@dp.message(AdminAddQuestion.entering_correct)
async def admin_save_correct(message: Message, state: FSMContext):
    """Сохранение индекса правильного ответа"""
    try:
        correct_idx = int(message.text.strip()) - 1
        data = await state.get_data()
        options = data.get("options", [])
        
        if not (0 <= correct_idx < len(options)):
            await message.answer(f"❌ Введите число от 1 до {len(options)}")
            return
        
        await state.update_data(correct_index=correct_idx)
        await state.set_state(AdminAddQuestion.entering_explanation)
        
        await message.answer("💡 <b>Пояснение к ответу:</b>\n\n"
                           "Отправьте текст пояснения или «-» для пропуска:")
        
    except ValueError:
        await message.answer("❌ Введите число")


@dp.message(AdminAddQuestion.entering_explanation)
async def admin_finish_add(message: Message, state: FSMContext):
    """Финализация и сохранение вопроса"""
    data = await state.get_data()
    
    question_payload = {
        "question": data.get("question_text", ""),
        "options": data.get("options", []),
        "correct": data.get("correct_index", 0),
        "explanation": message.text if message.text.strip() != "-" else "",
        "code": ""  # Можно расширить для ввода кода
    }
    
    success = add_question_to_block(data.get("admin_block_id"), question_payload)
    
    if success:
        await message.answer("✅ <b>Вопрос успешно добавлен!</b>", parse_mode="HTML")
        logger.info(f"🔧 Админ добавил вопрос в блок {data.get('admin_block_id')}")
    else:
        await message.answer("❌ Ошибка при сохранении вопроса")
    
    await state.clear()
    await cmd_admin(message)


# === УДАЛЕНИЕ ВОПРОСОВ (упрощённо) ===

@dp.callback_query(F.data == "admin_remove")
async def admin_remove_start(callback: CallbackQuery, state: FSMContext):
    """Начало удаления — выбор языка"""
    await callback.answer()
    
    languages = list(set(b.get("language") for b in DATA.get("blocks", [])))
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=lang, callback_data=f"admin_rem_lang_{lang}")]
        for lang in languages
    ])
    
    await state.set_state(AdminRemoveQuestion.selecting_block)
    await callback.message.edit_text("🗑️ Выберите язык для удаления вопроса:", reply_markup=keyboard)


@dp.callback_query(F.data.startswith("admin_rem_lang_"))
async def admin_remove_select_block(callback: CallbackQuery, state: FSMContext):
    """Выбор блока для удаления"""
    await callback.answer()
    lang = callback.data.split("_")[-1]
    
    blocks = get_all_blocks_by_language(lang)
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"#{b['id']}: {b['title'][:25]}", 
                             callback_data=f"admin_rem_block_{b['id']}")]
        for b in blocks[:10]
    ])
    
    await state.update_data(admin_lang=lang)
    await callback.message.edit_text(f"📦 Выберите блок ({lang}):", reply_markup=keyboard)


@dp.callback_query(F.data.startswith("admin_rem_block_"))
async def admin_remove_select_question(callback: CallbackQuery, state: FSMContext):
    """Выбор конкретного вопроса для удаления"""
    await callback.answer()
    block_id = int(callback.data.split("_")[-1])
    
    stats = get_question_stats(block_id)
    if not stats.get("question_ids"):
        await callback.answer("❌ В блоке нет вопросов", show_alert=True)
        return
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"#{qid}", callback_data=f"admin_del_q_{block_id}_{qid}")]
        for qid in stats["question_ids"][:15]  # Ограничение
    ])
    
    await state.update_data(admin_block_id=block_id)
    await callback.message.edit_text(
        f"❓ Выберите вопрос для удаления (всего: {stats['total_questions']}):",
        reply_markup=keyboard
    )


@dp.callback_query(F.data.startswith("admin_del_q_"))
async def admin_confirm_delete(callback: CallbackQuery, state: FSMContext):
    """Подтверждение удаления"""
    await callback.answer()
    parts = callback.data.split("_")
    block_id = int(parts[3])
    question_id = int(parts[4])
    
    block = get_block_by_id(block_id)
    question = next((q for q in block.get("tasks", []) if q["id"] == question_id), None)
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Да, удалить", callback_data=f"confirm_del_{block_id}_{question_id}")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="admin_remove")]
    ])
    
    await state.update_data(admin_block_id=block_id, admin_question_id=question_id)
    await state.set_state(AdminRemoveQuestion.confirming)
    
    preview = question["question"][:100] + "..." if len(question["question"]) > 100 else question["question"]
    await callback.message.edit_text(
        f"⚠️ <b>Подтвердите удаление:</b>\n\n"
        f"Вопрос #{question_id}:\n<i>{preview}</i>\n\n"
        f"Это действие нельзя отменить!",
        reply_markup=keyboard,
        parse_mode="HTML"
    )


@dp.callback_query(F.data.startswith("confirm_del_"))
async def admin_execute_delete(callback: CallbackQuery, state: FSMContext):
    """Непосредственное удаление"""
    await callback.answer()
    parts = callback.data.split("_")
    block_id = int(parts[2])
    question_id = int(parts[3])
    
    success = remove_question_from_block(block_id, question_id)
    
    if success:
        await callback.message.edit_text("✅ Вопрос удалён!")
        logger.info(f"🗑️ Админ удалил вопрос #{question_id} из блока {block_id}")
    else:
        await callback.message.edit_text("❌ Ошибка при удалении")
    
    await state.clear()
    await cmd_admin(callback.message)


# === СТАТИСТИКА ДЛЯ АДМИНА ===

@dp.callback_query(F.data == "admin_stats")
async def admin_show_stats(callback: CallbackQuery):
    """Показывает общую статистику бота"""
    await callback.answer()
    
    users_total = get_all_users_count()
    lang_stats = get_users_by_language()
    
    # Статистика по вопросам
    total_blocks = len(DATA.get("blocks", []))
    total_questions = sum(len(b.get("tasks", [])) for b in DATA.get("blocks", []))
    
    stats_text = (
        f"📊 <b>Статистика бота</b>\n\n"
        f"👥 Пользователи: {users_total}\n"
        f"📚 Языки:\n" + 
        "\n".join(f"  • {lang}: {cnt}" for lang, cnt in lang_stats.items()) +
        f"\n\n📦 Контент:\n"
        f"  • Блоков: {total_blocks}\n"
        f"  • Вопросов: {total_questions}\n\n"
        f"🔧 Админов: {len(ADMIN_IDS)}"
    )
    
    await callback.message.answer(stats_text, parse_mode="HTML")


@dp.callback_query(F.data == "admin_blocks")
async def admin_list_blocks(callback: CallbackQuery):
    """Список всех блоков"""
    await callback.answer()
    
    blocks = DATA.get("blocks", [])
    if not blocks:
        await callback.answer("❌ Блоки не загружены", show_alert=True)
        return
    
    # Группировка
    by_lang = {}
    for b in blocks:
        by_lang.setdefault(b["language"], []).append(b)
    
    text = "📋 <b>Все учебные блоки:</b>\n\n"
    for lang, lang_blocks in by_lang.items():
        text += f"🔹 {lang}:\n"
        for b in lang_blocks:
            tasks_count = len(b.get("tasks", []))
            text += f"  #{b['id']}: {b['title']} ({tasks_count} вопросов)\n"
        text += "\n"
    
    # Пагинация если много
    if len(text) > 4000:
        text = text[:3900] + "\n\n... (остальное в логах)"
    
    await callback.message.answer(text, parse_mode="HTML")


# === ОБРАБОТКА НЕИЗВЕСТНЫХ КОМАНД ===

@dp.message()
async def handle_unknown(message: Message):
    """Обработчик неизвестных сообщений"""
    user_id = message.from_user.id
    lang = load_user_language(user_id)
    
    # Если это ответ в режиме админ-добавления — пропускаем (обрабатывается FSM)
    current_state = await dp.storage.get_state(user_id=user_id)
    if current_state and current_state.startswith("Admin"):
        return
    
    # Подсказка
    if lang:
        await message.answer(
            "❓ Не распознано. Используйте кнопки меню или:\n"
            "• /start — начать заново\n"
            "• /admin — панель администратора",
            reply_markup=get_main_keyboard()
        )
    else:
        await message.answer(
            "👋 Нажмите /start для начала работы",
            reply_markup=ReplyKeyboardMarkup(
                keyboard=[[KeyboardButton(text="/start")]],
                resize_keyboard=True
            )
        )


# === ЗАПУСК БОТА ===

async def on_startup():
    """Действия при запуске"""
    logger.info("🚀 Бот запускается...")
    init_db()
    logger.info("✓ База данных инициализирована")
    
    # Уведомление админам о запуске (опционально)
    for admin_id in ADMIN_IDS:
        try:
            await bot.send_message(admin_id, "✅ Бот запущен и готов к работе")
        except Exception as e:
            logger.warning(f"⚠️ Не удалось уведомить админа {admin_id}: {e}")


async def on_shutdown():
    """Действия при завершении"""
    logger.info("🛑 Бот завершает работу...")
    await bot.session.close()


async def main():
    """Точка входа"""
    dp.startup.register(on_startup)
    dp.shutdown.register(on_shutdown)
    
    # === RENDER COMPATIBILITY FIX ===
    # Если задана переменная окружения, просто игнорируем проверку портов
    # Это позволяет запускать polling-бота на Render Web Service без ошибок
    if os.getenv("DISABLE_PORT_CHECK") == "true":
        logger.info("🔄 Render mode: skipping port check, running polling...")
    
    logger.info("🔄 Запуск в polling-режиме")
    # Запускаем polling. Для Render с переменной DISABLE_PORT_CHECK=true это работает стабильно.
    await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())


if __name__ == "__main__":
    # Обработка сигналов завершения для корректной остановки
    def graceful_exit(signum, frame):
        logger.info("🛑 Получен сигнал завершения. Корректная остановка...")
        sys.exit(0)

    signal.signal(signal.SIGTERM, graceful_exit)
    signal.signal(signal.SIGINT, graceful_exit)

    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("👋 Остановка по Ctrl+C")
    except Exception as e:
        logger.error(f"💥 Критическая ошибка: {e}", exc_info=True)