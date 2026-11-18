"""Aşama 3–7 testleri: araçlar, anlamsal arama, senkronizasyon, kasa, güvenlik, görev kuyruğu."""
from __future__ import annotations

import asyncio
import io
import json
import sqlite3
import time
import zipfile
from pathlib import Path

import pytest

from test_core import TMP, _wait, client  # noqa: F401  (ortam + fixture)

from app import backup, memory, sync, vault  # noqa: E402
from app.config import update_settings  # noqa: E402
from app.db import db  # noqa: E402
from app.orchestrator import _agent_tools, run_agent_step  # noqa: E402
from app.paths import ROOT, workspace  # noqa: E402
from app.security import pending, resolve_approval  # noqa: E402
from app.tools import TOOLS, ToolContext  # noqa: E402


def run(coro):
    return asyncio.get_event_loop_policy().new_event_loop().run_until_complete(coro)


def ctx(agent="veri_analisti"):
    return ToolContext(agent_id=agent, task_id="t", output_dir=str(workspace() / "test_out"))


# ------------------------------------------------------------------ Aşama 4
def test_ocr_reads_text():
    from PIL import Image, ImageDraw, ImageFont
    font = None
    for f in ("C:/Windows/Fonts/arial.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "/usr/share/fonts/dejavu/DejaVuSans.ttf"):
        if Path(f).exists():
            font = ImageFont.truetype(f, 48)
    img = Image.new("RGB", (700, 140), "white")
    ImageDraw.Draw(img).text((20, 40), "AI OFFICE 2026", fill="black", font=font)
    p = workspace() / "ocr_test.png"
    img.save(p)
    out = run(TOOLS["ocr"].func(ctx(), yol="ocr_test.png"))
    assert "OFFICE" in out.upper() and "2026" in out
    info = run(TOOLS["analyze_image"].func(ctx(), yol="ocr_test.png"))
    assert "700x140" in info and "Baskın renkler" in info


def test_data_analysis_chart_and_docx_image():
    (workspace() / "satis.csv").write_text("ay;tutar\nOcak;10\nŞubat;25\nMart;17\n", encoding="utf-8")
    out = run(TOOLS["analyze_data"].func(ctx(), yol="satis.csv"))
    assert "3 satır × 2 sütun" in out and "tutar" in out
    c = ctx()
    out = run(TOOLS["make_chart"].func(c, yol="satis.csv", x="ay", y="tutar", tur="bar", baslik="Satış"))
    png = Path(c.created_files[0])
    assert png.exists() and png.read_bytes()[:4] == b"\x89PNG"
    rel = png.relative_to(workspace())
    run(TOOLS["write_docx"].func(c, dosya_adi="grafikli.docx", baslik="Rapor", icerik=f"# Satışlar\n![grafik]({rel})\nMetin"))
    import docx
    d = docx.Document(c.created_files[-1])
    assert len(d.inline_shapes) == 1


def test_translate_uses_local_model(client):
    assert run(TOOLS["translate"].func(ctx(), metin="Merhaba dünya", hedef_dil="İngilizce")) == "Hello world"


def test_code_exec_disabled_then_approved(client):
    update_settings(code_exec_enabled=False)
    assert "kapalı" in run(TOOLS["run_python"].func(ctx("yazilim_gelistirici"), kod="print(1)"))
    update_settings(code_exec_enabled=True)

    async def go():
        async def approver():
            for _ in range(50):
                if pending:
                    resolve_approval(next(iter(pending)), True)
                    return
                await asyncio.sleep(0.05)
        asyncio.create_task(approver())
        return await TOOLS["run_python"].func(ctx("yazilim_gelistirici"), kod="print(sum(range(10)))")
    assert "45" in run(go())
    update_settings(code_exec_enabled=False)


def test_email_draft_without_smtp():
    c = ctx("eposta_uzmani")
    out = run(TOOLS["send_email"].func(c, alici="a@b.com", konu="Rapor", icerik="Ekte rapor"))
    assert "Taslak kaydedildi" in out and Path(c.created_files[0]).suffix == ".eml"


def test_browser_tool_reports_missing_install():
    out = run(TOOLS["browser_open"].func(ctx("internet_arastirmaci"), url="https://example.org"))
    assert "kurulu değil" in out or "example" in out.lower()


# ------------------------------------------------------------------ Aşama 5
def test_semantic_search(client):
    (workspace() / "savunma.md").write_text("Bu belge füze savunma sistemleri ve radar hakkındadır.", encoding="utf-8")
    (workspace() / "mutfak.md").write_text("Bu belge yemek tarifleri ve mutfak hakkındadır.", encoding="utf-8")
    client.post("/api/kb/add", json={"path": "savunma.md"})
    client.post("/api/kb/add", json={"path": "mutfak.md"})
    r = client.post("/api/embeddings/index").json()
    assert r["indexed"] >= 2
    hits = client.get("/api/kb/search?q=roket").json()["hits"]  # 'roket' belgede geçmiyor → sadece anlamsal bulunur
    assert hits and hits[0]["title"] == "savunma.md" and hits[0]["method"] in ("anlamsal", "hibrit")


# ------------------------------------------------------------------ Aşama 6
def test_sync_compare_and_apply(client, tmp_path):
    memory.add("kullanici", "Raporlar Times New Roman ile yazılsın")
    row = db.one("SELECT * FROM memory ORDER BY id DESC LIMIT 1")
    other = tmp_path / "other"
    (other / "database").mkdir(parents=True)
    (other / "agent_profiles").mkdir()
    db.checkpoint()
    import shutil
    shutil.copy(ROOT / "database" / "ai_office.db", other / "database" / "ai_office.db")
    con = sqlite3.connect(other / "database" / "ai_office.db")
    con.execute("UPDATE memory SET content=?, updated=? WHERE uid=?", ("Raporlar Calibri ile yazılsın", time.time() + 100, row["uid"]))
    con.execute("INSERT INTO memory(layer,content,source,confidence,created_by,shared,created,updated,uid) VALUES('ofis','Diğer bilgisayardan yeni bilgi','x',0.5,'ceo',1,?,?,?)",
                (time.time(), time.time(), "uid-yeni-123"))
    con.commit(); con.close()
    (other / "agent_profiles" / "ozel_diger.json").write_text(json.dumps({"id": "ozel_diger", "name": "D", "title": "Diğer", "tools": []}), encoding="utf-8")
    r = client.post("/api/sync/compare", json={"path": str(other)}).json()
    assert r["new_counts"]["memory"] == 1 and r["new_counts"]["agents"] == 1
    conf = [c for c in r["conflicts"] if c["key"] == f"memory:{row['uid']}"]
    assert conf and conf[0]["newer"] == "theirs"
    a = client.post("/api/sync/apply", json={"session": r["session"], "decisions": {conf[0]["key"]: "both"}}).json()
    assert a["imported"] == 2 and a["both"] == 1
    contents = [m["content"] for m in db.query("SELECT content FROM memory")]
    assert "Raporlar Times New Roman ile yazılsın" in contents and "Raporlar Calibri ile yazılsın" in contents
    assert (ROOT / "agent_profiles" / "ozel_diger.json").exists()


def test_vault_lock_unlock():
    n_before = db.one("SELECT COUNT(*) c FROM memory")["c"]
    r = vault.lock("gizliparola")
    assert vault.is_locked() and r["files"] > 0
    assert not (ROOT / "database" / "ai_office.db").exists()
    assert b"Times New Roman" not in (ROOT / "VAULT.aioffice").read_bytes()
    with pytest.raises(ValueError):
        vault.unlock("yanlis")
    vault.unlock("gizliparola")
    assert not vault.is_locked() and db.one("SELECT COUNT(*) c FROM memory")["c"] == n_before


# ------------------------------------------------------------------ Aşama 7: güvenlik
def test_permission_levels_enforced():
    qc = {"id": "x", "tools": ["read_file", "write_docx", "move_file"], "permission": 1}
    assert _agent_tools(qc) == ["read_file"]


def test_internet_kill_switch():
    update_settings(internet_enabled=False)
    try:
        assert "web_search" not in _agent_tools({"tools": ["web_search"], "permission": 3})
        with pytest.raises(Exception):
            run(TOOLS["web_search"].func(ctx(), sorgu="x"))
    finally:
        update_settings(internet_enabled=True)


def test_move_requires_approval_and_rejection_blocks():
    (workspace() / "tasinacak.txt").write_text("x", encoding="utf-8")

    async def go():
        async def rejecter():
            for _ in range(50):
                if pending:
                    resolve_approval(next(iter(pending)), False)
                    return
                await asyncio.sleep(0.05)
        asyncio.create_task(rejecter())
        return await TOOLS["move_file"].func(ctx("operasyon"), kaynak="tasinacak.txt", hedef_klasor="arsiv")
    assert "onaylamadı" in run(go())
    assert (workspace() / "tasinacak.txt").exists()


def test_zip_slip_restore_blocked():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("../../kotu.txt", "hack")
        z.writestr("config/zararsiz.txt", "ok")
    (ROOT / "backups" / "AI_OFFICE_YEDEK_kotu.zip").write_bytes(buf.getvalue())
    backup.restore_backup("AI_OFFICE_YEDEK_kotu.zip")
    assert not (ROOT.parent.parent / "kotu.txt").exists() and (ROOT / "config" / "zararsiz.txt").exists()


def test_untrusted_content_is_wrapped(client):
    """Prompt injection koruması: araç sonuçları 'güvenilmeyen veri' etiketiyle modele gider."""
    from test_core import CALLS
    joined = json.dumps(CALLS[-200:], ensure_ascii=False)
    assert "güvenilmeyen veri" in joined and "<veri>" in joined


def test_task_queue_limits_parallel(client):
    update_settings(max_parallel_tasks=1)
    ids = []
    for _ in range(2):
        r = client.post("/api/command", json={"text": "Klasörü incele ve rapor yaz"}).json()
        ids.append(r["task"]["id"])
        _wait(client, ids[-1], ("onay_bekliyor",))
    for i in ids:
        client.post(f"/api/tasks/{i}/approve")
    seen_queue = False
    for _ in range(60):
        st = [client.get(f"/api/tasks/{i}").json()["task"]["status"] for i in ids]
        seen_queue |= "sirada" in st
        if all(s == "tamamlandi" for s in st):
            break
        time.sleep(0.2)
    assert seen_queue and all(s == "tamamlandi" for s in st)


def test_gpu_and_resources(client):
    r = client.get("/api/system/resources").json()
    assert "gpu" in r["resources"] and r["embedder"]["status"] == "hazır"
