import os
import mysql.connector
from mysql.connector import pooling
from dotenv import load_dotenv

ROOT = os.path.abspath(os.path.dirname(__file__))
load_dotenv(os.path.join(ROOT, ".env"))

def _config():
    required = ["DB_HOST", "DB_USER", "DB_NAME"]
    missing = [key for key in required if not os.getenv(key)]
    if missing:
        raise RuntimeError(
            "Missing database settings in .env: " + ", ".join(missing) +
            ". Copy .env.example to .env and configure it."
        )
    return {
        "host": os.getenv("DB_HOST", "127.0.0.1"),
        "port": int(os.getenv("DB_PORT", "3306")),
        "user": os.getenv("DB_USER"),
        "password": os.getenv("DB_PASSWORD", ""),
        "database": os.getenv("DB_NAME", "dfms_db"),
        "autocommit": False,
        "connection_timeout": 8,
    }

_pool = None

def get_pool():
    global _pool
    if _pool is None:
        _pool = pooling.MySQLConnectionPool(pool_name="dfms_pool", pool_size=5, **_config())
    return _pool

def get_connection():
    return get_pool().get_connection()

def fetch_all(sql, params=()):
    conn = get_connection()
    cur = conn.cursor(dictionary=True)
    try:
        cur.execute(sql, params)
        return cur.fetchall()
    finally:
        cur.close()
        conn.close()

def fetch_one(sql, params=()):
    rows = fetch_all(sql, params)
    return rows[0] if rows else None

def execute(sql, params=(), commit=True):
    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.execute(sql, params)
        if commit:
            conn.commit()
        return cur.lastrowid, cur.rowcount
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()
        conn.close()

def transaction(callback):
    """Run callback(connection) atomically; rollback on failure."""
    conn = get_connection()
    try:
        result = callback(conn)
        conn.commit()
        return result
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()