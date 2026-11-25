"""Local database (SQLite) — no internet or cloud service needed."""
import json
import sqlite3
import threading
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
DATA_DIR.mkdir(exist_ok=True)
DB_PATH = DATA_DIR / "finai_bench.db"
_lock = threading.Lock()

SCHEMA = """
CREATE TABLE IF NOT EXISTS companies (
    id INTEGER PRIMARY KEY, name TEXT NOT NULL, tax_id TEXT, created TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS documents (
    id INTEGER PRIMARY KEY, company_id INTEGER REFERENCES companies(id) ON DELETE CASCADE,
    filename TEXT, kind TEXT, pages INTEGER, has_text INTEGER,
    ground_truth TEXT,       -- JSON {field: {"end": .., "start": ..}}
    accepted_values TEXT,    -- JSON {field: value} — what the dashboard uses
    accepted_run INTEGER,
    created TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS runs (
    id INTEGER PRIMARY KEY, document_id INTEGER REFERENCES documents(id) ON DELETE CASCADE,
    model TEXT, runtime TEXT, pipeline TEXT, device TEXT, params TEXT,
    raw_output TEXT, extracted TEXT, metrics TEXT,
    total_time REAL, load_time REAL, tokens_generated INTEGER, tokens_per_sec REAL, memory_mb REAL,
    json_valid INTEGER, error TEXT, repetition INTEGER DEFAULT 1, job_id TEXT,
    created TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS transactions (
    id INTEGER PRIMARY KEY, company_id INTEGER REFERENCES companies(id) ON DELETE CASCADE,
    date TEXT NOT NULL, type TEXT NOT NULL CHECK (type IN ('income','expense')),
    category TEXT NOT NULL, amount REAL NOT NULL CHECK (amount > 0), description TEXT,
    created TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT);
"""

JSON_COLS = {"ground_truth", "accepted_values", "params", "extracted", "metrics"}


def conn():
    c = sqlite3.connect(DB_PATH, check_same_thread=False)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA foreign_keys = ON")
    return c


def init():
    with conn() as c:
        c.executescript(SCHEMA)


def _row(r):
    if r is None:
        return None
    d = dict(r)
    for k in JSON_COLS & d.keys():
        if d[k]:
            try:
                d[k] = json.loads(d[k])
            except ValueError:
                pass
    return d


def q(sql, args=()):
    with conn() as c:
        return [_row(r) for r in c.execute(sql, args).fetchall()]


def q1(sql, args=()):
    r = q(sql, args)
    return r[0] if r else None


def ex(sql, args=()):
    args = tuple(json.dumps(a, ensure_ascii=False) if isinstance(a, (dict, list)) else a for a in args)
    with _lock, conn() as c:
        cur = c.execute(sql, args)
        return cur.lastrowid


DEFAULT_SETTINGS = {
    "ollama_url": "http://localhost:11434",
    "openai_url": "http://127.0.0.1:8090/v1",   # llama.cpp llama-server / LM Studio / mlx_vlm.server
    "dpi": "150",
    "max_side_px": "1024",
    "timeout_s": "900",
    "num_ctx": "8192",
    "device": "laptop",
    "thinking": "no",               # for "thinking" models (e.g. qwen3-vl): yes / no
    "embedding_threshold": "0.85",  # minimum cosine similarity for OCR + embeddings
    "prompt_example": "no",         # "yes" = the prompt includes an example answer (one-shot)
    "constrained_output": "no",     # "yes" = amounts may only contain digits (grammar-constrained decoding)
}


def get_settings():
    s = dict(DEFAULT_SETTINGS)
    for r in q("SELECT key, value FROM settings"):
        s[r["key"]] = r["value"]
    return s


def save_settings(d: dict):
    for k, v in d.items():
        if k in DEFAULT_SETTINGS:
            ex("INSERT INTO settings(key, value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
               (k, str(v)))
