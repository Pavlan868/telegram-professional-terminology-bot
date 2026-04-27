# config.py
# Конфигурация бота - НЕ КОММИТИТЬ В РЕПОЗИТОРИЙ!

import os
from dotenv import load_dotenv

# Загрузка переменных из .env
load_dotenv()

# Токен бота
BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise ValueError("❌ Переменная окружения BOT_TOKEN не задана! Проверьте .env файл")

# Список ID администраторов (через запятую в .env)
ADMIN_IDS_RAW = os.getenv("ADMIN_IDS", "")
ADMIN_IDS = [int(x.strip()) for x in ADMIN_IDS_RAW.split(",") if x.strip().isdigit()]

# Настройки прогресса
UNLOCK_THRESHOLD = float(os.getenv("UNLOCK_THRESHOLD", "0.8"))  # 80% для разблокировки
MIN_QUESTIONS_PER_BLOCK = int(os.getenv("MIN_QUESTIONS", "5"))  # Мин. вопросов в блоке

# Настройки деплоя
RENDER_MODE = os.getenv("RENDER_MODE", "false").lower() == "true"
WEBHOOK_URL = os.getenv("WEBHOOK_URL", "")  # Для webhook-режима на Render