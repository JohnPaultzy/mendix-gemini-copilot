import sqlite3
import os
from datetime import datetime

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "storage", "chats.db")

def get_db_connection():
    """Mokuha og SQLite connection nga naay timeout ug WAL mode para dili ma-lock."""
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=30.0) # 30 seconds timeout to prevent locking
    conn.execute("PRAGMA journal_mode=WAL;")      # Write-Ahead Logging para smooth multi-threading
    return conn

def init_db():
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS sessions (
                id TEXT PRIMARY KEY,
                title TEXT,
                system_instruction TEXT,
                created_at TIMESTAMP
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT,
                role TEXT,
                content TEXT,
                has_attachment INTEGER DEFAULT 0,
                created_at TIMESTAMP,
                FOREIGN KEY (session_id) REFERENCES sessions (id) ON DELETE CASCADE
            )
        """)
        conn.commit()
    finally:
        conn.close()

def create_session(session_id, title="New Chat", system_instruction=""):
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT OR REPLACE INTO sessions (id, title, system_instruction, created_at) VALUES (?, ?, ?, ?)",
            (session_id, title, system_instruction, datetime.now())
        )
        conn.commit()
    finally:
        conn.close()

def get_all_sessions():
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        # Kuhaon ang sessions nga naay sulod o bag-ong gihimo
        cursor.execute("SELECT id, title, created_at FROM sessions ORDER BY created_at DESC")
        sessions = cursor.fetchall()
        return sessions
    finally:
        conn.close()

def get_session_messages(session_id):
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id, role, content, has_attachment FROM messages WHERE session_id = ? ORDER BY id ASC",
            (session_id,)
        )
        messages = [{"id": row[0], "role": row[1], "content": row[2], "has_attachment": row[3]} for row in cursor.fetchall()]
        return messages
    finally:
        conn.close()

def add_message(session_id, role, content, has_attachment=0):
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO messages (session_id, role, content, has_attachment, created_at) VALUES (?, ?, ?, ?, ?)",
            (session_id, role, content, has_attachment, datetime.now())
        )
        
        # Auto-update sa Title base sa 1st user message
        if role == "user":
            cursor.execute("SELECT COUNT(*) FROM messages WHERE session_id = ?", (session_id,))
            if cursor.fetchone()[0] == 1:
                clean_title = content.replace("\n", " ").strip()
                short_title = (clean_title[:28] + '...') if len(clean_title) > 28 else clean_title
                cursor.execute("UPDATE sessions SET title = ? WHERE id = ?", (short_title, session_id))
                
        conn.commit()
    finally:
        conn.close()

def delete_single_message(message_id):
    """Papason ang usa ka specific nga mensahe."""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM messages WHERE id = ?", (message_id,))
        conn.commit()
    finally:
        conn.close()

def delete_session(session_id):
    """GI-AYO: Gigamit ang 'id' imbes nga 'session_id' para sa sessions table."""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM messages WHERE session_id = ?", (session_id,))
        cursor.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
        conn.commit()
    finally:
        conn.close()

def branch_session_from_message(current_session_id, message_id, new_session_id):
    """Mokopya sa chat history gikan sa sinugdanan hangtod sa gipiling mensahe."""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT title, system_instruction FROM sessions WHERE id = ?", (current_session_id,))
        session_row = cursor.fetchone()
        old_title = session_row[0] if session_row else "Branched Chat"
        sys_prompt = session_row[1] if session_row else ""
        
        new_title = f"🔀 Branch: {old_title[:18]}"
        cursor.execute(
            "INSERT INTO sessions (id, title, system_instruction, created_at) VALUES (?, ?, ?, ?)",
            (new_session_id, new_title, sys_prompt, datetime.now())
        )
        
        cursor.execute(
            "SELECT role, content, has_attachment FROM messages WHERE session_id = ? AND id <= ? ORDER BY id ASC",
            (current_session_id, message_id)
        )
        messages_to_copy = cursor.fetchall()
        
        for role, content, has_att in messages_to_copy:
            cursor.execute(
                "INSERT INTO messages (session_id, role, content, has_attachment, created_at) VALUES (?, ?, ?, ?, ?)",
                (new_session_id, role, content, has_att, datetime.now())
            )
            
        conn.commit()
    finally:
        conn.close()