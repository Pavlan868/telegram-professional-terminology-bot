# database.py
# Версия: PostgreSQL с вопросами
import os
import json
import psycopg2
from psycopg2.extras import RealDictCursor
from datetime import datetime

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise ValueError("❌ DATABASE_URL не задана! Проверь переменные окружения на Render")

def _get_conn():
    return psycopg2.connect(DATABASE_URL)

def init_db():
    conn = _get_conn()
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id BIGINT PRIMARY KEY,
            username TEXT,
            first_name TEXT,
            last_name TEXT,
            language TEXT,
            created_at TIMESTAMP DEFAULT NOW(),
            last_seen TIMESTAMP DEFAULT NOW()
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS user_progress (
            user_id BIGINT PRIMARY KEY REFERENCES users(user_id) ON DELETE CASCADE,
            progress_data JSONB DEFAULT '{}',
            updated_at TIMESTAMP DEFAULT NOW()
        )
    """)
    # 🔥 ТАБЛИЦА ВОПРОСОВ
    cur.execute("""
        CREATE TABLE IF NOT EXISTS questions (
            id SERIAL PRIMARY KEY,
            block_id INTEGER NOT NULL,
            question TEXT NOT NULL,
            options JSONB NOT NULL,
            correct INTEGER NOT NULL,
            explanation TEXT,
            code TEXT,
            created_at TIMESTAMP DEFAULT NOW()
        )
    """)
    conn.commit()
    cur.close()
    conn.close()

def register_user(user_id: int, username: str = None, first_name: str = None, last_name: str = None):
    conn = _get_conn()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO users (user_id, username, first_name, last_name, last_seen)
        VALUES (%s, %s, %s, %s, NOW())
        ON CONFLICT (user_id) DO UPDATE SET last_seen = NOW()
    """, (user_id, username, first_name, last_name))
    conn.commit()
    cur.close()
    conn.close()

def get_user_profile(user_id: int) -> dict:
    conn = _get_conn()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute("SELECT * FROM users WHERE user_id = %s", (user_id,))
    row = cur.fetchone()
    cur.close()
    conn.close()
    return dict(row) if row else None

def is_user_registered(user_id: int) -> bool:
    conn = _get_conn()
    cur = conn.cursor()
    cur.execute("SELECT 1 FROM users WHERE user_id = %s", (user_id,))
    exists = cur.fetchone() is not None
    cur.close()
    conn.close()
    return exists

def save_user_language(user_id: int, language: str):
    conn = _get_conn()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO users (user_id, language, last_seen)
        VALUES (%s, %s, NOW())
        ON CONFLICT (user_id) DO UPDATE SET language = %s, last_seen = NOW()
    """, (user_id, language.strip(), language.strip()))
    conn.commit()
    cur.close()
    conn.close()

def load_user_language(user_id: int):
    conn = _get_conn()
    cur = conn.cursor()
    cur.execute("SELECT language FROM users WHERE user_id = %s", (user_id,))
    row = cur.fetchone()
    cur.close()
    conn.close()
    return row[0] if row else None

def save_progress(user_id: int, progress_dict: dict):
    conn = _get_conn()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO user_progress (user_id, progress_data, updated_at)
        VALUES (%s, %s, NOW())
        ON CONFLICT (user_id) DO UPDATE SET progress_data = %s, updated_at = NOW()
    """, (user_id, json.dumps(progress_dict, ensure_ascii=False), json.dumps(progress_dict, ensure_ascii=False)))
    conn.commit()
    cur.close()
    conn.close()

def load_progress(user_id: int) -> dict:
    conn = _get_conn()
    cur = conn.cursor()
    cur.execute("SELECT progress_data FROM user_progress WHERE user_id = %s", (user_id,))
    row = cur.fetchone()
    cur.close()
    conn.close()
    if row and row[0]:
        return row[0] if isinstance(row[0], dict) else json.loads(row[0])
    return {}

def get_all_users_count() -> int:
    conn = _get_conn()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM users")
    count = cur.fetchone()[0]
    cur.close()
    conn.close()
    return count

def get_users_by_language() -> dict:
    conn = _get_conn()
    cur = conn.cursor()
    cur.execute("SELECT language, COUNT(*) FROM users WHERE language IS NOT NULL GROUP BY language")
    result = {row[0]: row[1] for row in cur.fetchall()}
    cur.close()
    conn.close()
    return result

# === РАБОТА С ВОПРОСАМИ В PostgreSQL ===

def add_question_to_db(block_id: int, question_ dict) -> int:
    """Добавляет вопрос в базу данных. Возвращает ID нового вопроса или False."""
    try:
        conn = _get_conn()
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO questions (block_id, question, options, correct, explanation, code)
            VALUES (%s, %s, %s, %s, %s, %s)
            RETURNING id
        """, (
            block_id,
            question_data.get("question", ""),
            json.dumps(question_data.get("options", []), ensure_ascii=False),
            question_data.get("correct", 0),
            question_data.get("explanation", ""),
            question_data.get("code", "")
        ))
        new_id = cur.fetchone()[0]
        conn.commit()
        cur.close()
        conn.close()
        return new_id
    except Exception as e:
        print(f"[DB ERROR] add_question_to_db: {e}")
        return False

def get_questions_for_block(block_id: int) -> list:
    """Получает все вопросы для блока из БД"""
    try:
        conn = _get_conn()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("SELECT * FROM questions WHERE block_id = %s ORDER BY id", (block_id,))
        rows = cur.fetchall()
        cur.close()
        conn.close()
        
        questions = []
        for row in rows:
            questions.append({
                "id": row["id"],
                "question": row["question"],
                "options": row["options"],
                "correct": row["correct"],
                "explanation": row["explanation"],
                "code": row["code"]
            })
        return questions
    except Exception as e:
        print(f"[DB ERROR] get_questions_for_block: {e}")
        return []

def get_all_questions() -> dict:
    """Получает все вопросы сгруппированные по блокам"""
    try:
        conn = _get_conn()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("SELECT * FROM questions ORDER BY block_id, id")
        rows = cur.fetchall()
        cur.close()
        conn.close()
        
        by_block = {}
        for row in rows:
            block_id = row["block_id"]
            if block_id not in by_block:
                by_block[block_id] = []
            by_block[block_id].append({
                "id": row["id"],
                "question": row["question"],
                "options": row["options"],
                "correct": row["correct"],
                "explanation": row["explanation"],
                "code": row["code"]
            })
        return by_block
    except Exception as e:
        print(f"[DB ERROR] get_all_questions: {e}")
        return {}

# === РАБОТА С DATA.JSON (для терминов и блоков) ===

def get_block_by_id(block_id: int):
    try:
        with open("data.json", "r", encoding="utf-8") as f:
            data = json.load(f)
        for block in data.get("blocks", []):
            if block.get("id") == block_id:
                return block
        return None
    except:
        return None

def get_all_blocks_by_language(language: str) -> list:
    try:
        with open("data.json", "r", encoding="utf-8") as f:
            data = json.load(f)
        return [b for b in data.get("blocks", []) if b.get("language") == language]
    except:
        return []

def get_question_stats(block_id: int) -> dict:
    block = get_block_by_id(block_id)
    if not block: return {}
    tasks = block.get("tasks", [])
    return {"total_questions": len(tasks), "question_ids": [t.get("id") for t in tasks]}