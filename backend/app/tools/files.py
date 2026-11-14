"""Dosya sistemi araçları (yalnızca izinli klasörlerde)."""
from __future__ import annotations

import shutil
import time
from collections import Counter
from pathlib import Path

from ..paths import DIRS
from ..security import request_approval, resolve_path, unique_path
from .base import ToolContext, tool

TEXT_EXT = {".txt", ".md", ".csv", ".json", ".py", ".js", ".html", ".htm", ".css", ".xml", ".log", ".ini", ".yaml", ".yml"}


def _human(n: int) -> str:
    for u in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.0f} {u}"
        n /= 1024
    return f"{n:.1f} TB"


@tool("list_files", "Klasör listeleme", 1, "Bir klasördeki dosya ve klasörleri listeler (alt klasörler dahil, en çok 200).",
      {"klasor": "klasör yolu (boşsa çalışma klasörü)", "alt_klasorler": "true/false"}, "Dosya inceliyor", "Dosya sistemi")
async def list_files(ctx: ToolContext, klasor: str = ".", alt_klasorler: str | bool = False) -> str:
    root = resolve_path(klasor, must_exist=True)
    rec = str(alt_klasorler).lower() in ("true", "1", "evet")
    items = list(root.rglob("*") if rec else root.iterdir())[:200]
    exts = Counter("(klasör)" if p.is_dir() else (p.suffix.lower() or "(uzantısız)") for p in items)
    lines = [f"Klasör: {root}  ({len(items)} öğe)", "Türlere göre: " + ", ".join(f"{k}: {v}" for k, v in exts.most_common())]
    for p in items:
        rel = p.relative_to(root)
        lines.append(f"[K] {rel}" if p.is_dir() else f"[D] {rel}  ({_human(p.stat().st_size)})")
    return "\n".join(lines)


@tool("read_file", "Dosya okuma", 1, "Metin dosyasını okur (txt, md, csv, json, kod).",
      {"yol": "dosya yolu"}, "Dosya inceliyor", "Dosya sistemi")
async def read_file(ctx: ToolContext, yol: str) -> str:
    p = resolve_path(yol, must_exist=True)
    if p.suffix.lower() not in TEXT_EXT:
        from .documents import extract_text
        return extract_text(p)[:8000]
    return p.read_text(encoding="utf-8", errors="ignore")[:8000]


@tool("search_files", "Dosya arama", 1, "Dosya adında (ve metin dosyalarının içeriğinde) arama yapar.",
      {"aranan": "aranacak kelime", "klasor": "klasör yolu (boşsa çalışma klasörü)", "uzanti": "ör. .pdf (isteğe bağlı)"},
      "Dosya inceliyor", "Dosya sistemi")
async def search_files(ctx: ToolContext, aranan: str, klasor: str = ".", uzanti: str = "") -> str:
    root = resolve_path(klasor, must_exist=True)
    q = aranan.lower()
    hits = []
    for p in root.rglob("*"):
        if not p.is_file() or (uzanti and p.suffix.lower() != uzanti.lower()):
            continue
        if q in p.name.lower():
            hits.append(f"[ad] {p.relative_to(root)}")
        elif p.suffix.lower() in TEXT_EXT and p.stat().st_size < 2_000_000:
            try:
                if q in p.read_text(encoding="utf-8", errors="ignore").lower():
                    hits.append(f"[içerik] {p.relative_to(root)}")
            except Exception:
                pass
        if len(hits) >= 100:
            break
    return f"{len(hits)} sonuç:\n" + "\n".join(hits) if hits else "Sonuç bulunamadı."


def _out_path(ctx: ToolContext, name: str, default_ext: str) -> Path:
    name = (name or f"cikti{default_ext}").replace("\\", "/").split("/")[-1]
    if not Path(name).suffix:
        name += default_ext
    base = Path(ctx.output_dir) if ctx.output_dir else resolve_path(".")
    base = resolve_path(str(base))
    base.mkdir(parents=True, exist_ok=True)
    return unique_path(base / name)


@tool("write_text", "Metin dosyası yazma", 2, "Yeni bir metin/markdown/kod dosyası oluşturur (üzerine yazmaz).",
      {"dosya_adi": "ör. notlar.md", "icerik": "dosya içeriği"}, "Yazıyor", "Belge üretimi")
async def write_text(ctx: ToolContext, dosya_adi: str, icerik: str) -> str:
    p = _out_path(ctx, dosya_adi, ".md")
    p.write_text(icerik, encoding="utf-8")
    ctx.created_files.append(str(p))
    return f"Dosya oluşturuldu: {p}"


@tool("create_folder", "Klasör oluşturma", 2, "İzinli alanda yeni klasör oluşturur.",
      {"yol": "klasör yolu"}, "Dosya inceliyor", "Dosya sistemi")
async def create_folder(ctx: ToolContext, yol: str) -> str:
    p = resolve_path(yol)
    p.mkdir(parents=True, exist_ok=True)
    return f"Klasör hazır: {p}"


@tool("copy_file", "Dosya kopyalama", 2, "Dosyayı başka bir izinli klasöre kopyalar (üzerine yazmaz).",
      {"kaynak": "dosya yolu", "hedef_klasor": "klasör yolu"}, "Dosya inceliyor", "Dosya sistemi")
async def copy_file(ctx: ToolContext, kaynak: str, hedef_klasor: str) -> str:
    src = resolve_path(kaynak, must_exist=True)
    dst_dir = resolve_path(hedef_klasor)
    dst_dir.mkdir(parents=True, exist_ok=True)
    dst = unique_path(dst_dir / src.name)
    shutil.copy2(src, dst)
    return f"Kopyalandı: {dst}"


@tool("move_file", "Dosya taşıma", 3, "Dosyayı taşır. KULLANICI ONAYI gerekir.",
      {"kaynak": "dosya yolu", "hedef_klasor": "klasör yolu"}, "Dosya inceliyor", "Dosya sistemi", needs_approval=True)
async def move_file(ctx: ToolContext, kaynak: str, hedef_klasor: str) -> str:
    src = resolve_path(kaynak, must_exist=True)
    dst_dir = resolve_path(hedef_klasor)
    if not await request_approval(ctx.agent_id, "Dosya taşıma", f"{src} → {dst_dir}", ctx.task_id):
        return "Kullanıcı taşıma işlemini onaylamadı."
    dst_dir.mkdir(parents=True, exist_ok=True)
    dst = unique_path(dst_dir / src.name)
    shutil.move(str(src), str(dst))
    return f"Taşındı: {dst}"


@tool("rename_file", "Yeniden adlandırma", 3, "Dosyayı yeniden adlandırır. KULLANICI ONAYI gerekir.",
      {"yol": "dosya yolu", "yeni_ad": "yeni dosya adı"}, "Dosya inceliyor", "Dosya sistemi", needs_approval=True)
async def rename_file(ctx: ToolContext, yol: str, yeni_ad: str) -> str:
    src = resolve_path(yol, must_exist=True)
    dst = unique_path(src.with_name(Path(yeni_ad).name))
    if not await request_approval(ctx.agent_id, "Yeniden adlandırma", f"{src.name} → {dst.name}", ctx.task_id):
        return "Kullanıcı yeniden adlandırmayı onaylamadı."
    src.rename(dst)
    return f"Yeni ad: {dst}"


@tool("delete_file", "Dosya silme", 3, "Dosyayı AI OFFICE çöp kutusuna taşır (kalıcı silmez). KULLANICI ONAYI gerekir.",
      {"yol": "dosya yolu"}, "Dosya inceliyor", "Dosya sistemi", needs_approval=True)
async def delete_file(ctx: ToolContext, yol: str) -> str:
    src = resolve_path(yol, must_exist=True)
    if not await request_approval(ctx.agent_id, "Dosya silme", str(src), ctx.task_id):
        return "Kullanıcı silme işlemini onaylamadı."
    trash = DIRS["cache"] / "trash" / time.strftime("%Y%m%d_%H%M%S")
    trash.mkdir(parents=True, exist_ok=True)
    shutil.move(str(src), str(trash / src.name))
    return f"Çöp kutusuna taşındı: {trash / src.name}"
