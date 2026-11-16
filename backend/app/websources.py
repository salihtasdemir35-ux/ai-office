"""Kullanıcının belirlediği internet kaynakları (Bilgi Bankası > İnternet kaynakları).

- 'İçeriği bilgi bankasına ekle': sayfa (isteğe bağlı aynı sitedeki alt sayfalar) indirilir, metni çıkarılır ve
  bilgi bankasına eklenir → ajanlar internet yokken bile bu içerikte arama yapar.
- 'Ajanlar önce buraya baksın': web aramalarında bu siteler öncelikli aranır ve ajanlara listelenir.
"""
from __future__ import annotations

import json
import re
import time
from urllib.parse import urldefrag, urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

from . import memory
from .db import db

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AIOffice/1.1"}


def _domain(url: str) -> str:
    d = (urlparse(url).hostname or "").lower()
    return d[4:] if d.startswith("www.") else d


def _normalize(url: str) -> str:
    url = url.strip()
    if url and not url.startswith(("http://", "https://")):
        url = "https://" + url
    url = urldefrag(url)[0]
    host = urlparse(url).hostname or ""
    if not host or "." not in host or host in ("localhost",) or host.startswith(("127.", "192.168.", "10.")):
        raise ValueError(f"Geçersiz veya yerel adres: {url}")
    return url


async def fetch_page(client: httpx.AsyncClient, url: str) -> tuple[str, str, list[str]]:
    r = await client.get(url)
    r.raise_for_status()
    ctype = r.headers.get("content-type", "")
    if "pdf" in ctype or url.lower().endswith(".pdf"):
        import pymupdf
        with pymupdf.open(stream=r.content, filetype="pdf") as doc:
            text = "\n".join(p.get_text() for p in doc)
        return url.rsplit("/", 1)[-1], text, []
    soup = BeautifulSoup(r.text, "html.parser")
    title = soup.title.get_text(strip=True) if soup.title else url
    links = []
    for a in soup.find_all("a", href=True):
        u = urldefrag(urljoin(str(r.url), a["href"]))[0]
        if u.startswith("http") and _domain(u) == _domain(url) and not re.search(r"\.(jpg|png|gif|zip|exe|mp4|mp3|css|js)$", u, re.I):
            links.append(u)
    for t in soup(["script", "style", "nav", "footer", "header", "aside", "form", "noscript"]):
        t.decompose()
    text = re.sub(r"\n{3,}", "\n\n", soup.get_text("\n", strip=True))
    return title, text, list(dict.fromkeys(links))


def list_sources() -> list[dict]:
    rows = db.query("SELECT * FROM kb_sources ORDER BY priority DESC, added DESC")
    for r in rows:
        r["pages"] = json.loads(r.get("pages") or "[]")
    return rows


def priority_sources() -> list[dict]:
    return db.query("SELECT url, title, domain FROM kb_sources WHERE priority=1 ORDER BY added")


async def index_source(sid: int) -> dict:
    src = db.one("SELECT * FROM kb_sources WHERE id=?", (sid,))
    if not src:
        raise ValueError("Kaynak bulunamadı")
    old_pages = json.loads(src.get("pages") or "[]")
    pages, errors, queue, seen = [], [], [src["url"]], set()
    async with httpx.AsyncClient(timeout=25, headers=UA, follow_redirects=True) as c:
        while queue and len(pages) < max(1, src["max_pages"] or 1):
            url = queue.pop(0)
            if url in seen:
                continue
            seen.add(url)
            try:
                title, text, links = await fetch_page(c, url)
            except Exception as e:  # noqa
                errors.append(f"{url}: {type(e).__name__}")
                continue
            if len(text.strip()) < 50:
                continue
            memory.kb_add_text(url, f"🌐 {title}", f"Kaynak: {url}\n{text}")
            pages.append(url)
            queue += [u for u in links if u not in seen]
    for u in old_pages:  # artık bulunmayan eski sayfaları kaldır
        if u not in pages:
            d = db.one("SELECT id FROM kb_docs WHERE path=?", (u,))
            if d:
                memory.kb_delete(d["id"])
    status = f"{len(pages)} sayfa eklendi" + (f", {len(errors)} hata" if errors else "")
    if not pages and errors:
        status = "Erişilemedi: " + errors[0]
    db.execute("UPDATE kb_sources SET pages=?, status=?, last_fetched=? WHERE id=?",
               (json.dumps(pages), status, time.time(), sid))
    return {"id": sid, "pages": len(pages), "errors": errors, "status": status}


def add_sources(text: str, title: str = "", priority: bool = True, index: bool = True, max_pages: int = 1) -> list[int]:
    """Tek adres veya her satırda bir adres. Satırda 'ad | adres' biçimi de kabul edilir."""
    ids = []
    for line in [l.strip() for l in text.splitlines() if l.strip()]:
        name = title
        if "|" in line:
            name, line = [x.strip() for x in line.split("|", 1)]
        url = _normalize(line)
        existing = db.one("SELECT id FROM kb_sources WHERE url=?", (url,))
        if existing:
            db.execute("UPDATE kb_sources SET priority=?, indexed=?, max_pages=?, title=COALESCE(NULLIF(?,''),title) WHERE id=?",
                       (int(priority), int(index), max_pages, name, existing["id"]))
            ids.append(existing["id"])
            continue
        ids.append(db.execute(
            "INSERT INTO kb_sources(url,title,domain,priority,indexed,max_pages,status,added) VALUES(?,?,?,?,?,?,?,?)",
            (url, name or _domain(url), _domain(url), int(priority), int(index), max(1, min(30, max_pages)),
             "bekliyor" if index else "sadece öncelikli kaynak", time.time())))
    return ids


def update_source(sid: int, **fields) -> None:
    allowed = {k: v for k, v in fields.items() if k in ("title", "priority", "indexed", "max_pages")}
    if allowed:
        db.execute(f"UPDATE kb_sources SET {', '.join(k + '=?' for k in allowed)} WHERE id=?", (*allowed.values(), sid))


def delete_source(sid: int) -> None:
    src = db.one("SELECT * FROM kb_sources WHERE id=?", (sid,))
    if not src:
        return
    for u in json.loads(src.get("pages") or "[]"):
        d = db.one("SELECT id FROM kb_docs WHERE path=?", (u,))
        if d:
            memory.kb_delete(d["id"])
    db.execute("DELETE FROM kb_sources WHERE id=?", (sid,))


def prompt_block() -> str:
    """Ajan talimatına eklenen öncelikli kaynak listesi."""
    srcs = priority_sources()
    if not srcs:
        return ""
    lines = "\n".join(f"- {s['title']}: {s['url']}" for s in srcs[:15])
    return ("\nKULLANICININ ÖNCELİKLİ İNTERNET KAYNAKLARI (araştırmaya önce bunlardan başla; web_search bunları "
            "otomatik önce arar, kb_search ile indirilmiş içeriklerinde internetsiz arama yapabilirsin):\n" + lines)
