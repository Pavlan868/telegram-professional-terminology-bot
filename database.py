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

# --- НОВЫЕ ФУНКЦИИ ДЛЯ АДМИНКИ И СПРАВКИ ---

def get_all_users_stats():
    """Возвращает статистику всех пользователей и список неактивных"""
    conn = _get_conn()
    cur = conn.cursor()
    
    # Всего пользователей
    cur.execute("SELECT COUNT(*) FROM users")
    total = cur.fetchone()[0]
    
    # Неактивные (нет активности 7 дней)
    cur.execute("""
        SELECT user_id, username, first_name, last_name, last_seen 
        FROM users 
        WHERE last_seen < NOW() - INTERVAL '7 days'
        ORDER BY last_seen DESC
        LIMIT 50
    """)
    inactive = cur.fetchall()
    
    cur.close()
    conn.close()
    
    return {
        "total": total,
        "inactive": [dict(u) for u in inactive]
    }

def get_all_users_list(limit=20):
    """Возвращает список пользователей для админки"""
    conn = _get_conn()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute("SELECT * FROM users ORDER BY last_seen DESC LIMIT %s", (limit,))
    users = cur.fetchall()
    cur.close()
    conn.close()
    return users

def get_inactive_users_count():
    conn = _get_conn()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM users WHERE last_seen < NOW() - INTERVAL '7 days'")
    count = cur.fetchone()[0]
    cur.close()
    conn.close()
    return count

# --- Конец новых функций ---

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

# === РАБОТА С ВОПРОСАМИ (data.json) ===

def add_question_to_block(block_id: int, question_dict: dict) -> bool:
    try:
        with open("data.json", "r", encoding="utf-8") as f:
            data = json.load(f)
        
        for block in data.get("blocks", []):
            if block.get("id") == block_id:
                tasks = block.get("tasks", [])
                new_id = max((q.get("id", 0) for q in tasks), default=0) + 1
                
                new_question = {
                    "id": new_id,
                    "question": question_dict.get("question", ""),
                    "options": question_dict.get("options", []),
                    "correct": question_dict.get("correct", 0),
                    "explanation": question_dict.get("explanation", ""),
                    "code": question_dict.get("code", ""),
                    "correct_text": question_dict.get("correct_text", ""),
                    "difficulty": question_dict.get("difficulty", "medium")
                }
                tasks.append(new_question)
                block["tasks"] = tasks
                
                with open("data.json", "w", encoding="utf-8") as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)
                
                return True
        return False
    except Exception as e:
        print(f"[ERROR] add_question_to_block: {e}")
        return False

def delete_question_from_block(block_id: int, question_id: int) -> bool:
    """Удаляет вопрос из data.json по ID"""
    try:
        with open("data.json", "r", encoding="utf-8") as f:
            data = json.load(f)
        
        for block in data.get("blocks", []):
            if block.get("id") == block_id:
                tasks = block.get("tasks", [])
                original_count = len(tasks)
                block["tasks"] = [q for q in tasks if q.get("id") != question_id]
                
                if len(block["tasks"]) < original_count:
                    with open("data.json", "w", encoding="utf-8") as f:
                        json.dump(data, f, ensure_ascii=False, indent=2)
                    return True
                else:
                    return False
        return False
    except Exception as e:
        print(f"[ERROR] delete_question_from_block: {e}")
        return False

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