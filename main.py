# main.py
# ФИНАЛЬНАЯ ВЕРСИЯ - на основе твоего рабочего кода
import asyncio
import json
import logging
import os
import random
from aiogram import Bot, Dispatcher
from aiogram.types import Message, ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from aiogram.filters import Command
from database import init_db, load_user_language, save_user_language, load_progress, save_progress

logging.basicConfig(level=logging.INFO)

# === ТОКЕН ===
BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise ValueError("❌ BOT_TOKEN не задана!")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# === ДАННЫЕ ===
try:
    with open("data.json", "r", encoding="utf-8") as f:
        DATA = json.load(f)
except FileNotFoundError:
    print("❌ data.json не найден!")
    exit(1)
except json.JSONDecodeError as e:
    print(f"❌ Ошибка в data.json: {e}")
    exit(1)

FIRST_BLOCK_ID = {"Python": 1, "C++": 6, "Java": 11, "JavaScript": 16, "Git": 21}

# === ADMIN IDS ===
ADMIN_IDS = [int(x) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip().isdigit()]

# === HELPERS ===
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

# === КЛАВИАТУРЫ ===
def get_main_keyboard(uid):
    lang = load_user_language(uid)
    if not lang:
        return get_language_keyboard()
    
    progress = load_progress(uid)
    lang_data = progress.get(lang.strip(), {})
    current_block = lang_data.get("current_block", FIRST_BLOCK_ID[lang])
    completed_blocks = lang_data.get("completed_blocks", [])

    keyboard = [
        [KeyboardButton(text="📚 Обучение")],
        [KeyboardButton(text="🧠 Задание")],
        [KeyboardButton(text="🔄 Сменить язык")]  # ✅ Отдельная кнопка, всегда видна
    ]

    # Кнопки повтора — только после первого блока
    if current_block != FIRST_BLOCK_ID[lang] or completed_blocks:
        keyboard.append([KeyboardButton(text="🔁 Повторить обучение")])
        keyboard.append([KeyboardButton(text="🧪 Повторить тест")])
    
    # Админка — только для админов
    if is_admin(uid):
        keyboard.append([KeyboardButton(text="⚙️ Админка")])

    return ReplyKeyboardMarkup(keyboard=keyboard, resize_keyboard=True)

def get_language_keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🐍 Python")],
            [KeyboardButton(text="CppClass C++")],
            [KeyboardButton(text="☕ Java")],
            [KeyboardButton(text="📜 JavaScript")],
            [KeyboardButton(text="🌱 Git")]
        ],
        resize_keyboard=True
    )

def get_answer_buttons():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="1", callback_data="ans_1")],
        [InlineKeyboardButton(text="2", callback_data="ans_2")],
        [InlineKeyboardButton(text="3", callback_data="ans_3")]
    ])

# === START ===
@dp.message(Command("start"))
async def start(message: Message):
    uid = message.from_user.id
    lang = load_user_language(uid)
    if lang is None:
        await message.answer("👋 Привет! Выбери язык для обучения:", reply_markup=get_language_keyboard())
    else:
        await message.answer("📖 Главное меню:", reply_markup=get_main_keyboard(uid))

# === ВЫБОР ЯЗЫКА ===
@dp.message(lambda m: m.text in ["🐍 Python", "CppClass C++", "☕ Java", "📜 JavaScript", "🌱 Git"])
async def handle_language_selection(message: Message):
    uid = message.from_user.id
    lang_map = {
        "🐍 Python": "Python", "CppClass C++": "C++", "☕ Java": "Java",
        "📜 JavaScript": "JavaScript", "🌱 Git": "Git"
    }
    lang = lang_map.get(message.text)
    if not lang:
        await message.answer("Пожалуйста, выбери язык из списка.")
        return

    save_user_language(uid, lang)
    progress = load_progress(uid)

    first_block_id = FIRST_BLOCK_ID[lang]
    if lang not in progress:
        progress[lang] = {"current_block": first_block_id, "completed_blocks": [], "current_attempt": None}
        save_progress(uid, progress)

    await message.answer(f"✅ Выбран: **{lang}**", parse_mode=None)
    await message.answer("📖 Главное меню:", reply_markup=get_main_keyboard(uid))

# === СМЕНИТЬ ЯЗЫК ===
@dp.message(lambda m: m.text == "🔄 Сменить язык")
async def change_language(message: Message):
    uid = message.from_user.id
    progress = load_progress(uid)
    lang = load_user_language(uid)
    if lang and progress.get(lang, {}).get("current_attempt"):
        await message.answer("❗ Сначала заверши текущий тест.")
        return
    await message.answer("📌 Выбери новый язык:", reply_markup=get_language_keyboard())

# === ОБУЧЕНИЕ ===
@dp.message(lambda m: m.text == "📚 Обучение")
async def learn(message: Message):
    uid = message.from_user.id
    lang = load_user_language(uid)
    if not lang:
        await message.answer("Сначала выбери язык!", reply_markup=get_language_keyboard())
        return
    
    progress = load_progress(uid)
    lang_data = progress.get(lang, {})
    current_block_id = lang_data.get("current_block", FIRST_BLOCK_ID[lang])

    block = next((b for b in DATA["blocks"] if b["id"] == current_block_id and b["language"] == lang), None)
    if not block or not block.get("terms"):
        await message.answer("📭 В этом блоке пока нет терминов.")
        return

    terms_text = "\n\n".join([f"**{t['term']}**\n_{t['definition']}_\n```\n{t['example']}\n```" for t in block["terms"]])
    await message.answer(f"📘 **{block['title']}**\n\n{terms_text}", parse_mode=None)

# === ЗАДАНИЕ ===
@dp.message(lambda m: m.text == "🧠 Задание")
async def task(message: Message):
    uid = message.from_user.id
    lang = load_user_language(uid)
    if not lang:
        await message.answer("Сначала выбери язык!", reply_markup=get_language_keyboard())
        return
    
    progress = load_progress(uid)
    lang_data = progress.get(lang, {})
    
    if lang_data.get("current_attempt"):
        await message.answer("❗ У тебя уже запущен тест. Ответь на текущий вопрос.")
        return

    current_block_id = lang_data.get("current_block", FIRST_BLOCK_ID[lang])
    block = next((b for b in DATA["blocks"] if b["id"] == current_block_id and b["language"] == lang), None)
    if not block or not block.get("tasks"):
        await message.answer("📭 В этом блоке пока нет заданий.")
        return

    selected = random.sample(block["tasks"], min(5, len(block["tasks"])))
    new_attempt = {"block_id": current_block_id, "questions": selected, "index": 0, "correct": 0, "total": len(selected), "mode": "block"}
    lang_data["current_attempt"] = new_attempt
    await async_save_progress(uid, progress)

    q = selected[0]
    code = f"```\n{q['code']}\n```" if q.get("code") else ""
    options_text = "\n".join([f"{i+1}. {opt}" for i, opt in enumerate(q["options"])])
    text = f"❓ {q['question']}\n\n{code}\n\n{options_text}"
    await message.answer(text, parse_mode=None, reply_markup=get_answer_buttons())

# === ПОВТОРИТЬ ОБУЧЕНИЕ ===
@dp.message(lambda m: m.text == "🔁 Повторить обучение")
async def repeat_learn(message: Message):
    uid = message.from_user.id
    lang = load_user_language(uid)
    if not lang:
        await message.answer("Сначала выбери язык!", reply_markup=get_language_keyboard())
        return
    
    progress = load_progress(uid)
    lang_data = progress.get(lang, {})
    if lang_data.get("current_attempt"):
        await message.answer("❗ Сначала заверши текущий тест.")
        return

    completed = lang_data.get("completed_blocks", [])
    current_block = lang_data.get("current_block", FIRST_BLOCK_ID[lang])
    all_block_ids = set(completed + [current_block])

    blocks_to_show = [b for b in DATA["blocks"] if b["language"] == lang and b["id"] in all_block_ids]
    if not blocks_to_show:
        await message.answer("📭 Нет пройденных тем для повторения.")
        return

    buttons = [[InlineKeyboardButton(text=block["title"], callback_data=f"repeat_block_{block['id']}")] for block in blocks_to_show]
    await message.answer("📚 Выбери тему для повторения:", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))

@dp.callback_query(lambda c: c.data.startswith("repeat_block_"))
async def handle_repeat_block_selection(callback: CallbackQuery):
    await callback.answer()
    uid = callback.from_user.id
    lang = load_user_language(uid)
    if not lang:
        await callback.message.answer("Сначала выбери язык!")
        return

    try:
        block_id = int(callback.data.split("_")[-1])
    except ValueError:
        await callback.answer("❌ Некорректный выбор.")
        return

    block = next((b for b in DATA["blocks"] if b["id"] == block_id and b["language"] == lang), None)
    if not block or not block.get("terms"):
        await callback.message.answer("📭 В этой теме нет терминов.")
        return

    terms_text = "\n\n".join([f"**{t['term']}**\n_{t['definition']}_\n```\n{t['example']}\n```" for t in block["terms"]])
    await callback.message.answer(f"📘 **{block['title']}**\n\n{terms_text}", parse_mode=None)

# === ПОВТОРИТЬ ТЕСТ ===
@dp.message(lambda m: m.text == "🧪 Повторить тест")
async def repeat_test(message: Message):
    uid = message.from_user.id
    lang = load_user_language(uid)
    if not lang:
        await message.answer("Сначала выбери язык!", reply_markup=get_language_keyboard())
        return
    
    progress = load_progress(uid)
    lang_data = progress.get(lang, {})
    if lang_data.get("current_attempt"):
        await message.answer("❗ У тебя уже запущен тест.")
        return

    completed = lang_data.get("completed_blocks", [])
    current_block = lang_data.get("current_block", FIRST_BLOCK_ID[lang])
    all_block_ids = set(completed + [current_block])

    all_questions = []
    for block in DATA["blocks"]:
        if block["language"] == lang and block["id"] in all_block_ids and block.get("tasks"):
            all_questions.extend(block["tasks"])

    if not all_questions:
        await message.answer("📭 Нет вопросов для теста.")
        return

    selected = random.sample(all_questions, min(10, len(all_questions)))
    new_attempt = {"block_id": -1, "questions": selected, "index": 0, "correct": 0, "total": len(selected), "mode": "repeat"}
    lang_data["current_attempt"] = new_attempt
    await async_save_progress(uid, progress)

    q = selected[0]
    code = f"```\n{q['code']}\n```" if q.get("code") else ""
    options_text = "\n".join([f"{i+1}. {opt}" for i, opt in enumerate(q["options"])])
    text = f"❓ Вопрос 1 из {len(selected)}:\n\n{q['question']}\n\n{code}\n\n{options_text}"
    await message.answer(text, parse_mode=None, reply_markup=get_answer_buttons())

# === ОТВЕТЫ ===
@dp.callback_query(lambda c: c.data.startswith("ans_"))
async def handle_inline_answer(callback: CallbackQuery):
    await callback.answer()  # 🔥 Обязательно первым!

    uid = callback.from_user.id
    lang = load_user_language(uid)
    if not lang:
        await callback.message.answer("Выбери язык!")
        return

    progress = load_progress(uid)
    lang_data = progress.get(lang, {})
    attempt = lang_data.get("current_attempt")
    if not attempt:
        await callback.message.answer("❌ Нет активного теста.")
        return

    idx = attempt["index"]
    if idx >= attempt["total"]:
        return

    q = attempt["questions"][idx]
    answer_num = int(callback.data.split("_")[1])
    is_correct = (answer_num - 1 == q["correct"])

    if is_correct:
        attempt["correct"] += 1
        await callback.message.answer("✅ Верно!", parse_mode=None)
    else:
        await callback.message.answer(f"❌ Нет. Правильно: {q['options'][q['correct']]}\n\n💡 {q['explanation']}", parse_mode=None)

    attempt["index"] += 1
    await async_save_progress(uid, progress)

    if attempt["index"] < attempt["total"]:
        q_next = attempt["questions"][attempt["index"]]
        total = attempt["total"]
        code = f"```\n{q_next['code']}\n```" if q_next.get("code") else ""
        options_text = "\n".join([f"{i+1}. {opt}" for i, opt in enumerate(q_next["options"])])
        prefix = f"Вопрос {attempt['index'] + 1} из {total}:\n\n" if attempt.get("mode") == "repeat" else ""
        text = f"{prefix}❓ {q_next['question']}\n\n{code}\n\n{options_text}"
        await callback.message.answer(text, parse_mode=None, reply_markup=get_answer_buttons())
    else:
        correct = attempt["correct"]
        total = attempt["total"]
        perc = correct / total
        mode = attempt.get("mode", "block")

        if mode == "block" and perc >= 0.8 and attempt["block_id"] != -1:
            next_block_id = attempt["block_id"] + 1
            next_block = next((b for b in DATA["blocks"] if b["id"] == next_block_id and b["language"] == lang), None)
            if next_block:
                lang_data["completed_blocks"].append(attempt["block_id"])
                lang_data["current_block"] = next_block_id
                await callback.message.answer(f"🎉 Отлично! Следующая тема: **{next_block['title']}**", parse_mode=None, reply_markup=get_main_keyboard(uid))
            else:
                await callback.message.answer("🏆 Все темы пройдены!", reply_markup=get_main_keyboard(uid))
        elif mode == "repeat":
            await callback.message.answer(f"✅ Тест завершён!\nПравильных: {correct} из {total} ({perc:.0%})")
            await callback.message.answer("📖 Главное меню:", reply_markup=get_main_keyboard(uid))
        else:
            await callback.message.answer("❌ Попробуй ещё раз!", reply_markup=get_main_keyboard(uid))

        lang_data["current_attempt"] = None
        await async_save_progress(uid, progress)

# === АДМИНКА (упрощённая) ===
@dp.message(lambda m: m.text == "⚙️ Админка")
async def admin_panel(message: Message):
    uid = message.from_user.id
    if not is_admin(uid):
        await message.answer("❌ Доступ запрещён")
        return
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Добавить вопрос", callback_data="admin_add")],
        [InlineKeyboardButton(text="📊 Статистика", callback_data="admin_stats")]
    ])
    await message.answer("🔧 Админ-панель", reply_markup=keyboard)

@dp.callback_query(lambda c: c.data == "admin_add")
async def admin_add_start(callback: CallbackQuery):
    await callback.answer()
    langs = list(set(b.get("language") for b in DATA.get("blocks", [])))
    keyboard = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=l, callback_data=f"admin_add_{l}")] for l in langs])
    await callback.message.edit_text("📚 Выбери язык:", reply_markup=keyboard)

@dp.callback_query(lambda c: c.data.startswith("admin_add_"))
async def admin_select_block(callback: CallbackQuery):
    await callback.answer()
    lang = callback.data.split("_")[-1]
    blocks = [b for b in DATA.get("blocks", []) if b.get("language") == lang]
    keyboard = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=f"#{b['id']}", callback_data=f"admin_q_{b['id']}")] for b in blocks[:10]])
    await callback.message.edit_text(f"📦 Блоки ({lang}):", reply_markup=keyboard)
    # Для полноценного добавления вопросов нужна FSM — оставлено как заглушка
    await callback.message.answer("ℹ️ Добавление вопросов через админку — в разработке. Пока редактируй data.json вручную.")

@dp.callback_query(lambda c: c.data == "admin_stats")
async def admin_stats(callback: CallbackQuery):
    await callback.answer()
    await callback.message.answer("📊 Статистика: в разработке")

# === НЕИЗВЕСТНЫЕ СООБЩЕНИЯ ===
@dp.message()
async def handle_unknown(message: Message):
    lang = load_user_language(message.from_user.id)
    if lang:
        await message.answer("❓ Используй кнопки меню или /start", reply_markup=get_main_keyboard(message.from_user.id))
    else:
        await message.answer("👋 Нажми /start", reply_markup=ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="/start")]], resize_keyboard=True))

# === ЗАПУСК ===
async def main():
    init_db()
    print("✅ Бот запущен. Напиши /start в Telegram.")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())