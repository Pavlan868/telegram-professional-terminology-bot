import sqlite3
import json
import os

DB_PATH = "bot_data.db"

def init_db():
    if not os.path.exists(DB_PATH):
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS user_languages (
                user_id INTEGER PRIMARY KEY,
                selected_language TEXT
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS user_progress (
                user_id INTEGER PRIMARY KEY,
                language_data TEXT
            )
        """)
        conn.commit()
        conn.close()

def save_user_language(user_id, lang):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute(
        "INSERT OR REPLACE INTO user_languages (user_id, selected_language) VALUES (?, ?)",
        (user_id, lang)
    )
    conn.commit()
    conn.close()

def load_user_language(user_id):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT selected_language FROM user_languages WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    conn.close()
    return row[0] if row else None

def save_progress(user_id, progress_dict):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    # Нормализация ключей (удаление пробелов)
    cleaned = {}
    for lang, data in progress_dict.items():
        clean_lang = lang.strip()
        clean_data = {k.strip(): v for k, v in data.items()}
        cleaned[clean_lang] = clean_data
    data_str = json.dumps(cleaned, ensure_ascii=False)
    cursor.execute(
        "INSERT OR REPLACE INTO user_progress (user_id, language_data) VALUES (?, ?)",
        (user_id, data_str)
    )
    conn.commit()
    conn.close()

def load_progress(user_id):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT language_data FROM user_progress WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    conn.close()

    default_progress = {
        "Python": {"current_block": 1, "completed_blocks": [], "current_attempt": None},
        "C++": {"current_block": 6, "completed_blocks": [], "current_attempt": None},
        "Java": {"current_block": 11, "completed_blocks": [], "current_attempt": None},
        "JavaScript": {"current_block": 16, "completed_blocks": [], "current_attempt": None},
        "Git": {"current_block": 21, "completed_blocks": [], "current_attempt": None}
    }

    if row and row[0]:
        try:
            saved_data = json.loads(row[0])
            for lang in default_progress:
                for key in saved_data:
                    if key.strip() == lang:
                        default_progress[lang].update(saved_data[key])
                        break
        except (json.JSONDecodeError, TypeError):
            pass

    return default_progress