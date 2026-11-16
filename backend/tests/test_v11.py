"""Sürüm 1.1: motor bulma, ajan adları/kişi sayısı, kullanıcı internet kaynakları."""
from __future__ import annotations

import asyncio
import io
import os
import zipfile

from test_core import _wait, client  # noqa: F401

from app import model_manager as mm  # noqa: E402
from app import websources  # noqa: E402
from app.agents import registry  # noqa: E402
from app.db import db  # noqa: E402
from app.paths import DIRS  # noqa: E402


def test_pick_asset_skips_release_without_windows_builds():
    releases = [
        {"tag_name": "v0.9", "assets": [{"name": "llama-v0.9-src.tar.gz"}]},           # sürüm numaralı, Windows yok
        {"tag_name": "b11500", "assets": [{"name": "llama-b11500-bin-ubuntu-x64.tar.gz"},
                                          {"name": "llama-b11500-bin-win-vulkan-x64.zip"},
                                          {"name": "llama-b11500-bin-win-cpu-x64.zip"}]},
    ]
    a, tag = mm.pick_asset(releases, "vulkan")
    assert tag == "b11500" and a["name"].endswith("win-vulkan-x64.zip")
    assert mm.pick_asset(releases, "cpu")[1] == "b11500"
    assert mm.pick_asset(releases[:1], "cpu") == (None, None)


def test_import_manually_downloaded_engine_zip():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("llama-server.exe" if os.name == "nt" else "llama-server", b"MZ fake")
        z.writestr("ggml.dll", b"x")
    (DIRS["cache"] / "llama-b11500-bin-win-cpu-x64.zip").write_bytes(buf.getvalue())
    found = mm.import_local_engines()
    assert "cpu" in found
    assert mm.find_server("cpu").name.startswith("llama-server")


def test_agent_headcount_and_names(client):
    r = client.post("/api/agents/internet_arastirmaci/count",
                    json={"count": 3, "names": ["Deniz", "", "Kemal Bey"]}).json()
    ids = sorted(m["id"] for m in r["members"])
    assert ids == ["internet_arastirmaci", "internet_arastirmaci__2", "internet_arastirmaci__3"]
    names = {m["id"]: m["name"] for m in r["members"]}
    assert names["internet_arastirmaci"] == "Deniz" and names["internet_arastirmaci__3"] == "Kemal Bey"
    assert names["internet_arastirmaci__2"] not in ("", "Deniz", "Kemal Bey")      # otomatik ad
    copy = registry.get("internet_arastirmaci__3")
    assert copy["title"] == "İnternet Araştırmacısı" and "web_search" in copy["tools"]
    assert copy["system_prompt"].startswith("Sen Kemal Bey.")
    # yeniden adlandırma ve CEO ekip listesi
    client.post("/api/agents/word_uzmani/rename", json={"name": "Raporcu Ayla"})
    assert registry.get("word_uzmani")["name"] == "Raporcu Ayla"
    from app.orchestrator import _team_text
    team = _team_text()
    assert "Kemal Bey (İnternet Araştırmacısı)" in team
    # azaltma kopyaları siler, CEO tek kalır
    client.post("/api/agents/internet_arastirmaci/count", json={"count": 1})
    assert registry.get("internet_arastirmaci__2") is None and registry.get("internet_arastirmaci")["hired"]
    client.post("/api/agents/ceo/count", json={"count": 4})
    assert [a["id"] for a in registry.hired() if a["id"].startswith("ceo")] == ["ceo"]
    client.post("/api/agents/word_uzmani/rename", json={"name": "Gizem Aydın"})


def test_user_web_sources(client, monkeypatch):
    async def fake_fetch(c, url):
        if url.endswith("/alt"):
            return "Alt sayfa", "Patriot füze savunma sistemi teknik ayrıntıları burada anlatılmaktadır.", []
        return "Ana sayfa", "SSB savunma sanayii haberleri ve proje duyuruları bu sayfadadır, güncel bilgiler.", [url + "/alt"]
    monkeypatch.setattr(websources, "fetch_page", fake_fetch)
    ids = websources.add_sources("SSB | https://www.ssb.gov.tr\nhttps://dergipark.org.tr", priority=True, index=True, max_pages=5)
    assert len(ids) == 2
    r = asyncio.get_event_loop_policy().new_event_loop().run_until_complete(websources.index_source(ids[0]))
    assert r["pages"] == 2
    hits = db.query("SELECT path FROM kb_docs WHERE path LIKE 'https://www.ssb.gov.tr%'")
    assert len(hits) == 2
    block = websources.prompt_block()
    assert "SSB: https://www.ssb.gov.tr" in block and "dergipark.org.tr" in block
    assert any(h["path"].endswith("/alt") for h in client.get("/api/kb/search?q=Patriot teknik").json()["hits"])
    src = client.get("/api/kb/sources").json()["sources"]
    assert {s["domain"] for s in src} >= {"ssb.gov.tr", "dergipark.org.tr"}
    client.delete(f"/api/kb/sources/{ids[0]}")
    assert not db.query("SELECT id FROM kb_docs WHERE path LIKE 'https://www.ssb.gov.tr%'")
    try:
        websources.add_sources("http://localhost/x")
        raise AssertionError("yerel adres kabul edilmemeli")
    except ValueError:
        pass


def test_agents_get_priority_sources_in_prompt(client):
    from test_core import CALLS
    websources.add_sources("Akademik | https://dergipark.org.tr", priority=True, index=False)
    r = client.post("/api/command", json={"text": "Klasörü incele ve rapor yaz"}).json()
    _wait(client, r["task"]["id"], ("onay_bekliyor",))
    plan_call = [c for c in CALLS if "iş planı" in c["messages"][0]["content"]][-1]
    assert "dergipark.org.tr" in plan_call["messages"][-1]["content"]
