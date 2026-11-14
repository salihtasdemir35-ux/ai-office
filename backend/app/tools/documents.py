"""Gerçek belge üretimi ve okuma: Word (python-docx), Excel (openpyxl), PowerPoint (python-pptx), PDF (PyMuPDF)."""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

from ..security import resolve_path
from .base import ToolContext, tool
from .files import _out_path

URL_RE = re.compile(r"https?://[^\s)\]>\"']+")


# ------------------------------------------------------------------ okuma
def extract_text(p: Path) -> str:
    ext = p.suffix.lower()
    try:
        if ext == ".pdf":
            import pymupdf
            with pymupdf.open(p) as doc:
                return "\n".join(page.get_text() for page in doc)
        if ext == ".docx":
            import docx
            d = docx.Document(str(p))
            parts = [para.text for para in d.paragraphs]
            for t in d.tables:
                for row in t.rows:
                    parts.append(" | ".join(c.text for c in row.cells))
            return "\n".join(parts)
        if ext in (".xlsx", ".xlsm"):
            import openpyxl
            wb = openpyxl.load_workbook(p, read_only=True, data_only=True)
            out = []
            for ws in wb.worksheets:
                out.append(f"## Sayfa: {ws.title}")
                for i, row in enumerate(ws.iter_rows(values_only=True)):
                    if i > 300:
                        out.append("... (kısaltıldı)")
                        break
                    out.append(" | ".join("" if v is None else str(v) for v in row))
            return "\n".join(out)
        if ext == ".pptx":
            from pptx import Presentation
            prs = Presentation(str(p))
            out = []
            for i, s in enumerate(prs.slides, 1):
                out.append(f"## Slayt {i}")
                for sh in s.shapes:
                    if sh.has_text_frame:
                        out.append(sh.text_frame.text)
            return "\n".join(out)
        if ext in (".html", ".htm"):
            from bs4 import BeautifulSoup
            return BeautifulSoup(p.read_text(encoding="utf-8", errors="ignore"), "html.parser").get_text("\n")
        return p.read_text(encoding="utf-8", errors="ignore")
    except Exception as e:  # noqa
        return f"[Metin çıkarılamadı: {e}]"


@tool("read_document", "Belge okuma (PDF/Word/Excel/PowerPoint)", 1,
      "PDF, DOCX, XLSX, PPTX, TXT, MD veya HTML belgesinin metnini çıkarır.",
      {"yol": "belge yolu"}, "Dosya inceliyor", "Belge okuma")
async def read_document(ctx: ToolContext, yol: str) -> str:
    p = resolve_path(yol, must_exist=True)
    text = extract_text(p)
    return f"Belge: {p.name} ({len(text)} karakter)\n" + text[:7000]


# ------------------------------------------------------------------ yazma
def build_docx(path: Path, title: str, content: str, sources: list[str] | None = None) -> Path:
    import docx
    from docx.shared import Pt, RGBColor
    d = docx.Document()
    st = d.styles["Normal"]
    st.font.name = "Calibri"
    st.font.size = Pt(11)
    h = d.add_heading(title or "Rapor", level=0)
    for r in h.runs:
        r.font.color.rgb = RGBColor(0x0B, 0x1F, 0x3A)
    for line in content.splitlines():
        s = line.rstrip()
        if not s.strip():
            continue
        img = re.match(r"^!\[[^\]]*\]\((.+?)\)\s*$", s.strip())
        if img:
            try:
                from docx.shared import Inches
                ip = resolve_path(img.group(1), must_exist=True)
                d.add_picture(str(ip), width=Inches(6))
                continue
            except Exception:
                pass
        if s.startswith("### "):
            d.add_heading(s[4:], level=3)
        elif s.startswith("## "):
            d.add_heading(s[3:], level=2)
        elif s.startswith("# "):
            d.add_heading(s[2:], level=1)
        elif re.match(r"^\s*[-*•]\s+", s):
            d.add_paragraph(re.sub(r"^\s*[-*•]\s+", "", s).replace("**", ""), style="List Bullet")
        elif re.match(r"^\s*\d+[.)]\s+", s):
            d.add_paragraph(re.sub(r"^\s*\d+[.)]\s+", "", s).replace("**", ""), style="List Number")
        else:
            d.add_paragraph(s.replace("**", ""))
    srcs = list(dict.fromkeys((sources or []) + URL_RE.findall(content)))
    if srcs and "kaynakça" not in content.lower():
        d.add_heading("Kaynakça", level=1)
        for i, u in enumerate(srcs, 1):
            d.add_paragraph(f"[{i}] {u}")
    d.add_paragraph().add_run("Bu belge AI OFFICE yerel yapay zekâ ajanları tarafından hazırlanmıştır. "
                              "Bilgileri kullanmadan önce kaynaklardan doğrulayın.").italic = True
    d.save(str(path))
    return path


@tool("write_docx", "Word belgesi oluşturma", 2,
      "Gerçek bir .docx Word belgesi oluşturur. İçerikte '# Başlık', '## Alt başlık', '- madde' kullanabilirsin.",
      {"dosya_adi": "ör. rapor.docx", "baslik": "belge başlığı", "icerik": "belge metni (markdown benzeri)"},
      "Yazıyor", "Belge üretimi")
async def write_docx(ctx: ToolContext, dosya_adi: str, baslik: str = "Rapor", icerik: str = "") -> str:
    p = _out_path(ctx, dosya_adi, ".docx")
    build_docx(p, baslik, icerik, ctx.sources)
    ctx.created_files.append(str(p))
    return f"Word belgesi oluşturuldu: {p}"


def build_xlsx(path: Path, rows: list[list], sheet: str = "Veri") -> Path:
    import openpyxl
    from openpyxl.styles import Font, PatternFill
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = (sheet or "Veri")[:30]
    for r in rows:
        ws.append([_num(v) for v in r])
    if rows:
        for c in ws[1]:
            c.font = Font(bold=True, color="FFFFFF")
            c.fill = PatternFill("solid", fgColor="0B1F3A")
        for col in ws.columns:
            w = max(len(str(c.value or "")) for c in col)
            ws.column_dimensions[col[0].column_letter].width = min(60, max(10, w + 2))
    wb.save(str(path))
    return path


def _num(v):
    if isinstance(v, str):
        t = v.strip().replace(".", "").replace(",", ".") if re.fullmatch(r"-?\d{1,3}(\.\d{3})+(,\d+)?", v.strip()) else v.strip()
        try:
            return float(t) if "." in t else int(t)
        except ValueError:
            return v
    return v


def rows_from_text(text: str) -> list[list]:
    """Markdown tablo, CSV veya JSON metnini satırlara çevirir."""
    text = text.strip()
    try:
        data = json.loads(text)
        if isinstance(data, list) and data and isinstance(data[0], dict):
            keys = list(data[0].keys())
            return [keys] + [[d.get(k) for k in keys] for d in data]
        if isinstance(data, list):
            return [r if isinstance(r, list) else [r] for r in data]
    except Exception:
        pass
    rows = []
    for line in text.splitlines():
        s = line.strip()
        if not s or re.fullmatch(r"[|\-:\s]+", s):
            continue
        if "|" in s:
            rows.append([c.strip() for c in s.strip("|").split("|")])
        elif ";" in s:
            rows.append([c.strip() for c in s.split(";")])
        elif "," in s and s.count(",") >= 1:
            rows.append([c.strip() for c in s.split(",")])
        else:
            rows.append([s])
    return rows


@tool("write_xlsx", "Excel dosyası oluşturma", 2,
      "Gerçek bir .xlsx Excel dosyası oluşturur. 'veri' JSON listesi ([[...],[...]]) veya markdown tablo olabilir.",
      {"dosya_adi": "ör. tablo.xlsx", "veri": "ilk satır başlık olacak şekilde tablo", "sayfa": "sayfa adı"},
      "Yazıyor", "Belge üretimi")
async def write_xlsx(ctx: ToolContext, dosya_adi: str, veri, sayfa: str = "Veri") -> str:
    rows = veri if isinstance(veri, list) else rows_from_text(str(veri))
    rows = [r if isinstance(r, list) else [r] for r in rows]
    p = _out_path(ctx, dosya_adi, ".xlsx")
    build_xlsx(p, rows, sayfa)
    ctx.created_files.append(str(p))
    return f"Excel dosyası oluşturuldu: {p} ({len(rows)} satır)"


def slides_from_text(title: str, text: str) -> list[dict]:
    slides, cur = [], None
    for line in text.splitlines():
        s = line.strip()
        if not s:
            continue
        if s.startswith("#"):
            cur = {"baslik": s.lstrip("# ").strip(), "maddeler": []}
            slides.append(cur)
        else:
            if cur is None:
                cur = {"baslik": title, "maddeler": []}
                slides.append(cur)
            cur["maddeler"].append(re.sub(r"^[-*•\d.)\s]+", "", s).replace("**", ""))
    out = []
    for sl in slides:  # uzun slaytları böl
        items = sl["maddeler"] or [""]
        for i in range(0, len(items), 6):
            out.append({"baslik": sl["baslik"] + (" (devam)" if i else ""), "maddeler": items[i:i + 6]})
    return out[:30]


def build_pptx(path: Path, title: str, slides: list[dict]) -> Path:
    from pptx import Presentation
    from pptx.dml.color import RGBColor
    from pptx.util import Pt
    prs = Presentation()
    s0 = prs.slides.add_slide(prs.slide_layouts[0])
    s0.shapes.title.text = title or "Sunum"
    s0.placeholders[1].text = "AI OFFICE – Yerel yapay zekâ ajanları"
    for sl in slides:
        s = prs.slides.add_slide(prs.slide_layouts[1])
        s.shapes.title.text = str(sl.get("baslik", ""))[:120]
        s.shapes.title.text_frame.paragraphs[0].runs[0].font.color.rgb = RGBColor(0x0B, 0x1F, 0x3A)
        tf = s.placeholders[1].text_frame
        tf.clear()
        for i, m in enumerate(sl.get("maddeler", [])):
            p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
            p.text = str(m)[:300]
            p.font.size = Pt(18)
    prs.save(str(path))
    return path


@tool("write_pptx", "PowerPoint sunumu oluşturma", 2,
      "Gerçek bir .pptx sunumu oluşturur. 'slaytlar' = [{\"baslik\":\"...\",\"maddeler\":[\"...\"]}] veya '# Başlık' ve maddeler içeren metin.",
      {"dosya_adi": "ör. sunum.pptx", "baslik": "sunum başlığı", "slaytlar": "slayt listesi veya metin"},
      "Yazıyor", "Belge üretimi")
async def write_pptx(ctx: ToolContext, dosya_adi: str, baslik: str = "Sunum", slaytlar="") -> str:
    slides = slaytlar if isinstance(slaytlar, list) else slides_from_text(baslik, str(slaytlar))
    slides = [s if isinstance(s, dict) else {"baslik": str(s), "maddeler": []} for s in slides]
    p = _out_path(ctx, dosya_adi, ".pptx")
    build_pptx(p, baslik, slides)
    ctx.created_files.append(str(p))
    return f"PowerPoint sunumu oluşturuldu: {p} ({len(slides) + 1} slayt)"


def _font_file() -> str | None:
    cands = []
    windir = os.environ.get("WINDIR") or os.environ.get("SystemRoot")
    if windir:
        cands += [os.path.join(windir, "Fonts", f) for f in ("arial.ttf", "calibri.ttf", "segoeui.ttf")]
    cands += ["/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "/usr/share/fonts/dejavu/DejaVuSans.ttf",
              "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf"]
    return next((c for c in cands if os.path.exists(c)), None)


def build_pdf(path: Path, title: str, content: str) -> Path:
    """Türkçe karakterleri (ş, ğ, ı, İ) destekleyen PDF üretimi."""
    import pymupdf
    font = _font_file()
    doc = pymupdf.open()
    W, H, M = 595, 842, 50
    lines = [(title, 16)] + [("", 11)] + [(ln.replace("**", "").lstrip("#").strip() if ln.startswith("#") else ln, 13 if ln.startswith("#") else 11)
                                         for ln in content.splitlines()]
    page, y = None, H
    for text, size in lines:
        wrapped = _wrap(text, int((W - 2 * M) / (size * 0.5)))
        for w in wrapped or [""]:
            if y > H - M - size:
                page = doc.new_page(width=W, height=H)
                if font:
                    page.insert_font(fontname="tr", fontfile=font)
                y = M
            page.insert_text((M, y + size), w, fontsize=size, fontname="tr" if font else "helv")
            y += size * 1.45
    doc.save(str(path))
    doc.close()
    return path


def _wrap(text: str, width: int) -> list[str]:
    out, cur = [], ""
    for word in text.split(" "):
        if len(cur) + len(word) + 1 > width and cur:
            out.append(cur)
            cur = word
        else:
            cur = (cur + " " + word).strip()
    if cur:
        out.append(cur)
    return out


@tool("write_pdf", "PDF oluşturma", 2, "Gerçek bir PDF belgesi oluşturur (Türkçe karakter desteği).",
      {"dosya_adi": "ör. ozet.pdf", "baslik": "başlık", "icerik": "metin"}, "Yazıyor", "Belge üretimi")
async def write_pdf(ctx: ToolContext, dosya_adi: str, baslik: str = "Belge", icerik: str = "") -> str:
    p = _out_path(ctx, dosya_adi, ".pdf")
    build_pdf(p, baslik, icerik)
    ctx.created_files.append(str(p))
    return f"PDF oluşturuldu: {p}"
