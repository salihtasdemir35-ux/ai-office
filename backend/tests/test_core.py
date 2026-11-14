"""AI OFFICE çekirdek testleri.

Orkestratör uçtan uca testi için TEST AMAÇLI sahte bir OpenAI uyumlu sunucu kullanılır (yalnızca testte;
uygulama arayüzünde sahte yanıt yoktur). Gerçek model testi: arayüzde Kurulum > Sistem testi.
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import threading
import time
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[2]
TMP = Path(tempfile.mkdtemp(prefix="aioffice_test_"))
shutil.copytree(SRC / "frontend", TMP / "frontend")
os.environ["AI_OFFICE_ROOT"] = str(TMP)
sys.path.insert(0, str(SRC / "backend"))

import uvicorn  # noqa: E402
from fastapi import FastAPI, Request  # noqa: E402

# ------------------------------------------------------------------ sahte yerel LLM (yalnızca test)
fake = FastAPI()
CALLS: list[dict] = []


@fake.get("/v1/models")
async def _models():
    return {"data": [{"id": "test"}]}


@fake.post("/v1/chat/completions")
async def _chat(req: Request):
    body = await req.json()
    CALLS.append(body)
    sys_msg = body["messages"][0]["content"] if body["messages"][0]["role"] == "system" else ""
    last = body["messages"][-1]["content"]
    if "profesyonel bir çevirmensin" in sys_msg:
        return {"choices": [{"message": {"content": "Hello world"}}]}
    if "iş planı" in sys_msg:
        out = {"ozet": "Dosyalar incelenecek ve Word raporu hazırlanacak.", "adimlar": [
            {"ajan": "veri_analisti", "baslik": "Dosyaları incele", "talimat": "Çalışma klasörünü listele ve sınıflandır.", "cikti": "metin"},
            {"ajan": "word_uzmani", "baslik": "Rapor yaz", "talimat": "Bulgulardan Word raporu hazırla.", "cikti": "docx"}]}
    elif "ÇALIŞMA PROTOKOLÜ" in sys_msg:
        if "Veri Analisti" in sys_msg and not last.startswith("ARAÇ SONUCU"):
            out = {"mesaj": "Klasörü tarıyorum.", "eylem": "list_files", "parametreler": {"klasor": "."}}
        elif "Veri Analisti" in sys_msg:
            out = {"mesaj": "Sınıflandırdım.", "eylem": "bitir", "sonuc": "# Bulgular\n- 1 metin dosyası bulundu: ornek.txt"}
        elif "Word Uzmanı" in sys_msg and not last.startswith(("ARAÇ SONUCU", "YANIT")):
            out = {"mesaj": "Analiste soruyorum.", "eylem": "soru", "parametreler": {"ajan": "veri_analisti", "soru": "Kaç dosya var?"}}
        else:
            out = {"mesaj": "Raporu bitirdim.", "eylem": "bitir", "sonuc": "# Rapor\nŞğıİöç Türkçe içerik.\n- Madde 1\nKaynak: https://example.org/kaynak"}
    else:
        return {"choices": [{"message": {"content": "Hazırım. Ekip görevi başarıyla tamamladı."}}], "usage": {"completion_tokens": 8}}
    return {"choices": [{"message": {"content": json.dumps(out, ensure_ascii=False)}}], "usage": {"completion_tokens": 20}}


SYN = {"roket": "füze", "fuze": "füze", "missile": "füze", "uçak": "uçak", "aircraft": "uçak"}


@fake.post("/v1/embeddings")
async def _emb(req: Request):
    """Test amaçlı deterministik 'anlamsal' vektör: eş anlamlı kelimeler aynı boyuta düşer."""
    import hashlib
    import re as _re
    body = await req.json()
    data = []
    for i, text in enumerate(body["input"]):
        v = [0.0] * 64
        for w in _re.findall(r"\w+", text.lower()):
            w = SYN.get(w, w)
            v[int(hashlib.md5(w.encode()).hexdigest(), 16) % 64] += 1.0
        data.append({"index": i, "embedding": v})
    return {"data": data}


def _free_port() -> int:
    import socket
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


PORT = int(os.environ.get("AI_OFFICE_TEST_PORT") or _free_port())
os.environ["AI_OFFICE_TEST_PORT"] = str(PORT)  # modül ikinci kez yüklenirse aynı sunucuyu kullan


def _serve():
    uvicorn.run(fake, host="127.0.0.1", port=PORT, log_level="error")


def _port_open() -> bool:
    import socket
    try:
        with socket.create_connection(("127.0.0.1", PORT), timeout=0.5):
            return True
    except OSError:
        return False


if not _port_open():
    threading.Thread(target=_serve, daemon=True).start()
    for _ in range(50):
        if _port_open():
            break
        time.sleep(0.1)
os.environ["AI_OFFICE_LLM_URL"] = f"http://127.0.0.1:{PORT}"
os.environ["AI_OFFICE_EMBED_URL"] = f"http://127.0.0.1:{PORT}"

from fastapi.testclient import TestClient  # noqa: E402

from app import backup, model_manager as mm  # noqa: E402
from app.main import app  # noqa: E402
from app.paths import ROOT, workspace  # noqa: E402
from app.security import SecurityError, resolve_path  # noqa: E402


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def test_paths_are_dynamic():
    assert ROOT == TMP.resolve()
    assert str(workspace()).startswith(str(TMP.resolve()))


def test_recommend_8gb_amd():
    hw = {"ram_total_gb": 7.9, "gpu_usable": False, "vram_gb": 0.5, "cores_physical": 4, "disk_free_gb": 50,
          "gpu_best": None}
    rec = mm.recommend(hw)
    assert rec["model_id"] == "qwen2.5-3b" and rec["ngl"] == 0 and not rec["gpu_mode"]


def test_recommend_tiers():
    gpu = {"vendor": "AMD", "vram_gb": 8, "name": "RX 6600"}
    assert mm.recommend({"ram_total_gb": 16, "gpu_usable": True, "vram_gb": 8, "gpu_best": gpu, "disk_free_gb": 100})["model_id"] == "qwen2.5-7b"
    assert mm.recommend({"ram_total_gb": 64, "gpu_usable": True, "vram_gb": 12, "gpu_best": gpu, "disk_free_gb": 100})["model_id"] == "qwen2.5-14b"
    assert mm.recommend({"ram_total_gb": 4, "gpu_usable": False, "vram_gb": 0, "gpu_best": None, "disk_free_gb": 100})["model_id"] == "qwen2.5-1.5b"
    assert mm.recommend({"ram_total_gb": 32, "gpu_usable": False, "vram_gb": 0, "gpu_best": None, "disk_free_gb": 2.5})["model_id"] == "qwen2.5-1.5b"


def test_security_blocks_outside():
    with pytest.raises(SecurityError):
        resolve_path("/etc/passwd")
    with pytest.raises(SecurityError):
        resolve_path("../../database/ai_office.db")
    assert resolve_path("alt/dosya.txt").is_relative_to(workspace())


def test_status_and_agents(client):
    r = client.get("/api/status").json()
    assert r["ok"] and r["portable"] is False  # test kökünde PORTABLE_MODE.json yok
    a = client.get("/api/agents").json()
    assert len([x for x in a["agents"] if x["builtin"]]) == 26
    r = client.post("/api/agents/team", json={"ids": ["veri_analisti", "word_uzmani", "kalite_kontrol"]}).json()
    assert r["hired"][0] == "ceo"


def test_hardware(client):
    r = client.get("/api/hardware").json()
    assert r["hardware"]["ram_total_gb"] > 0 and r["recommendation"]["model_id"]


def test_custom_agent(client):
    r = client.post("/api/agents/custom", json={"name": "Kemal", "title": "Savunma Analisti", "tools": ["web_search", "yok_boyle"], "permission": 5}).json()
    assert r["agent"]["id"] == "ozel_savunma_analisti" and r["agent"]["tools"] == ["web_search"] and r["agent"]["permission"] == 3
    assert (TMP / "agent_profiles" / "ozel_savunma_analisti.json").exists()


def _wait(client, tid, statuses, timeout=30):
    end = time.time() + timeout
    while time.time() < end:
        t = client.get(f"/api/tasks/{tid}").json()["task"]
        if t["status"] in statuses:
            return t
        time.sleep(0.3)
    raise AssertionError(f"Görev durumu: {t['status']}")


def test_full_multi_agent_flow(client):
    (workspace() / "ornek.txt").write_text("hava savunma yapay sinir ağları", encoding="utf-8")
    r = client.post("/api/command", json={"text": "Klasörümü analiz et ve Word raporu hazırla"}).json()
    tid = r["task"]["id"]
    t = _wait(client, tid, ("onay_bekliyor", "hata"))
    assert t["status"] == "onay_bekliyor", t["errors"]
    assert [s["ajan"] for s in t["plan"]["adimlar"]] == ["veri_analisti", "word_uzmani"]
    client.post(f"/api/tasks/{tid}/approve")
    t = _wait(client, tid, ("tamamlandi", "hata"))
    assert t["status"] == "tamamlandi", t["errors"]
    docx = [f for f in t["files"] if f.endswith(".docx")]
    assert docx and Path(docx[0]).exists()
    import docx as d
    text = "\n".join(p.text for p in d.Document(docx[0]).paragraphs)
    assert "Şğıİöç" in text and "example.org" in text
    msgs = client.get(f"/api/tasks/{tid}").json()["messages"]
    kinds = {m["kind"] for m in msgs}
    assert {"komut", "plan", "toplanti", "atama", "soru", "yanit", "kontrol", "sonuc"} <= kinds
    assert any(m["sender"] == "word_uzmani" and m["receiver"] == "veri_analisti" for m in msgs)
    audit = client.get("/api/audit").json()["items"]
    assert any(a["action"] == "list_files" and a["agent"] == "veri_analisti" for a in audit)
    mem = client.get("/api/memory").json()
    assert mem["stats"]["ajan"] >= 2 and mem["stats"]["proje"] >= 1
    assert (TMP / "projects" / f"{tid}.json").exists()


def test_direct_agent_and_chat(client):
    r = client.post("/api/command", json={"text": "Excel tablosu: ad;puan", "agent_id": "word_uzmani"}).json()
    t = _wait(client, r["task"]["id"], ("tamamlandi", "hata"))
    assert t["status"] == "tamamlandi"
    r = client.post("/api/agents/veri_analisti/chat", json={"message": "Merhaba"}).json()
    assert "Hazırım" in r["answer"]


def test_memory_and_kb(client):
    mid = client.post("/api/memory", json={"content": "Raporlarda APA formatı kullan"}).json()["id"]
    assert client.get("/api/memory?q=APA").json()["items"][0]["id"] == mid
    client.put(f"/api/memory/{mid}", json={"content": "Raporlarda IEEE formatı kullan"})
    assert client.get("/api/memory?q=IEEE").json()["items"]
    client.delete(f"/api/memory/{mid}")
    (workspace() / "bilgi.md").write_text("# Patriot\nPatriot hava savunma sistemi radar kullanır.", encoding="utf-8")
    r = client.post("/api/kb/add", json={"path": "bilgi.md"}).json()
    assert r["added"][0]["chunks"] >= 1
    assert client.get("/api/kb/search?q=radar").json()["hits"]


def test_system_test_endpoint(client):
    r = client.post("/api/setup/system-test").json()
    names = {x["name"]: x["ok"] for x in r["results"]}
    assert names["Belge üretimi (Word/Excel/PowerPoint/PDF)"] and names["Güvenlik: izinsiz klasör engeli"]
    assert names["Yerel AI motoru"] and names["Model yanıt testi"]


def test_backup_encrypted_roundtrip(client):
    p = backup.create_backup(password="gizli123")
    assert p.suffix == ".aioffice" and not p.read_bytes()[9:].startswith(b"PK")
    with pytest.raises(ValueError):
        backup.restore_backup(p.name, "yanlis")
    r = client.post("/api/backups/restore", json={"name": p.name, "password": "gizli123"}).json()
    assert r["restored_files"] > 0


def test_cancel_and_resume(client):
    r = client.post("/api/command", json={"text": "Klasörü incele ve rapor yaz"}).json()
    tid = r["task"]["id"]
    _wait(client, tid, ("onay_bekliyor",))
    client.post(f"/api/tasks/{tid}/cancel")
    t = _wait(client, tid, ("iptal",))
    client.post(f"/api/tasks/{tid}/resume")
    t = _wait(client, tid, ("tamamlandi", "hata"))
    assert t["status"] == "tamamlandi"
