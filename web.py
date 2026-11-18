"""İnternet araçları. Kayıt/API anahtarı gerektirmeyen kaynaklar: DuckDuckGo HTML arama + Wikipedia.

UYARI (kota): DuckDuckGo HTML uç noktasının resmi kotası yoktur; çok sık istekte geçici olarak
engelleyebilir. Bu durumda Wikipedia aramasına geçilir. Web içerikleri GÜVENİLMEYEN VERİ olarak işaretlenir.
"""
from __future__ import annotations

import re
from urllib.parse import parse_qs, unquote, urlparse

import httpx
from bs4 import BeautifulSoup

from ..config import get_settings
from ..security import SecurityError
from .base import ToolContext, tool

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AIOffice/0.2"}


def _check() -> None:
    if not get_settings().get("internet_enabled", True):
        raise SecurityError("İnternet erişimi kullanıcı tarafından kapatıldı.")


def _clean_ddg(href: str) -> str:
    if "duckduckgo.com/l/" in href:
        q = parse_qs(urlparse(href).query)
        if "uddg" in q:
            return unquote(q["uddg"][0])
    return href


async def ddg_search(query: str, n: int = 8) -> list[dict]:
    async with httpx.AsyncClient(timeout=15, headers=UA, follow_redirects=True) as c:
        r = await c.post("https://html.duckduckgo.com/html/", data={"q": query, "kl": "tr-tr"})
        r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")
    out = []
    for res in soup.select(".result"):
        a = res.select_one("a.result__a")
        if not a:
            continue
        sn = res.select_one(".result__snippet")
        out.append({"title": a.get_text(" ", strip=True), "url": _clean_ddg(a.get("href", "")),
                    "snippet": sn.get_text(" ", strip=True) if sn else ""})
        if len(out) >= n:
            break
    return out


async def wiki_search(query: str, n: int = 5, lang: str = "tr") -> list[dict]:
    async with httpx.AsyncClient(timeout=15, headers=UA) as c:
        r = await c.get(f"https://{lang}.wikipedia.org/w/api.php",
                        params={"action": "query", "list": "search", "srsearch": query, "format": "json", "srlimit": n})
        r.raise_for_status()
    out = []
    for it in r.json().get("query", {}).get("search", []):
        out.append({"title": it["title"], "url": f"https://{lang}.wikipedia.org/wiki/{it['title'].replace(' ', '_')}",
                    "snippet": re.sub("<[^>]+>", "", it.get("snippet", ""))})
    return out


@tool("web_search", "Web araması", 1, "İnternette arama yapar ve başlık, adres ve özet listesi döndürür.",
      {"sorgu": "arama ifadesi"}, "Araştırıyor", "İnternet", needs_internet=True)
async def web_search(ctx: ToolContext, sorgu: str) -> str:
    _check()
    results, note = [], ""
    # 1) Kullanıcının öncelikli kaynakları (Bilgi Bankası > İnternet kaynakları)
    from ..websources import priority_sources
    prio = []
    for src in priority_sources()[:3]:
        try:
            for r in await ddg_search(f"{sorgu} site:{src['domain']}", n=3):
                r["title"] = f"[Öncelikli kaynak: {src['title']}] {r['title']}"
                prio.append(r)
        except Exception:
            continue
    try:
        results = await ddg_search(sorgu)
    except Exception as e:  # noqa
        note = f"(DuckDuckGo yanıt vermedi: {type(e).__name__}; Wikipedia kullanıldı)\n"
    if not results:
        try:
            results = await wiki_search(sorgu)
        except Exception as e:  # noqa
            return f"Arama başarısız: {e}"
    seen = {r["url"] for r in prio}
    results = prio + [r for r in results if r["url"] not in seen]
    for r in results:
        ctx.sources.append(r["url"])
    lines = [f"{i}. {r['title']}\n   {r['url']}\n   {r['snippet'][:250]}" for i, r in enumerate(results, 1)]
    return note + "\n".join(lines) if lines else "Sonuç bulunamadı."


@tool("web_fetch", "Sayfa açma / metin çıkarma", 1, "Bir web sayfasını açar ve ana metnini çıkarır.",
      {"url": "sayfa adresi (http/https)"}, "Araştırıyor", "İnternet", needs_internet=True)
async def web_fetch(ctx: ToolContext, url: str) -> str:
    _check()
    if not url.startswith(("http://", "https://")):
        return "Geçersiz adres."
    host = urlparse(url).hostname or ""
    if host in ("localhost", "127.0.0.1") or host.startswith(("192.168.", "10.")):
        return "Yerel ağ adreslerine erişim engellendi."
    async with httpx.AsyncClient(timeout=20, headers=UA, follow_redirects=True) as c:
        r = await c.get(url)
    ctype = r.headers.get("content-type", "")
    if "pdf" in ctype:
        import pymupdf
        with pymupdf.open(stream=r.content, filetype="pdf") as doc:
            text = "\n".join(p.get_text() for p in doc)
    else:
        soup = BeautifulSoup(r.text, "html.parser")
        for t in soup(["script", "style", "nav", "footer", "header", "aside", "form"]):
            t.decompose()
        title = soup.title.get_text(strip=True) if soup.title else url
        text = title + "\n" + re.sub(r"\n{3,}", "\n\n", soup.get_text("\n", strip=True))
    ctx.sources.append(url)
    return text[:6000]
