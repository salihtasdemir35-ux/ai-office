"""Aşama 6: Bilgisayarlar / kopyalar arası senkronizasyon.

Başka bir AI OFFICE klasörü (ör. diğer USB veya bilgisayardaki kopya) ya da bir yedek dosyası ile karşılaştırır.
Çakışmalarda OTOMATİK ÜZERİNE YAZILMAZ: değişiklikler ve tarihler gösterilir, kullanıcı 'benimki / onunki / ikisini koru' seçer.
"""
from __future__ import annotations

import io
import json
import shutil
import sqlite3
import time
import uuid
import zipfile
from pathlib import Path

from . import backup
from .db import db
from .paths import DIRS

SESSIONS: dict[str, dict] = {}


def _prepare_source(path: str, password: str = "") -> Path:
    p = Path(path).expanduser()
    if not p.exists():
        raise FileNotFoundError(f"Bulunamadı: {p}")
    if p.is_dir():
        if not (p / "database" / "ai_office.db").exists():
            raise ValueError("Bu klasör bir AI OFFICE klasörü değil (database/ai_office.db yok).")
        return p
    data = p.read_bytes()
    if p.suffix == ".aioffice":
        if not password:
            raise ValueError("Şifreli dosya için parola gerekli.")
        data = backup.decrypt_bytes(data, password)
    tmp = DIRS["cache"] / f"sync_{uuid.uuid4().hex[:6]}"
    tmp.mkdir(parents=True)
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        for info in z.infolist():
            target = (tmp / info.filename).resolve()
            if tmp.resolve() in target.parents:
                target.parent.mkdir(parents=True, exist_ok=True)
                with z.open(info) as s, open(target, "wb") as d:
                    shutil.copyfileobj(s, d)
    if not (tmp / "database" / "ai_office.db").exists():
        raise ValueError("Yedekte veritabanı yok.")
    return tmp


def _rows(conn: sqlite3.Connection, sql: str, params: tuple = ()) -> list[dict]:
    conn.row_factory = sqlite3.Row
    try:
        return [dict(r) for r in conn.execute(sql, params).fetchall()]
    except sqlite3.OperationalError:
        return []


def _date(ts) -> str:
    return time.strftime("%d.%m.%Y %H:%M", time.localtime(ts)) if ts else "—"


def compare(path: str, password: str = "") -> dict:
    src = _prepare_source(path, password)
    other = sqlite3.connect(f"file:{src / 'database' / 'ai_office.db'}?mode=ro", uri=True)
    new: dict[str, list] = {"memory": [], "tasks": [], "agents": []}
    conflicts: list[dict] = []
    # hafıza (uid ile)
    mine = {r["uid"]: r for r in db.query("SELECT * FROM memory WHERE uid IS NOT NULL")}
    for r in _rows(other, "SELECT * FROM memory"):
        uid = r.get("uid")
        if not uid:
            continue
        m = mine.get(uid)
        if not m:
            new["memory"].append(r)
        elif m["content"] != r["content"]:
            conflicts.append({"key": f"memory:{uid}", "kind": "Hafıza", "title": r["content"][:60],
                              "mine": {"text": m["content"], "date": _date(m["updated"])},
                              "theirs": {"text": r["content"], "date": _date(r["updated"])},
                              "newer": "theirs" if (r["updated"] or 0) > (m["updated"] or 0) else "mine", "_row": r})
    # görevler
    mine_t = {r["id"]: r for r in db.query("SELECT id, title, status, result, updated FROM tasks")}
    for r in _rows(other, "SELECT * FROM tasks"):
        m = mine_t.get(r["id"])
        if not m:
            r["_messages"] = _rows(other, "SELECT * FROM messages WHERE task_id=?", (r["id"],))
            new["tasks"].append(r)
        elif (m.get("updated") or 0) != (r.get("updated") or 0) and (m["status"] != r["status"] or m["result"] != r["result"]):
            r["_messages"] = _rows(other, "SELECT * FROM messages WHERE task_id=?", (r["id"],))
            conflicts.append({"key": f"task:{r['id']}", "kind": "Görev", "title": r["title"],
                              "mine": {"text": f"Durum: {m['status']}\n{(m['result'] or '')[:400]}", "date": _date(m.get("updated"))},
                              "theirs": {"text": f"Durum: {r['status']}\n{(r['result'] or '')[:400]}", "date": _date(r.get("updated"))},
                              "newer": "theirs" if (r.get("updated") or 0) > (m.get("updated") or 0) else "mine", "_row": r})
    other.close()
    # ajan profilleri
    for f in (src / "agent_profiles").glob("*.json"):
        mf = DIRS["agent_profiles"] / f.name
        if not mf.exists():
            new["agents"].append({"file": str(f), "name": f.stem})
        elif mf.read_text(encoding="utf-8") != f.read_text(encoding="utf-8"):
            conflicts.append({"key": f"agent:{f.name}", "kind": "Ajan profili", "title": f.stem,
                              "mine": {"text": mf.read_text(encoding="utf-8")[:500], "date": _date(mf.stat().st_mtime)},
                              "theirs": {"text": f.read_text(encoding="utf-8")[:500], "date": _date(f.stat().st_mtime)},
                              "newer": "theirs" if f.stat().st_mtime > mf.stat().st_mtime else "mine", "_file": str(f)})
    sid = uuid.uuid4().hex[:8]
    SESSIONS[sid] = {"src": str(src), "new": new, "conflicts": conflicts, "created": time.time()}
    return public(sid)


def public(sid: str) -> dict:
    s = SESSIONS[sid]
    return {"session": sid, "source": s["src"],
            "new_counts": {k: len(v) for k, v in s["new"].items()},
            "new_preview": {"memory": [r["content"][:80] for r in s["new"]["memory"][:10]],
                            "tasks": [r["title"] for r in s["new"]["tasks"][:10]],
                            "agents": [a["name"] for a in s["new"]["agents"]]},
            "conflicts": [{k: v for k, v in c.items() if not k.startswith("_")} for c in s["conflicts"]]}


def _insert_memory(r: dict, new_uid: bool = False) -> None:
    cols = ["layer", "owner", "project", "content", "source", "confidence", "created_by", "shared", "created", "updated", "uid"]
    vals = [r.get(c) for c in cols]
    if new_uid:
        vals[-1] = uuid.uuid4().hex
    db.execute(f"INSERT INTO memory({','.join(cols)}) VALUES({','.join('?' * len(cols))})", vals)


def _insert_task(r: dict, new_id: str | None = None) -> None:
    my_cols = {c["name"] for c in db.query("PRAGMA table_info(tasks)")}
    t = {k: v for k, v in r.items() if not k.startswith("_") and k in my_cols}
    if new_id:
        t["id"] = new_id
        t["title"] = (t.get("title") or "") + " (diğer kopya)"
    cols = [c for c in t]
    db.execute(f"INSERT OR REPLACE INTO tasks({','.join(cols)}) VALUES({','.join('?' * len(cols))})", [t[c] for c in cols])
    if True:
        db.execute("DELETE FROM messages WHERE task_id=?", (t["id"],))
        for m in r.get("_messages", []):
            db.execute("INSERT INTO messages(task_id,sender,receiver,kind,content,ts) VALUES(?,?,?,?,?,?)",
                       (t["id"], m["sender"], m["receiver"], m["kind"], m["content"], m["ts"]))


def apply(sid: str, decisions: dict[str, str], import_new: bool = True) -> dict:
    s = SESSIONS.get(sid)
    if not s:
        raise ValueError("Karşılaştırma oturumu bulunamadı; yeniden karşılaştırın.")
    safety = backup.create_backup()
    stats = {"imported": 0, "theirs": 0, "both": 0, "mine": 0}
    if import_new:
        for r in s["new"]["memory"]:
            _insert_memory(r)
            stats["imported"] += 1
        for r in s["new"]["tasks"]:
            _insert_task(r)
            stats["imported"] += 1
        for a in s["new"]["agents"]:
            shutil.copy2(a["file"], DIRS["agent_profiles"] / Path(a["file"]).name)
            stats["imported"] += 1
    for c in s["conflicts"]:
        choice = decisions.get(c["key"], "mine")  # karar verilmemişse mevcut veri korunur
        kind, key = c["key"].split(":", 1)
        if choice == "theirs":
            if kind == "memory":
                r = c["_row"]
                db.execute("UPDATE memory SET content=?, updated=?, confidence=?, source=? WHERE uid=?",
                           (r["content"], r["updated"], r["confidence"], r["source"], key))
                db.execute("DELETE FROM mem_vec WHERE mem_id=(SELECT id FROM memory WHERE uid=?)", (key,))
            elif kind == "task":
                _insert_task(c["_row"])
            else:
                shutil.copy2(c["_file"], DIRS["agent_profiles"] / key)
        elif choice == "both":
            if kind == "memory":
                _insert_memory(c["_row"], new_uid=True)
            elif kind == "task":
                _insert_task(c["_row"], new_id=key[:6] + uuid.uuid4().hex[:4])
            else:
                d = json.loads(Path(c["_file"]).read_text(encoding="utf-8"))
                d["id"] = d["id"] + "_kopya"
                d["title"] = d.get("title", "") + " (kopya)"
                (DIRS["agent_profiles"] / f"{d['id']}.json").write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")
        stats[choice if choice in stats else "mine"] += 1
    from .embeddings import embedder
    embedder.invalidate()
    SESSIONS.pop(sid, None)
    return {**stats, "safety_backup": safety.name}
