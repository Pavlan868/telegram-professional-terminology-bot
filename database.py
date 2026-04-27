# database.py
# Модуль работы с базой данных SQLite

import sqlite3
import json
import os
from datetime import datetime
from typing import Optional, Dict, Any

DB_PATH = "bot_data.db"


def init_db():
    """Инициализация базы данных: создание таблиц, если не существуют"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # Таблица пользователей
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            first_name TEXT,
            last_name TEXT,
            registered_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            last_seen DATETIME DEFAULT CURRENT_TIMESTAMP,
            is_admin INTEGER DEFAULT 0
        )
    """)
    
    # Таблица выбранных языков
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS user_languages (
            user_id INTEGER PRIMARY KEY,
            language TEXT NOT NULL,
            selected_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
        )
    """)
    
    # Таблица прогресса обучения
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS user_progress (
            user_id INTEGER PRIMARY KEY,
            progress_data TEXT NOT NULL,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
        )
    """)
    
    conn.commit()
    conn.close()


def register_user(user_id: int, username: Optional[str] = None, 
                  first_name: Optional[str] = None, last_name: Optional[str] = None):
    """Регистрирует нового пользователя или обновляет данные существующего"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # Вставка или обновление пользователя
    cursor.execute("""
        INSERT OR REPLACE INTO users (user_id, username, first_name, last_name, last_seen)
        VALUES (?, ?, ?, ?, datetime('now'))
    """, (user_id, username, first_name, last_name))
    
    # Инициализация прогресса, если нет записи
    cursor.execute("""
        INSERT OR IGNORE INTO user_progress (user_id, progress_data)
        VALUES (?, ?)
    """, (user_id, json.dumps({}, ensure_ascii=False)))
    
    conn.commit()
    conn.close()


def get_user_profile(user_id: int) -> Optional[Dict[str, Any]]:
    """Возвращает профиль пользователя или None, если не найден"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT user_id, username, first_name, last_name, registered_at, last_seen, is_admin
        FROM users WHERE user_id = ?
    """, (user_id,))
    
    row = cursor.fetchone()
    conn.close()
    
    if not row:
        return None
    
    return {
        "user_id": row[0],
        "username": row[1],
        "first_name": row[2],
        "last_name": row[3],
        "registered_at": row[4],
        "last_seen": row[5],
        "is_admin": bool(row[6])
    }


def is_user_registered(user_id: int) -> bool:
    """Проверяет, зарегистрирован ли пользователь"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT 1 FROM users WHERE user_id = ?", (user_id,))
    exists = cursor.fetchone() is not None
    conn.close()
    return exists


def save_user_language(user_id: int, language: str):
    """Сохраняет выбранный язык для пользователя"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # Нормализация названия языка
    lang_clean = language.strip().lower().capitalize()
    
    cursor.execute("""
        INSERT OR REPLACE INTO user_languages (user_id, language, selected_at)
        VALUES (?, ?, datetime('now'))
    """, (user_id, lang_clean))
    
    conn.commit()
    conn.close()


def load_user_language(user_id: int) -> Optional[str]:
    """Загружает выбранный язык пользователя"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    cursor.execute("SELECT language FROM user_languages WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    conn.close()
    
    return row[0] if row else None


def _normalize_progress_keys(data: Dict) -> Dict:
    """Нормализует ключи в словаре прогресса (убирает лишние пробелы)"""
    if not isinstance(data, dict):
        return data
    return {
        str(k).strip(): _normalize_progress_keys(v) if isinstance(v, dict) else v
        for k, v in data.items()
    }


def _get_default_progress() -> Dict:
    """Возвращает структуру прогресса по умолчанию для всех языков"""
    return {
        "Python": {"current_block": 1, "completed_blocks": [], "current_attempt": None},
        "C++": {"current_block": 6, "completed_blocks": [], "current_attempt": None},
        "Java": {"current_block": 11, "completed_blocks": [], "current_attempt": None},
        "JavaScript": {"current_block": 16, "completed_blocks": [], "current_attempt": None},
        "Git": {"current_block": 21, "completed_blocks": [], "current_attempt": None},
    }


def save_progress(user_id: int, progress_dict: Dict):
    """Сохраняет прогресс обучения пользователя в БД"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # Нормализация и сериализация
    cleaned = _normalize_progress_keys(progress_dict)
    progress_json = json.dumps(cleaned, ensure_ascii=False)
    
    cursor.execute("""
        INSERT OR REPLACE INTO user_progress (user_id, progress_data, updated_at)
        VALUES (?, ?, datetime('now'))
    """, (user_id, progress_json))
    
    conn.commit()
    conn.close()


def load_progress(user_id: int) -> Dict:
    """Загружает прогресс пользователя, возвращает дефолтный если нет данных"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    cursor.execute("SELECT progress_data FROM user_progress WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    conn.close()
    
    # Дефолтная структура
    default_progress = _get_default_progress()
    
    if not row or not row[0]:
        return default_progress
    
    try:
        saved = json.loads(row[0])
        # Объединяем с дефолтом (на случай добавления новых языков)
        for lang, data in default_progress.items():
            if lang not in saved:
                saved[lang] = data
            elif isinstance(data, dict):
                for key, val in data.items():
                    if key not in saved[lang]:
                        saved[lang][key] = val
        return _normalize_progress_keys(saved)
    except (json.JSONDecodeError, TypeError):
        return default_progress


def get_all_users_count() -> int:
    """Возвращает общее количество зарегистрированных пользователей"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM users")
    count = cursor.fetchone()[0]
    conn.close()
    return count


def get_users_by_language() -> Dict[str, int]:
    """Возвращает статистику: количество пользователей по языкам"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT language, COUNT(*) as cnt FROM user_languages 
        GROUP BY language ORDER BY cnt DESC
    """)
    result = {row[0]: row[1] for row in cursor.fetchall()}
    conn.close()
    return result


# === ФУНКЦИИ ДЛЯ АДМИНИСТРАТОРА ===

def add_question_to_block(block_id: int, question_data: Dict) -> bool:
    """
    Добавляет новый вопрос в указанный блок data.json
    question_data должен содержать: question, options (list), correct (int), explanation, code (опционально)
    """
    try:
        with open("data.json", "r", encoding="utf-8") as f:
            data = json.load(f)
        
        block_found = False
        for block in data.get("blocks", []):
            if block.get("id") == block_id:
                block_found = True
                # Генерация нового ID вопроса
                existing_ids = [q.get("id", 0) for q in block.get("tasks", [])]
                new_id = max(existing_ids, default=0) + 1
                
                # Формирование структуры вопроса
                new_question = {
                    "id": new_id,
                    "question": question_data.get("question", ""),
                    "options": question_data.get("options", []),
                    "correct": question_data.get("correct", 0),
                    "explanation": question_data.get("explanation", ""),
                    "code": question_data.get("code", "")
                }
                
                block.setdefault("tasks", []).append(new_question)
                
                # Сохранение файла
                with open("data.json", "w", encoding="utf-8") as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)
                return True
        
        return not block_found  # False если блок не найден
        
    except Exception as e:
        print(f"[DB ERROR] add_question: {e}")
        return False


def remove_question_from_block(block_id: int, question_id: int) -> bool:
    """Удаляет вопрос по ID из указанного блока"""
    try:
        with open("data.json", "r", encoding="utf-8") as f:
            data = json.load(f)
        
        for block in data.get("blocks", []):
            if block.get("id") == block_id:
                original_count = len(block.get("tasks", []))
                block["tasks"] = [q for q in block.get("tasks", []) if q.get("id") != question_id]
                
                if len(block["tasks"]) < original_count:
                    with open("data.json", "w", encoding="utf-8") as f:
                        json.dump(data, f, ensure_ascii=False, indent=2)
                    return True
                return False  # Вопрос не найден
        
        return False  # Блок не найден
        
    except Exception as e:
        print(f"[DB ERROR] remove_question: {e}")
        return False


def get_block_by_id(block_id: int) -> Optional[Dict]:
    """Возвращает данные блока по ID"""
    try:
        with open("data.json", "r", encoding="utf-8") as f:
            data = json.load(f)
        
        for block in data.get("blocks", []):
            if block.get("id") == block_id:
                return block
        return None
    except Exception:
        return None


def get_all_blocks_by_language(language: str) -> list:
    """Возвращает все блоки для указанного языка"""
    try:
        with open("data.json", "r", encoding="utf-8") as f:
            data = json.load(f)
        
        return [b for b in data.get("blocks", []) if b.get("language") == language]
    except Exception:
        return []


def get_question_stats(block_id: int) -> Dict:
    """Возвращает статистику по вопросам в блоке"""
    block = get_block_by_id(block_id)
    if not block:
        return {}
    
    tasks = block.get("tasks", [])
    return {
        "total_questions": len(tasks),
        "question_ids": [t.get("id") for t in tasks],
        "first_question": tasks[0].get("question") if tasks else None
    }