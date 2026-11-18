"""Aşama 4 araçları: OCR, görüntü analizi, veri analizi, grafik, çeviri, dosya/PDF indirme,
tarayıcı otomasyonu (Playwright), Python kod çalıştırma (onaylı), e-posta (taslak + onaylı gönderim)."""
from __future__ import annotations

import asyncio
import os
import re
import smtplib
import subprocess
import sys
import time
from email.message import EmailMessage
from pathlib import Path
from urllib.parse import urlparse

import httpx

from ..config import get_settings
from ..paths import DIRS
from ..security import SecurityError, request_approval, resolve_path, unique_path
from .base import ToolContext, tool
from .files import _out_path
from .web import UA, _check

IMG_EXT = {".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff", ".webp"}
_ocr_engine = None


# ------------------------------------------------------------------ OCR (yerel, internetsiz)
def ocr_file(p: Path) -> str:
    """RapidOCR (ONNX, CPU, modeller paket içinde). PDF ise sayfaları görüntüye çevirip okur."""
    global _ocr_engine
    try:
        from rapidocr_onnxruntime import RapidOCR
    except ImportError:
        return "[OCR bileşeni kurulu değil: Araçlar > Eksik bileşenleri kur]"
    if _ocr_engine is None:
        _ocr_engine = RapidOCR()
    images: list = []
    if p.suffix.lower() == ".pdf":
        import pymupdf
        with pymupdf.open(p) as doc:
            for page in list(doc)[:15]:
                images.append(page.get_pixmap(dpi=200).tobytes("png"))
    else:
        images.append(str(p))
    out = []
    for i, img in enumerate(images, 1):
        res, _ = _ocr_engine(img)
        text = "\n".join(r[1] for r in (res or []))
        out.append(f"--- Sayfa {i} ---\n{text}" if len(images) > 1 else text)
    return "\n".join(out).strip() or "[Metin bulunamadı]"


@tool("ocr", "OCR (görüntüden metin)", 1, "Görüntü veya taranmış PDF'teki yazıları yerel OCR ile okur (internetsiz).",
      {"yol": "görüntü veya PDF yolu"}, "Dosya inceliyor", "Belge okuma")
async def ocr(ctx: ToolContext, yol: str) -> str:
    p = resolve_path(yol, must_exist=True)
    text = await asyncio.to_thread(ocr_file, p)
    return f"OCR sonucu ({p.name}):\n{text[:6000]}"


@tool("analyze_image", "Görüntü analizi", 1,
      "Görüntünün boyutunu, biçimini, EXIF bilgisini, baskın renklerini ve içindeki yazıları (OCR) çıkarır.",
      {"yol": "görüntü yolu"}, "Dosya inceliyor", "Belge okuma")
async def analyze_image(ctx: ToolContext, yol: str) -> str:
    from PIL import ExifTags, Image
    p = resolve_path(yol, must_exist=True)
    with Image.open(p) as im:
        info = [f"Dosya: {p.name}", f"Biçim: {im.format}", f"Boyut: {im.width}x{im.height} piksel", f"Renk modu: {im.mode}"]
        exif = {}
        try:
            for k, v in (im.getexif() or {}).items():
                name = ExifTags.TAGS.get(k, str(k))
                if name in ("Make", "Model", "DateTime", "Software", "Artist"):
                    exif[name] = str(v)
        except Exception:
            pass
        if exif:
            info.append("EXIF: " + ", ".join(f"{k}={v}" for k, v in exif.items()))
        small = im.convert("RGB").resize((64, 64))
        colors = sorted(small.getcolors(64 * 64), reverse=True)[:5]
        info.append("Baskın renkler: " + ", ".join("#%02x%02x%02x" % c[1] for c in colors))
    text = await asyncio.to_thread(ocr_file, p)
    info.append("Görüntüdeki yazılar (OCR):\n" + text[:3000])
    return "\n".join(info)


# ------------------------------------------------------------------ veri analizi
def _load_df(p: Path):
    import pandas as pd
    ext = p.suffix.lower()
    if ext in (".xlsx", ".xlsm", ".xls"):
        return pd.read_excel(p)
    if ext == ".json":
        return pd.read_json(p)
    for sep in (",", ";", "\t"):
        try:
            df = pd.read_csv(p, sep=sep, encoding="utf-8", engine="python")
            if df.shape[1] > 1:
                return df
        except Exception:
            continue
    return pd.read_csv(p, encoding="latin-1")


@tool("analyze_data", "Veri analizi", 1,
      "CSV/Excel/JSON tablosunu analiz eder: sütunlar, eksik değerler, istatistikler, en sık değerler.",
      {"yol": "veri dosyası yolu"}, "Dosya inceliyor", "Veri")
async def analyze_data(ctx: ToolContext, yol: str) -> str:
    p = resolve_path(yol, must_exist=True)
    df = await asyncio.to_thread(_load_df, p)
    lines = [f"Dosya: {p.name}  |  {df.shape[0]} satır × {df.shape[1]} sütun", "", "Sütunlar ve türleri:"]
    for c in df.columns:
        lines.append(f"- {c}: {df[c].dtype}, eksik={int(df[c].isna().sum())}, benzersiz={df[c].nunique()}")
    num = df.select_dtypes("number")
    if not num.empty:
        lines += ["", "Sayısal istatistikler:", num.describe().round(3).to_string()]
    for c in df.select_dtypes(exclude="number").columns[:5]:
        top = df[c].value_counts().head(5)
        lines.append(f"\nEn sık '{c}': " + ", ".join(f"{k} ({v})" for k, v in top.items()))
    lines += ["", "İlk 5 satır:", df.head().to_string()]
    return "\n".join(lines)[:7000]


@tool("make_chart", "Grafik oluşturma", 2,
      "Veri dosyasından grafik (PNG) üretir. tur: bar | line | pie | hist. Word raporuna '![grafik](dosya_yolu)' ile eklenebilir.",
      {"yol": "veri dosyası", "x": "x ekseni sütunu", "y": "y ekseni sütunu (hist/pie için tek sütun yeterli)",
       "tur": "bar|line|pie|hist", "baslik": "grafik başlığı"}, "Yazıyor", "Veri")
async def make_chart(ctx: ToolContext, yol: str, x: str = "", y: str = "", tur: str = "bar", baslik: str = "") -> str:
    p = resolve_path(yol, must_exist=True)
    df = await asyncio.to_thread(_load_df, p)
    safe = re.sub(r"[^\w]+", "_", baslik or p.stem)[:30]
    out = _out_path(ctx, f"grafik_{safe}.png", ".png")

    def draw():
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        fig, ax = plt.subplots(figsize=(9, 5), dpi=120)
        col = y or x or df.select_dtypes("number").columns[0]
        if tur == "hist":
            df[col].dropna().plot(kind="hist", ax=ax, bins=20, color="#14b8a6")
        elif tur == "pie":
            s = df.groupby(x)[y].sum() if x and y else df[col].value_counts()
            s.head(10).plot(kind="pie", ax=ax, autopct="%1.0f%%")
            ax.set_ylabel("")
        else:
            data = df.groupby(x)[y].sum() if x and y and tur == "bar" else (df.set_index(x)[y] if x and y else df[col])
            data.head(40).plot(kind="line" if tur == "line" else "bar", ax=ax, color="#0b1f3a")
        ax.set_title(baslik or col)
        fig.tight_layout()
        fig.savefig(out)
        plt.close(fig)
    await asyncio.to_thread(draw)
    ctx.created_files.append(str(out))
    return f"Grafik oluşturuldu: {out}"


# ------------------------------------------------------------------ çeviri (yerel model)
@tool("translate", "Çeviri", 1, "Metni yerel yapay zekâ modeliyle hedef dile çevirir (internet gerekmez).",
      {"metin": "çevrilecek metin", "hedef_dil": "ör. İngilizce, Türkçe, Almanca"}, "Yazıyor", "Dil")
async def translate(ctx: ToolContext, metin: str, hedef_dil: str = "İngilizce") -> str:
    from ..engine import engine
    return await engine.chat([
        {"role": "system", "content": f"Sen profesyonel bir çevirmensin. Verilen metni {hedef_dil} diline çevir. "
                                      "Sadece çeviriyi yaz, açıklama ekleme. Terimleri ve biçimi koru."},
        {"role": "user", "content": metin[:6000]}], max_tokens=1500, temperature=0.1)


# ------------------------------------------------------------------ indirme
@tool("download_file", "Dosya / PDF indirme", 2,
      "İnternetten PDF veya belge indirir ve görev klasörüne kaydeder (en fazla 50 MB).",
      {"url": "dosya adresi"}, "Araştırıyor", "İnternet", needs_internet=True)
async def download_file(ctx: ToolContext, url: str) -> str:
    _check()
    host = urlparse(url).hostname or ""
    if not url.startswith(("http://", "https://")) or host in ("localhost", "127.0.0.1"):
        return "Geçersiz adres."
    name = Path(urlparse(url).path).name or "indirilen"
    async with httpx.AsyncClient(timeout=60, headers=UA, follow_redirects=True) as c:
        async with c.stream("GET", url) as r:
            r.raise_for_status()
            ctype = r.headers.get("content-type", "")
            if "pdf" in ctype and not name.lower().endswith(".pdf"):
                name += ".pdf"
            if "text/html" in ctype:
                return "Bu adres bir web sayfası; metni için web_fetch kullanın."
            out = _out_path(ctx, name, ".bin")
            size = 0
            with open(out, "wb") as f:
                async for chunk in r.aiter_bytes(1 << 16):
                    size += len(chunk)
                    if size > 50 * 1024 * 1024:
                        f.close()
                        out.unlink(missing_ok=True)
                        return "Dosya 50 MB sınırını aşıyor; indirme durduruldu."
                    f.write(chunk)
    ctx.created_files.append(str(out))
    ctx.sources.append(url)
    return f"İndirildi: {out} ({size // 1024} KB). İçeriği read_document ile okuyabilirsin."


# ------------------------------------------------------------------ tarayıcı otomasyonu
def playwright_status() -> dict:
    try:
        import playwright  # noqa: F401
    except ImportError:
        return {"installed": False, "browser": False}
    bdir = DIRS["dependencies"] / "ms-playwright"
    return {"installed": True, "browser": bdir.exists() and any(bdir.glob("chromium*"))}


@tool("browser_open", "Tarayıcı otomasyonu", 1,
      "JavaScript gerektiren sayfaları gerçek (görünmez) Chromium tarayıcıyla açar; metni ve isteğe bağlı ekran görüntüsünü alır. "
      "İsterse sayfadaki bir alana yazı yazıp arama yapabilir.",
      {"url": "sayfa adresi", "ekran_goruntusu": "true/false", "arama_kutusu": "CSS seçici (isteğe bağlı)",
       "arama_metni": "kutuya yazılacak metin (isteğe bağlı)"}, "Araştırıyor", "İnternet", needs_internet=True)
async def browser_open(ctx: ToolContext, url: str, ekran_goruntusu="false", arama_kutusu: str = "", arama_metni: str = "") -> str:
    _check()
    st = playwright_status()
    if not st["installed"] or not st["browser"]:
        return "Tarayıcı otomasyonu kurulu değil. Araçlar ekranından 'Tarayıcı otomasyonunu kur' ile kurun; şimdilik web_fetch kullanın."
    os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(DIRS["dependencies"] / "ms-playwright")
    from playwright.async_api import async_playwright
    async with async_playwright() as p:
        b = await p.chromium.launch(headless=True)
        page = await b.new_page(user_agent=UA["User-Agent"])
        await page.goto(url, timeout=45000, wait_until="domcontentloaded")
        if arama_kutusu and arama_metni:
            await page.fill(arama_kutusu, arama_metni)
            await page.press(arama_kutusu, "Enter")
            await page.wait_for_load_state("domcontentloaded")
        await page.wait_for_timeout(1500)
        title = await page.title()
        text = await page.inner_text("body")
        shot = ""
        if str(ekran_goruntusu).lower() in ("true", "1", "evet"):
            out = _out_path(ctx, f"ekran_{int(time.time())}.png", ".png")
            await page.screenshot(path=str(out), full_page=True)
            ctx.created_files.append(str(out))
            shot = f"\nEkran görüntüsü: {out}"
        final = page.url
        await b.close()
    ctx.sources.append(final)
    return f"{title}\n{final}{shot}\n\n{re.sub(chr(10) + '{3,}', chr(10) * 2, text)[:6000]}"


# ------------------------------------------------------------------ kod çalıştırma (varsayılan KAPALI)
@tool("run_python", "Python kodu çalıştırma", 3,
      "Python kodunu görev klasöründe 60 sn sınırla çalıştırır. Ayarlardan açılmalı ve HER ÇALIŞTIRMA kullanıcı onayı ister.",
      {"kod": "Python kodu"}, "Yazıyor", "Kod", needs_approval=True)
async def run_python(ctx: ToolContext, kod: str) -> str:
    if not get_settings().get("code_exec_enabled", False):
        return "Kod çalıştırma Ayarlar > Güvenlik bölümünde kapalı."
    if not await request_approval(ctx.agent_id, "Python kodu çalıştırma", kod[:1500], ctx.task_id):
        return "Kullanıcı kod çalıştırmayı onaylamadı."
    cwd = Path(ctx.output_dir or resolve_path("."))
    cwd = resolve_path(str(cwd))
    cwd.mkdir(parents=True, exist_ok=True)
    script = unique_path(cwd / "_ajan_kodu.py")
    script.write_text(kod, encoding="utf-8")
    env = {"PATH": os.environ.get("PATH", ""), "SYSTEMROOT": os.environ.get("SYSTEMROOT", ""),
           "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1", "TEMP": str(DIRS["cache"]), "TMP": str(DIRS["cache"])}
    try:
        r = await asyncio.to_thread(subprocess.run, [sys.executable, "-I", str(script)], cwd=str(cwd), env=env,
                                    capture_output=True, text=True, timeout=60, encoding="utf-8", errors="ignore")
        out = f"Çıkış kodu: {r.returncode}\n{(r.stdout or '')[-4000:]}\n{('HATA: ' + r.stderr[-2000:]) if r.stderr else ''}"
    except subprocess.TimeoutExpired:
        out = "Zaman aşımı (60 sn) – kod durduruldu."
    finally:
        script.unlink(missing_ok=True)
    return out


# ------------------------------------------------------------------ e-posta
@tool("send_email", "E-posta (taslak / gönderim)", 3,
      "E-posta taslağını .eml dosyası olarak kaydeder. SMTP ayarlıysa ve kullanıcı ONAYLARSA gönderir.",
      {"alici": "e-posta adresi", "konu": "konu", "icerik": "metin", "ek": "eklenecek dosya yolu (isteğe bağlı)"},
      "Yazıyor", "İletişim", needs_approval=True)
async def send_email(ctx: ToolContext, alici: str, konu: str, icerik: str, ek: str = "") -> str:
    s = get_settings().get("smtp") or {}
    msg = EmailMessage()
    msg["To"], msg["Subject"] = alici, konu
    msg["From"] = s.get("from") or s.get("user") or "ai-office@localhost"
    msg.set_content(icerik)
    if ek:
        ap = resolve_path(ek, must_exist=True)
        msg.add_attachment(ap.read_bytes(), maintype="application", subtype="octet-stream", filename=ap.name)
    safe = re.sub(r"[^\w]+", "_", konu)[:30]
    draft = _out_path(ctx, f"eposta_{safe}.eml", ".eml")
    draft.write_bytes(bytes(msg))
    ctx.created_files.append(str(draft))
    if not s.get("host"):
        return f"Taslak kaydedildi: {draft}. (Göndermek için Ayarlar > E-posta (SMTP) bölümünü doldurun.)"
    if not await request_approval(ctx.agent_id, "E-posta gönderme (dışarıya veri gönderimi)",
                                  f"Alıcı: {alici}\nKonu: {konu}\nEk: {ek or 'yok'}\n\n{icerik[:500]}", ctx.task_id):
        return f"Kullanıcı gönderimi onaylamadı. Taslak: {draft}"

    def _send():
        with smtplib.SMTP(s["host"], int(s.get("port", 587)), timeout=30) as srv:
            srv.starttls()
            if s.get("user"):
                srv.login(s["user"], s.get("password", ""))
            srv.send_message(msg)
    try:
        await asyncio.to_thread(_send)
    except Exception as e:  # noqa
        raise SecurityError(f"E-posta gönderilemedi: {e}") from e
    return f"E-posta gönderildi: {alici}. Taslak kopyası: {draft}"
