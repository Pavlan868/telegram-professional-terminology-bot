import asyncio
import json
import logging
import random
from aiogram import Bot, Dispatcher
from aiogram.types import Message, ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from aiogram.filters import Command
from database import init_db, load_user_language, save_user_language, load_progress, save_progress

logging.basicConfig(level=logging.INFO)
BOT_TOKEN = "7715060788:AAF301Vg4BtYWO7SkQ4z96DJQe1TfRMCBS4"
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# Загрузка данных
try:
    with open("data.json", "r", encoding="utf-8") as f:
        DATA = json.load(f)
except FileNotFoundError:
    print("❌ Ошибка: файл data.json не найден!")
    exit(1)
except json.JSONDecodeError as e:
    print(f"❌ Ошибка в data.json: {e}")
    exit(1)

FIRST_BLOCK_ID = {
    "Python": 1,
    "C++": 6,
    "Java": 11,
    "JavaScript": 16,
    "Git": 21
}

# Асинхронные обёртки для работы с БД
async def async_load_progress(user_id):
    loop = asyncio.get_event_loop()
    from functools import partial
    return await loop.run_in_executor(None, partial(load_progress, user_id))

async def async_save_progress(user_id, data):
    loop = asyncio.get_event_loop()
    from functools import partial
    await loop.run_in_executor(None, partial(save_progress, user_id, data))

def get_main_keyboard(uid):
    lang = load_user_language(uid)
    if not lang:
        return get_language_keyboard()

    progress = load_progress(uid)
    lang_data = progress.get(lang, {})
    current_block = lang_data.get("current_block", FIRST_BLOCK_ID[lang])
    completed_blocks = lang_data.get("completed_blocks", [])

    keyboard = [
        [KeyboardButton(text="📚 Обучение")],
        [KeyboardButton(text="🧠 Задание")]
    ]

    if current_block != FIRST_BLOCK_ID[lang] or completed_blocks:
        keyboard.append([KeyboardButton(text="🔁 Повторить обучение")])
        keyboard.append([KeyboardButton(text="🧪 Повторить тест")])

    keyboard.append([KeyboardButton(text="🌐 Сменить язык")])
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

@dp.message(Command("start"))
async def start(message: Message):
    uid = message.from_user.id
    lang = load_user_language(uid)
    if lang is None:
        await message.answer("Выберите язык программирования для обучения:", reply_markup=get_language_keyboard())
    else:
        await message.answer("Главное меню:", reply_markup=get_main_keyboard(uid))

@dp.message(lambda m: m.text in ["🐍 Python", "CppClass C++", "☕ Java", "📜 JavaScript", "🌱 Git"])
async def handle_language_selection(message: Message):
    uid = message.from_user.id
    lang_map = {
        "🐍 Python": "Python",
        "CppClass C++": "C++",
        "☕ Java": "Java",
        "📜 JavaScript": "JavaScript",
        "🌱 Git": "Git"
    }
    lang = lang_map.get(message.text)
    if not lang:
        await message.answer("Пожалуйста, выберите язык из списка.")
        return

    save_user_language(uid, lang)
    progress = load_progress(uid)

    first_block_id = FIRST_BLOCK_ID[lang]
    if lang not in progress:
        progress[lang] = {
            "current_block": first_block_id,
            "completed_blocks": [],
            "current_attempt": None
        }
        save_progress(uid, progress)

    await message.answer(f"Отлично! Вы выбрали: **{lang}**.", parse_mode=None)
    await message.answer("Главное меню:", reply_markup=get_main_keyboard(uid))

@dp.message(lambda m: m.text == "🌐 Сменить язык")
async def change_language(message: Message):
    uid = message.from_user.id
    progress = load_progress(uid)
    lang = load_user_language(uid)
    if lang and progress.get(lang, {}).get("current_attempt"):
        await message.answer("❗ Сначала завершите текущий тест.")
        return
    await message.answer("Выберите язык программирования для обучения:", reply_markup=get_language_keyboard())

@dp.message(lambda m: m.text == "📚 Обучение")
async def learn(message: Message):
    uid = message.from_user.id
    lang = load_user_language(uid)
    if not lang:
        await message.answer("Сначала выберите язык!", reply_markup=get_language_keyboard())
        return

    progress = load_progress(uid)
    lang_data = progress.get(lang, {})
    current_block_id = lang_data.get("current_block", FIRST_BLOCK_ID[lang])

    block = next((b for b in DATA["blocks"] if b["id"] == current_block_id and b["language"] == lang), None)
    if not block or not block.get("terms"):
        await message.answer("В этом блоке нет терминов.")
        return

    terms_text = "\n\n".join([
        f"**{t['term']}**\n_{t['definition']}_\n```\n{t['example']}\n```"
        for t in block["terms"]
    ])
    await message.answer(f"📘 Тема: **{block['title']}**\n\n{terms_text}", parse_mode=None)

@dp.message(lambda m: m.text == "🧠 Задание")
async def task(message: Message):
    uid = message.from_user.id
    lang = load_user_language(uid)
    if not lang:
        await message.answer("Сначала выберите язык!", reply_markup=get_language_keyboard())
        return

    progress = load_progress(uid)
    lang_data = progress.get(lang, {})
    if lang_data.get("current_attempt"):
        await message.answer("❗ У вас уже запущен тест. Ответьте на текущий вопрос.")
        return

    current_block_id = lang_data.get("current_block", FIRST_BLOCK_ID[lang])
    block = next((b for b in DATA["blocks"] if b["id"] == current_block_id and b["language"] == lang), None)
    if not block or not block.get("tasks"):
        await message.answer("В этом блоке нет заданий.")
        return

    selected = random.sample(block["tasks"], min(5, len(block["tasks"])))
    new_attempt = {
        "block_id": current_block_id,
        "questions": selected,
        "index": 0,
        "correct": 0,
        "total": len(selected),
        "mode": "block"
    }
    lang_data["current_attempt"] = new_attempt
    await async_save_progress(uid, progress)

    q = selected[0]
    code = f"```\n{q['code']}\n```"
    options_text = "\n".join([f"{i+1}. {opt}" for i, opt in enumerate(q["options"])])
    text = f"{q['question']}\n\n{code}\n\n{options_text}"
    buttons = [
        [InlineKeyboardButton(text="1", callback_data="ans_1")],
        [InlineKeyboardButton(text="2", callback_data="ans_2")],
        [InlineKeyboardButton(text="3", callback_data="ans_3")]
    ]
    await message.answer(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))

@dp.message(lambda m: m.text == "🔁 Повторить обучение")
async def repeat_learn(message: Message):
    uid = message.from_user.id
    lang = load_user_language(uid)
    if not lang:
        await message.answer("Сначала выберите язык!", reply_markup=get_language_keyboard())
        return

    progress = load_progress(uid)
    lang_data = progress.get(lang, {})
    if lang_data.get("current_attempt"):
        await message.answer("❗ Сначала завершите текущий тест.")
        return

    completed = lang_data.get("completed_blocks", [])
    current_block = lang_data.get("current_block", FIRST_BLOCK_ID[lang])
    all_block_ids = set(completed + [current_block])

    blocks_to_show = [b for b in DATA["blocks"] if b["language"] == lang and b["id"] in all_block_ids]
    if not blocks_to_show:
        await message.answer("Нет пройденных тем для повторения.")
        return

    buttons = []
    for block in blocks_to_show:
        buttons.append([
            InlineKeyboardButton(text=block["title"], callback_data=f"repeat_block_{block['id']}")
        ])
    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
    await message.answer("Выберите тему для повторения:", reply_markup=keyboard)

@dp.callback_query(lambda c: c.data.startswith("repeat_block_"))
async def handle_repeat_block_selection(callback: CallbackQuery):
    uid = callback.from_user.id
    lang = load_user_language(uid)
    if not lang:
        await callback.answer("Сначала выберите язык!")
        return

    try:
        block_id = int(callback.data.split("_")[-1])
    except ValueError:
        await callback.answer("Некорректный выбор.")
        return

    block = next((b for b in DATA["blocks"] if b["id"] == block_id and b["language"] == lang), None)
    if not block or not block.get("terms"):
        await callback.message.answer("В этой теме нет терминов.")
        return

    terms_text = "\n\n".join([
        f"**{t['term']}**\n_{t['definition']}_\n```\n{t['example']}\n```"
        for t in block["terms"]
    ])
    await callback.message.answer(f"📘 Тема: **{block['title']}**\n\n{terms_text}", parse_mode=None)
    await callback.answer()

@dp.message(lambda m: m.text == "🧪 Повторить тест")
async def repeat_test(message: Message):
    uid = message.from_user.id
    lang = load_user_language(uid)
    if not lang:
        await message.answer("Сначала выберите язык!", reply_markup=get_language_keyboard())
        return

    progress = load_progress(uid)
    lang_data = progress.get(lang, {})
    if lang_data.get("current_attempt"):
        await message.answer("❗ У вас уже запущен тест. Ответьте на текущий вопрос.")
        return

    completed = lang_data.get("completed_blocks", [])
    current_block = lang_data.get("current_block", FIRST_BLOCK_ID[lang])
    all_block_ids = set(completed + [current_block])

    all_questions = []
    for block in DATA["blocks"]:
        if block["language"] == lang and block["id"] in all_block_ids and block.get("tasks"):
            all_questions.extend(block["tasks"])

    if not all_questions:
        await message.answer("Нет вопросов для повторного теста.")
        return

    selected = random.sample(all_questions, min(10, len(all_questions)))
    new_attempt = {
        "block_id": -1,
        "questions": selected,
        "index": 0,
        "correct": 0,
        "total": len(selected),
        "mode": "repeat"
    }
    lang_data["current_attempt"] = new_attempt
    await async_save_progress(uid, progress)

    q = selected[0]
    code = f"```\n{q['code']}\n```"
    options_text = "\n".join([f"{i+1}. {opt}" for i, opt in enumerate(q["options"])])
    text = f"Вопрос 1 из {len(selected)}:\n\n{q['question']}\n\n{code}\n\n{options_text}"
    buttons = [
        [InlineKeyboardButton(text="1", callback_data="ans_1")],
        [InlineKeyboardButton(text="2", callback_data="ans_2")],
        [InlineKeyboardButton(text="3", callback_data="ans_3")]
    ]
    await message.answer(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))

@dp.callback_query(lambda c: c.data.startswith("ans_"))
async def handle_inline_answer(callback: CallbackQuery):
    # 🔥 ОБЯЗАТЕЛЬНО: подтверждаем запрос СРАЗУ
    await callback.answer()

    uid = callback.from_user.id
    lang = load_user_language(uid)
    if not lang:
        await callback.message.answer("Выберите язык!")
        return

    progress = load_progress(uid)
    lang_data = progress.get(lang, {})
    attempt = lang_data.get("current_attempt")
    if not attempt:
        await callback.message.answer("Нет активного теста.")
        return

    idx = attempt["index"]
    if idx >= attempt["total"]:
        return

    q = attempt["questions"][idx]
    answer_num = int(callback.data.split("_")[1])
    is_correct = (answer_num - 1 == q["correct"])

    if is_correct:
        attempt["correct"] += 1
        await callback.message.answer("✅ Верно!")
    else:
        await callback.message.answer(f"❌ Нет. Правильно: {q['options'][q['correct']]}\n\n💡 {q['explanation']}")

    attempt["index"] += 1
    await async_save_progress(uid, progress)

    if attempt["index"] < attempt["total"]:
        q_next = attempt["questions"][attempt["index"]]
        total = attempt["total"]
        code = f"```\n{q_next['code']}\n```"
        options_text = "\n".join([f"{i+1}. {opt}" for i, opt in enumerate(q_next["options"])])
        if attempt.get("mode") == "repeat":
            text = f"Вопрос {attempt['index'] + 1} из {total}:\n\n{q_next['question']}\n\n{code}\n\n{options_text}"
        else:
            text = f"{q_next['question']}\n\n{code}\n\n{options_text}"
        buttons = [
            [InlineKeyboardButton(text="1", callback_data="ans_1")],
            [InlineKeyboardButton(text="2", callback_data="ans_2")],
            [InlineKeyboardButton(text="3", callback_data="ans_3")]
        ]
        await callback.message.answer(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
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
                await callback.message.answer(
                    f"🎉 Отлично! Следующая тема: **{next_block['title']}**",
                    parse_mode=None,
                    reply_markup=get_main_keyboard(uid)
                )
            else:
                await callback.message.answer("🏆 Все темы пройдены!", reply_markup=get_main_keyboard(uid))
        elif mode == "repeat":
            await callback.message.answer(f"✅ Тест завершён!\nПравильных ответов: {correct} из {total} ({perc:.0%})")
            await callback.message.answer("Главное меню:", reply_markup=get_main_keyboard(uid))
        else:
            await callback.message.answer("❌ Попытка не пройдена. Попробуйте снова!", reply_markup=get_main_keyboard(uid))

        lang_data["current_attempt"] = None
        await async_save_progress(uid, progress)

async def main():
    init_db()
    await dp.start_polling(bot)

if __name__ == "__main__":
    print("✅ Бот запущен. Напишите /start в Telegram.")
    asyncio.run(main())