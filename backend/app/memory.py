"""Hafıza katmanları: kullanici, ajan, ofis (ortak), proje. + Bilgi bankası (anahtar kelime / FTS5).

Her kayıtta kaynak, tarih, güven düzeyi ve oluşturan ajan tutulur.
Eski/çelişkili bilgi otomatik doğru kabul edilmez: ajanlara 'doğrulanmamış geçmiş bilgi' olarak verilir.
"""
from __future__ import annotations

import time
import uuid
from pathlib import Path

from .db import db, fts_query

LAYERS = {"kullanici": "Kullanıcı hafızası", "ajan": "Ajan hafızası", "ofis": "Ortak ofis hafızası",
          "proje": "Proje hafızası"}


def add(layer: str, content: str, owner: str = "", project: str = "", source: str = "",
        confidence: float = 0.5, created_by: str = "kullanici", shared: bool = False) -> int:
    now = time.time()
    return db.execute(
        "INSERT INTO memory(layer,owner,project,content,source,confidence,created_by,shared,created,updated,uid)"
        " VALUES(?,?,?,?,?,?,?,?,?,?,?)",
        (layer, owner, project, content.strip()[:4000], source, confidence, created_by, int(shared), now, now,
         uuid.uuid4().hex))


def update(mid: int, **fields) -> None:
    allowed = {k: v for k, v in fields.items() if k in ("content", "confidence", "shared", "layer", "owner", "source")}
    if not allowed:
        return
    sets = ", ".join(f"{k}=?" for k in allowed) + ", updated=?"
    db.execute(f"UPDATE memory SET {sets} WHERE id=?", (*allowed.values(), time.time(), mid))
    if "content" in allowed:
        db.execute("DELETE FROM mem_vec WHERE mem_id=?", (mid,))
        _invalidate()


def delete(mid: int) -> None:
    db.execute("DELETE FROM memory WHERE id=?", (mid,))
    db.execute("DELETE FROM mem_vec WHERE mem_id=?", (mid,))
    _invalidate()


def _invalidate() -> None:
    from .embeddings import embedder
    embedder.invalidate()


def search(q: str = "", layer: str = "", owner: str = "", limit: int = 100) -> list[dict]:
    where, params = [], []
    if layer:
        where.append("m.layer=?")
        params.append(layer)
    if owner:
        where.append("m.owner=?")
        params.append(owner)
    if q.strip():
        sql = ("SELECT m.* FROM memory_fts f JOIN memory m ON m.id=f.rowid WHERE memory_fts MATCH ? "
               + ("AND " + " AND ".join(where) if where else "") + " ORDER BY rank LIMIT ?")
        try:
            return db.query(sql, [fts_query(q), *params, limit])
        except Exception:
            pass
    sql = "SELECT m.* FROM memory m " + ("WHERE " + " AND ".join(where) if where else "") + " ORDER BY updated DESC LIMIT ?"
    return db.query(sql, [*params, limit])


def recall_for(agent_id: str, text: str, limit: int = 5) -> str:
    """Ajanın erişebileceği hafızadan ilgili kayıtlar: kendi ajan hafızası + ortak + kullanıcı tercihleri."""
    rows = []
    try:
        rows = db.query(
            "SELECT m.* FROM memory_fts f JOIN memory m ON m.id=f.rowid WHERE memory_fts MATCH ? AND "
            "(m.layer='kullanici' OR (m.layer='ajan' AND m.owner=?) OR m.layer='ofis' OR m.shared=1) "
            "ORDER BY rank LIMIT ?", (fts_query(text), agent_id, limit))
    except Exception:
        pass
    prefs = db.query("SELECT * FROM memory WHERE layer='kullanici' ORDER BY updated DESC LIMIT 5")
    seen, lines = set(), []
    for r in prefs + rows:
        if r["id"] in seen:
            continue
        seen.add(r["id"])
        date = time.strftime("%d.%m.%Y", time.localtime(r["updated"]))
        lines.append(f"- [{LAYERS.get(r['layer'], r['layer'])}, {date}, güven {r['confidence']:.1f}] {r['content'][:300]}")
    return "\n".join(lines)


def stats() -> dict:
    out = {k: 0 for k in LAYERS}
    for r in db.query("SELECT layer, COUNT(*) c FROM memory GROUP BY layer"):
        out[r["layer"]] = r["c"]
    kb = db.one("SELECT COUNT(*) c, COALESCE(SUM(chunks),0) ch FROM kb_docs") or {"c": 0, "ch": 0}
    out["kb_docs"], out["kb_chunks"] = kb["c"], kb["ch"]
    return out


# ------------------------------------------------------------------ bilgi bankası
KB_EXT = {".pdf", ".docx", ".xlsx", ".pptx", ".txt", ".md", ".html", ".htm"}


def _chunks(text: str, size: int = 1200, overlap: int = 150) -> list[str]:
    text = " ".join(text.split())
    out, i = [], 0
    while i < len(text):
        out.append(text[i:i + size])
        i += size - overlap
    return out


def kb_add(path: Path) -> dict:
    from .tools.documents import extract_text
    if path.suffix.lower() not in KB_EXT:
        raise ValueError(f"Desteklenmeyen tür: {path.suffix}")
    return kb_add_text(str(path), path.name, extract_text(path), path.stat().st_mtime)


def kb_add_text(key: str, title: str, text: str, mtime: float | None = None) -> dict:
    """Bilgi bankasına metin ekler (dosya yolu veya web adresi anahtar olarak kullanılır)."""
    chunks = _chunks(text) or [""]
    old = db.one("SELECT id FROM kb_docs WHERE path=?", (key,))
    if old:
        db.execute("DELETE FROM kb_vec WHERE doc_id=?", (old["id"],))
        db.execute("DELETE FROM kb_fts WHERE doc_id=?", (old["id"],))
        db.execute("DELETE FROM kb_docs WHERE id=?", (old["id"],))
    did = db.execute("INSERT INTO kb_docs(path,title,mtime,chunks,added) VALUES(?,?,?,?,?)",
                     (key, title[:200], mtime or time.time(), len(chunks), time.time()))
    for i, ch in enumerate(chunks):
        db.execute("INSERT INTO kb_fts(content, doc_id, chunk_no) VALUES(?,?,?)", (ch, did, i))
    _invalidate()
    return {"id": did, "title": title, "chunks": len(chunks)}


def kb_refresh() -> list[dict]:
    """Güncelleme kontrolü: değişen dosyaları yeniden indeksler."""
    changed = []
    for d in db.query("SELECT * FROM kb_docs WHERE path NOT LIKE 'http%'"):
        p = Path(d["path"])
        if p.exists() and p.stat().st_mtime > (d["mtime"] or 0) + 1:
            changed.append(kb_add(p))
    return changed


def kb_search(q: str, limit: int = 6) -> list[dict]:
    try:
        rows = db.query("SELECT k.rowid AS cid, k.content, k.chunk_no, d.title, d.path, d.id doc_id FROM kb_fts k "
                        "JOIN kb_docs d ON d.id=k.doc_id WHERE kb_fts MATCH ? ORDER BY rank LIMIT ?",
                        (fts_query(q), limit))
        for r in rows:
            r["method"] = "anahtar kelime"
        return rows
    except Exception:
        return []


async def kb_search_hybrid(q: str, limit: int = 6) -> list[dict]:
    """Hibrit arama: anahtar kelime (FTS5) + anlamsal vektör (bge-m3), RRF ile birleştirilir."""
    from .embeddings import embedder, rrf
    kw = kb_search(q, limit * 2)
    vec: list[tuple[int, float]] = []
    try:
        vec = await embedder.search("kb", q, limit * 2)
    except Exception:
        vec = []
    if not vec:
        return kw[:limit]
    vscore = dict(vec)
    order = rrf([r["cid"] for r in kw], [i for i, _ in vec])[:limit]
    by_id = {r["cid"]: r for r in kw}
    out = []
    for cid in order:
        r = by_id.get(cid)
        if not r:
            r = db.one("SELECT k.rowid AS cid, k.content, k.chunk_no, d.title, d.path, d.id doc_id FROM kb_fts k "
                       "JOIN kb_docs d ON d.id=k.doc_id WHERE k.rowid=?", (cid,))
            if not r:
                continue
        r["method"] = ("hibrit" if cid in by_id and cid in vscore else "anlamsal" if cid in vscore else "anahtar kelime")
        r["score"] = round(vscore.get(cid, 0.0), 3)
        out.append(r)
    return out


async def recall(agent_id: str, text: str, limit: int = 5) -> str:
    """recall_for + anlamsal eşleşmeler (embedding hazırsa)."""
    base = recall_for(agent_id, text, limit)
    from .embeddings import embedder
    try:
        vec = await embedder.search("mem", text, limit * 2)
    except Exception:
        vec = []
    extra = []
    for mid, score in vec:
        if score < 0.45:
            continue
        r = db.one("SELECT * FROM memory WHERE id=? AND (layer='kullanici' OR (layer='ajan' AND owner=?) "
                   "OR layer='ofis' OR shared=1)", (mid, agent_id))
        if r and r["content"][:300] not in base:
            date = time.strftime("%d.%m.%Y", time.localtime(r["updated"]))
            extra.append(f"- [{LAYERS.get(r['layer'], r['layer'])}, {date}, güven {r['confidence']:.1f}, anlamsal] {r['content'][:300]}")
        if len(extra) >= limit:
            break
    return "\n".join([x for x in [base] + extra if x])


def kb_delete(doc_id: int) -> None:
    db.execute("DELETE FROM kb_vec WHERE doc_id=?", (doc_id,))
    _invalidate()
    db.execute("DELETE FROM kb_fts WHERE doc_id=?", (doc_id,))
    db.execute("DELETE FROM kb_docs WHERE id=?", (doc_id,))
