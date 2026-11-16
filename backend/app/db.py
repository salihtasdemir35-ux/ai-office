"""SQLite veritabanı: görevler, mesajlar, hafıza (FTS5), bilgi bankası, işlem geçmişi."""
from __future__ import annotations

import json
import sqlite3
import threading
import time
from typing import Any

from .paths import DIRS

DB_PATH = DIRS["database"] / "ai_office.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS tasks(
  id TEXT PRIMARY KEY, title TEXT, command TEXT, status TEXT, progress REAL DEFAULT 0,
  plan TEXT, result TEXT, files TEXT DEFAULT '[]', errors TEXT DEFAULT '[]',
  lead_agent TEXT, agents TEXT DEFAULT '[]', project_dir TEXT, direct INTEGER DEFAULT 0,
  created REAL, started REAL, finished REAL);
CREATE TABLE IF NOT EXISTS messages(
  id INTEGER PRIMARY KEY AUTOINCREMENT, task_id TEXT, sender TEXT, receiver TEXT,
  kind TEXT, content TEXT, ts REAL);
CREATE INDEX IF NOT EXISTS ix_msg_task ON messages(task_id);
CREATE INDEX IF NOT EXISTS ix_msg_sender ON messages(sender);
CREATE TABLE IF NOT EXISTS memory(
  id INTEGER PRIMARY KEY AUTOINCREMENT, layer TEXT, owner TEXT, project TEXT, content TEXT,
  source TEXT, confidence REAL DEFAULT 0.5, created_by TEXT, shared INTEGER DEFAULT 0,
  created REAL, updated REAL);
CREATE VIRTUAL TABLE IF NOT EXISTS memory_fts USING fts5(content, content='memory', content_rowid='id', tokenize='unicode61 remove_diacritics 2');
CREATE TRIGGER IF NOT EXISTS memory_ai AFTER INSERT ON memory BEGIN
  INSERT INTO memory_fts(rowid, content) VALUES (new.id, new.content); END;
CREATE TRIGGER IF NOT EXISTS memory_ad AFTER DELETE ON memory BEGIN
  INSERT INTO memory_fts(memory_fts, rowid, content) VALUES('delete', old.id, old.content); END;
CREATE TRIGGER IF NOT EXISTS memory_au AFTER UPDATE ON memory BEGIN
  INSERT INTO memory_fts(memory_fts, rowid, content) VALUES('delete', old.id, old.content);
  INSERT INTO memory_fts(rowid, content) VALUES (new.id, new.content); END;
CREATE TABLE IF NOT EXISTS kb_docs(
  id INTEGER PRIMARY KEY AUTOINCREMENT, path TEXT UNIQUE, title TEXT, mtime REAL, chunks INTEGER, added REAL);
CREATE VIRTUAL TABLE IF NOT EXISTS kb_fts USING fts5(content, doc_id UNINDEXED, chunk_no UNINDEXED, tokenize='unicode61 remove_diacritics 2');
CREATE TABLE IF NOT EXISTS kb_sources(
  id INTEGER PRIMARY KEY AUTOINCREMENT, url TEXT UNIQUE, title TEXT, domain TEXT, priority INTEGER DEFAULT 1,
  indexed INTEGER DEFAULT 1, max_pages INTEGER DEFAULT 1, pages TEXT DEFAULT '[]', status TEXT, last_fetched REAL, added REAL);
CREATE TABLE IF NOT EXISTS kb_vec(chunk_id INTEGER PRIMARY KEY, doc_id INTEGER, vec BLOB);
CREATE TABLE IF NOT EXISTS mem_vec(mem_id INTEGER PRIMARY KEY, vec BLOB);
CREATE TABLE IF NOT EXISTS audit(
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL, agent TEXT, action TEXT, target TEXT,
  result TEXT, task_id TEXT);
"""


class DB:
    def __init__(self) -> None:
        self.lock = threading.RLock()
        self.conn: sqlite3.Connection | None = None

    def open(self) -> None:
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        # journal_mode=DELETE: USB/exFAT üzerinde WAL'dan daha güvenli
        self.conn = sqlite3.connect(DB_PATH, check_same_thread=False, isolation_level=None)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=DELETE")
        self.conn.execute("PRAGMA synchronous=FULL")
        self.conn.executescript(SCHEMA)
        self._migrate()

    def _migrate(self) -> None:
        """Eski veritabanlarına yeni sütunları ekler (USB'deki eski sürüm verisi korunur)."""
        import uuid
        cols = {r[1] for r in self.conn.execute("PRAGMA table_info(memory)")}
        if "uid" not in cols:
            self.conn.execute("ALTER TABLE memory ADD COLUMN uid TEXT")
        for (mid,) in self.conn.execute("SELECT id FROM memory WHERE uid IS NULL").fetchall():
            self.conn.execute("UPDATE memory SET uid=? WHERE id=?", (uuid.uuid4().hex, mid))
        tcols = {r[1] for r in self.conn.execute("PRAGMA table_info(tasks)")}
        if "updated" not in tcols:
            self.conn.execute("ALTER TABLE tasks ADD COLUMN updated REAL")

    def close(self) -> None:
        with self.lock:
            if self.conn:
                self.conn.commit()
                self.conn.close()
                self.conn = None

    def execute(self, sql: str, params: tuple | list = ()) -> int:
        with self.lock:
            assert self.conn, "Veritabanı açık değil"
            cur = self.conn.execute(sql, params)
            return cur.lastrowid

    def query(self, sql: str, params: tuple | list = ()) -> list[dict]:
        with self.lock:
            assert self.conn, "Veritabanı açık değil"
            return [dict(r) for r in self.conn.execute(sql, params).fetchall()]

    def one(self, sql: str, params: tuple | list = ()) -> dict | None:
        rows = self.query(sql, params)
        return rows[0] if rows else None

    # ---------- yardımcılar ----------
    def audit(self, agent: str, action: str, target: str, result: str, task_id: str | None = None) -> None:
        # Hassas içerik yazılmaz: sadece hedef özeti (ilk 200 karakter) tutulur
        self.execute("INSERT INTO audit(ts,agent,action,target,result,task_id) VALUES(?,?,?,?,?,?)",
                     (time.time(), agent, action, (target or "")[:200], (result or "")[:200], task_id))

    def save_task(self, t: dict) -> None:
        t["updated"] = time.time()
        cols = ["id", "title", "command", "status", "progress", "plan", "result", "files", "errors",
                "lead_agent", "agents", "project_dir", "direct", "created", "started", "finished", "updated"]
        vals = []
        for c in cols:
            v = t.get(c)
            if c in ("plan", "files", "errors", "agents") and not isinstance(v, str):
                v = json.dumps(v if v is not None else ([] if c != "plan" else None), ensure_ascii=False)
            vals.append(v)
        self.execute(f"INSERT OR REPLACE INTO tasks({','.join(cols)}) VALUES({','.join('?'*len(cols))})", vals)

    def load_task(self, task_id: str) -> dict | None:
        t = self.one("SELECT * FROM tasks WHERE id=?", (task_id,))
        if t:
            for c in ("plan", "files", "errors", "agents"):
                try:
                    t[c] = json.loads(t[c]) if t[c] else ([] if c != "plan" else None)
                except Exception:
                    pass
        return t

    def checkpoint(self) -> None:
        with self.lock:
            if self.conn:
                self.conn.commit()


db = DB()


def fts_query(text: str) -> str:
    """Serbest metni güvenli bir FTS5 sorgusuna çevirir (OR ile)."""
    import re
    words = [w for w in re.findall(r"\w{3,}", text.lower())][:12]
    return " OR ".join(f'"{w}"' for w in words) if words else '""'


def as_json(v: Any) -> str:
    return json.dumps(v, ensure_ascii=False)
