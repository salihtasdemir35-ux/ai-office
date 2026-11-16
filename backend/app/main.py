"""AI OFFICE – FastAPI sunucusu (yalnızca 127.0.0.1)."""
from __future__ import annotations

import asyncio
import importlib.util
import os
import shutil
import subprocess
import sys
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import __version__, backup, installer, memory, sync, vault
from .embeddings import embedder
from .embeddings import download_model as download_embedding
from . import model_manager as mm
from . import orchestrator as orch
from .agents import registry
from .agents.catalog import CATEGORIES, DEPARTMENTS, RECOMMENDED_TEAM
from .config import get_settings, list_machines, load_machine, machine_id, save_machine, update_settings
from .db import db
from .engine import engine
from .events import AGENT_STATUSES, bus
from .hardware import NO_WINDOW, detect, gpu_usage, resources
from .paths import BACKEND, DIRS, FRONTEND, ROOT, drive_letter, ensure_dirs, is_portable, portable_info, workspace
from .security import allowed_roots, cancel_all_approvals, pending, public, resolve_approval, resolve_path
from .tools import TOOLS

ensure_dirs()


async def _resource_loop():
    tick = 0
    while True:
        try:
            if tick % 3 == 0:
                await asyncio.to_thread(gpu_usage)
            await bus.emit("resources", resources=resources(), engine=engine.info())
            if tick % 5 == 0 and embedder.ready and db.conn:
                n = await embedder.index_pending()
                if n:
                    await bus.emit("embedder", embedder=embedder.info(), indexed=n)
        except Exception:
            pass
        tick += 1
        await asyncio.sleep(3)


async def _start_embedder():
    try:
        await embedder.start()
    except Exception:
        pass


@asynccontextmanager
async def lifespan(app: FastAPI):
    if vault.is_locked():  # şifreli kasa: parola girilene kadar veritabanı açılmaz
        loop_task = asyncio.create_task(_resource_loop())
        yield
        loop_task.cancel()
        await engine.stop()
        await embedder.stop()
        db.close()
        return
    db.open()
    orch.recover_on_start()
    asyncio.create_task(_start_embedder())
    m = load_machine()
    m["last_seen"] = time.time()
    if m.get("recommendation"):
        save_machine(m)
    for a in registry.hired():
        bus.agent_state[a["id"]] = {"status": "Müsait", "zone": "desk", "bubble": "", "with": None, "task_id": None}
    loop_task = asyncio.create_task(_resource_loop())
    yield
    loop_task.cancel()
    await orch.cancel_all()
    await engine.stop()
    await embedder.stop()
    db.close()


app = FastAPI(title="AI OFFICE", version=__version__, lifespan=lifespan)


def ok(**data):
    return {"ok": True, **data}


# ------------------------------------------------------------------ durum / kurulum
@app.get("/api/status")
async def status():
    s = get_settings()
    machine = load_machine()
    if vault.is_locked():
        return ok(version=__version__, locked=True, portable=is_portable(), drive=drive_letter())
    return ok(version=__version__, locked=False, setup_complete=s["setup_complete"], machine_known=bool(machine.get("recommendation")),
              machine_id=machine_id(), portable=is_portable(), portable_info=portable_info(), mode=s["mode"],
              root=str(ROOT), drive=drive_letter(), workspace=str(workspace()), engine=engine.info(),
              settings=_masked(s), recommendation=machine.get("recommendation"))


@app.get("/api/hardware")
async def hardware(refresh: bool = True):
    machine = load_machine()
    if refresh or not machine.get("hardware"):
        hw = await asyncio.to_thread(detect)
        machine["hardware"] = hw
        machine["recommendation"] = mm.recommend(hw)
        machine["last_seen"] = time.time()
        save_machine(machine)
    return ok(hardware=machine["hardware"], recommendation=machine["recommendation"])


@app.get("/api/models")
async def models():
    machine = load_machine()
    hw = machine.get("hardware") or await asyncio.to_thread(detect)
    return ok(models=mm.list_models(hw), recommendation=mm.recommend(hw), embedding=mm.CATALOG["embedding"],
              engine_files={"vulkan": bool(mm.find_server("vulkan")), "cpu": bool(mm.find_server("cpu"))},
              releases_page=mm.LLAMA_RELEASES_PAGE, jobs=[mm.job_public(j) for j in mm.jobs.values()])


class DownloadReq(BaseModel):
    model_id: str
    location: str = "usb"


@app.post("/api/models/download")
async def model_download(req: DownloadReq):
    if not mm.get_model(req.model_id):
        raise HTTPException(404, "Model bulunamadı")
    update_settings(model_location=req.location)
    return ok(job=mm.start_model_download(req.model_id, req.location))


@app.post("/api/models/select")
async def model_select(req: DownloadReq):
    machine = load_machine()
    machine["model_id"] = req.model_id
    save_machine(machine)
    await engine.stop()
    return ok(started=await engine.start(req.model_id), engine=engine.info())


@app.post("/api/engine/download")
async def engine_download():
    return ok(job=mm.start_engine_download())


@app.post("/api/engine/scan")
async def engine_scan():
    found = await asyncio.to_thread(mm.import_local_engines)
    return ok(found=found, engine_files={"vulkan": bool(mm.find_server("vulkan")), "cpu": bool(mm.find_server("cpu"))},
              releases_page=mm.LLAMA_RELEASES_PAGE)


@app.post("/api/jobs/{jid}/cancel")
async def job_cancel(jid: str):
    j = mm.jobs.get(jid)
    if j:
        j["cancel"].set()
    return ok()


@app.get("/api/engine/status")
async def engine_status():
    return ok(engine=engine.info())


@app.post("/api/engine/start")
async def engine_start():
    started = await engine.start()
    return ok(started=started, engine=engine.info())


@app.post("/api/engine/stop")
async def engine_stop():
    await engine.stop()
    return ok(engine=engine.info())


@app.post("/api/engine/test")
async def engine_test():
    t0 = time.time()
    try:
        ans = await engine.chat([{"role": "user", "content": "Tek cümleyle Türkçe olarak kendini tanıt."}], max_tokens=60)
        return ok(answer=ans, seconds=round(time.time() - t0, 1), engine=engine.info())
    except Exception as e:  # noqa
        return JSONResponse({"ok": False, "error": str(e), "engine": engine.info()}, status_code=200)


REQUIRED = ["fastapi", "uvicorn", "pydantic", "httpx", "psutil", "docx", "openpyxl", "pptx", "pymupdf", "bs4", "cryptography"]


@app.get("/api/setup/deps")
async def deps():
    return ok(packages=[{"name": p, "installed": importlib.util.find_spec(p) is not None} for p in REQUIRED],
              python=sys.version.split()[0], executable=sys.executable)


@app.post("/api/setup/install-deps")
async def install_deps():
    req = BACKEND / "requirements.txt"
    cmd = [sys.executable, "-m", "pip", "install", "-r", str(req), "--disable-pip-version-check"]
    proc = await asyncio.to_thread(subprocess.run, cmd, capture_output=True, text=True, creationflags=NO_WINDOW)
    return ok(returncode=proc.returncode, log=(proc.stdout + proc.stderr)[-4000:])


class SetupDone(BaseModel):
    mode: str = "portable"
    hired_agents: list[str] = []


@app.post("/api/setup/complete")
async def setup_complete(req: SetupDone):
    if req.hired_agents:
        registry.set_team(req.hired_agents)
    update_settings(setup_complete=True, mode=req.mode)
    for a in registry.hired():
        bus.agent_state.setdefault(a["id"], {"status": "Müsait", "zone": "desk", "bubble": "", "with": None})
    return ok(message="AI OFFICE hazır. Dijital çalışanlarınız görev bekliyor.")


@app.post("/api/setup/system-test")
async def system_test():
    results = []

    def add(name, passed, detail=""):
        results.append({"name": name, "ok": bool(passed), "detail": str(detail)[:300]})
    try:
        db.execute("CREATE TABLE IF NOT EXISTS _t(x)"); db.execute("DROP TABLE _t")
        add("Veritabanı (SQLite)", True, str(DIRS['database']))
    except Exception as e:  # noqa
        add("Veritabanı (SQLite)", False, e)
    try:
        f = workspace() / ".yazma_testi"
        f.write_text("ok", encoding="utf-8"); f.unlink()
        add("Çalışma klasörü yazma", True, str(workspace()))
    except Exception as e:  # noqa
        add("Çalışma klasörü yazma", False, e)
    try:
        from .tools.documents import build_docx, build_pdf, build_pptx, build_xlsx
        tdir = DIRS["cache"] / "systest"; tdir.mkdir(exist_ok=True)
        build_docx(tdir / "t.docx", "Test", "# Başlık\n- şğıİöç madde")
        build_xlsx(tdir / "t.xlsx", [["a", "b"], [1, 2]])
        build_pptx(tdir / "t.pptx", "Test", [{"baslik": "S1", "maddeler": ["m"]}])
        build_pdf(tdir / "t.pdf", "Test", "Türkçe karakter: şğıİöçü")
        add("Belge üretimi (Word/Excel/PowerPoint/PDF)", True)
    except Exception as e:  # noqa
        add("Belge üretimi (Word/Excel/PowerPoint/PDF)", False, e)
    try:
        resolve_path("/etc" if os.name != "nt" else "C:\\Windows")
        add("Güvenlik: izinsiz klasör engeli", False, "engellenmedi!")
    except Exception:
        add("Güvenlik: izinsiz klasör engeli", True)
    started = await engine.start()
    add("Yerel AI motoru", started, engine.info().get("model_name") or engine.error)
    if started:
        try:
            t0 = time.time()
            ans = await engine.chat([{"role": "user", "content": "Sadece 'Hazırım' yaz."}], max_tokens=20)
            add("Model yanıt testi", bool(ans.strip()), f"{ans.strip()[:60]} ({time.time()-t0:.1f} sn)")
        except Exception as e:  # noqa
            add("Model yanıt testi", False, e)
    from .hardware import _internet
    add("İnternet (isteğe bağlı)", await asyncio.to_thread(_internet), "yoksa yerel çalışma devam eder")
    return ok(results=results, all_ok=all(r["ok"] for r in results if not r["name"].startswith("İnternet")))


# ------------------------------------------------------------------ ajanlar
@app.get("/api/agents")
async def agents():
    states = bus.agent_state
    out = [{**a, "state": states.get(a["id"], {"status": "Müsait"})} for a in registry.all_agents()]
    return ok(agents=out, departments=DEPARTMENTS, categories=CATEGORIES, recommended=RECOMMENDED_TEAM,
              statuses=AGENT_STATUSES, tools=list(TOOLS))


@app.get("/api/agents/{agent_id}")
async def agent_detail(agent_id: str):
    a = registry.get(agent_id)
    if not a:
        raise HTTPException(404, "Ajan bulunamadı")
    msgs = db.query("SELECT * FROM messages WHERE sender=? OR receiver=? ORDER BY id DESC LIMIT 40", (agent_id, agent_id))
    tasks = db.query("SELECT id,title,status,created FROM tasks WHERE agents LIKE ? ORDER BY created DESC LIMIT 20",
                     (f'%"{agent_id}"%',))
    mem = memory.search(owner=agent_id, limit=20)
    return ok(agent={**a, "state": bus.agent_state.get(agent_id, {"status": "Müsait"})}, messages=msgs, tasks=tasks, memory=mem)


class IdsReq(BaseModel):
    ids: list[str]


@app.post("/api/agents/hire")
async def agents_hire(req: IdsReq):
    team = registry.hire(req.ids)
    for i in req.ids:
        bus.agent_state.setdefault(i, {"status": "Müsait", "zone": "desk", "bubble": ""})
    return ok(hired=team)


@app.post("/api/agents/team")
async def agents_team(req: IdsReq):
    return ok(hired=registry.set_team(req.ids))


class RenameReq(BaseModel):
    name: str
    avatar: str | None = None


@app.post("/api/agents/{agent_id}/rename")
async def agents_rename(agent_id: str, req: RenameReq):
    try:
        a = registry.rename(agent_id, req.name, req.avatar)
    except ValueError as e:
        raise HTTPException(400, str(e))
    await bus.emit("agents_changed")
    return ok(agent=a)


class CountReq(BaseModel):
    count: int
    names: list[str] = []


@app.post("/api/agents/{agent_id}/count")
async def agents_count(agent_id: str, req: CountReq):
    try:
        members = registry.set_count(agent_id, req.count, req.names)
    except ValueError as e:
        raise HTTPException(400, str(e))
    for a in members:
        bus.agent_state.setdefault(a["id"], {"status": "Müsait", "zone": "desk", "bubble": ""})
    await bus.emit("agents_changed")
    return ok(members=members)


@app.post("/api/agents/{agent_id}/fire")
async def agents_fire(agent_id: str):
    try:
        return ok(hired=registry.fire(agent_id))
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.post("/api/agents/custom")
async def agents_custom(data: dict):
    return ok(agent=registry.create_custom(data))


@app.delete("/api/agents/custom/{agent_id}")
async def agents_custom_delete(agent_id: str):
    try:
        registry.delete_custom(agent_id)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return ok()


class ChatReq(BaseModel):
    message: str


@app.post("/api/agents/{agent_id}/chat")
async def agent_chat(agent_id: str, req: ChatReq):
    try:
        return ok(answer=await orch.direct_chat(agent_id, req.message))
    except Exception as e:  # noqa
        raise HTTPException(500, str(e))


# ------------------------------------------------------------------ görevler
class CommandReq(BaseModel):
    text: str
    agent_id: str | None = None


@app.post("/api/command")
async def command(req: CommandReq):
    if not req.text.strip():
        raise HTTPException(400, "Komut boş")
    if req.agent_id and not (registry.get(req.agent_id) or {}).get("hired"):
        raise HTTPException(400, "Bu ajan ofiste değil")
    return ok(task=await orch.create_task(req.text, req.agent_id))


@app.get("/api/tasks")
async def tasks():
    rows = db.query("SELECT id FROM tasks ORDER BY created DESC LIMIT 200")
    return ok(tasks=[orch.public_task(db.load_task(r["id"])) for r in rows])


@app.get("/api/tasks/{task_id}")
async def task_detail(task_id: str):
    t = db.load_task(task_id)
    if not t:
        raise HTTPException(404, "Görev bulunamadı")
    msgs = db.query("SELECT * FROM messages WHERE task_id=? ORDER BY id", (task_id,))
    return ok(task=orch.public_task(t), messages=msgs, running=task_id in orch.running)


@app.post("/api/tasks/{task_id}/approve")
async def task_approve(task_id: str):
    try:
        return ok(task=await orch.approve(task_id))
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.post("/api/tasks/{task_id}/resume")
async def task_resume(task_id: str):
    return await task_approve(task_id)


@app.post("/api/tasks/{task_id}/cancel")
async def task_cancel(task_id: str):
    await orch.cancel(task_id)
    return ok()


@app.post("/api/tasks/{task_id}/note")
async def task_note(task_id: str, req: ChatReq):
    orch.add_note(task_id, req.message)
    return ok()


@app.get("/api/messages")
async def messages(task_id: str | None = None, kind: str | None = None, limit: int = 50):
    sql, params = "SELECT * FROM messages", []
    conds = []
    if task_id:
        conds.append("task_id=?"); params.append(task_id)
    if kind:
        conds.append("kind=?"); params.append(kind)
    if conds:
        sql += " WHERE " + " AND ".join(conds)
    sql += " ORDER BY id DESC LIMIT ?"
    params.append(min(limit, 500))
    return ok(messages=list(reversed(db.query(sql, params))))


# ------------------------------------------------------------------ hafıza & bilgi bankası
@app.get("/api/memory")
async def memory_list(q: str = "", layer: str = ""):
    return ok(items=memory.search(q, layer), stats=memory.stats(), layers=memory.LAYERS)


class MemReq(BaseModel):
    layer: str = "kullanici"
    content: str
    owner: str = ""
    source: str = "kullanıcı"
    confidence: float = 0.9
    shared: bool = False


@app.post("/api/memory")
async def memory_add(req: MemReq):
    return ok(id=memory.add(req.layer, req.content, owner=req.owner, source=req.source,
                            confidence=req.confidence, created_by="kullanici", shared=req.shared))


@app.put("/api/memory/{mid}")
async def memory_update(mid: int, data: dict):
    memory.update(mid, **data)
    return ok()


@app.delete("/api/memory/{mid}")
async def memory_delete(mid: int):
    memory.delete(mid)
    return ok()


class PathReq(BaseModel):
    path: str
    reveal: bool = False


@app.get("/api/kb")
async def kb_list():
    return ok(docs=db.query("SELECT * FROM kb_docs ORDER BY added DESC"))


@app.post("/api/kb/add")
async def kb_add(req: PathReq):
    p = resolve_path(req.path, must_exist=True)
    files = [p] if p.is_file() else [f for f in p.rglob("*") if f.suffix.lower() in memory.KB_EXT][:500]
    added, errors = [], []
    for f in files:
        try:
            added.append(await asyncio.to_thread(memory.kb_add, f))
        except Exception as e:  # noqa
            errors.append(f"{f.name}: {e}")
    return ok(added=added, errors=errors)


class SourceReq(BaseModel):
    urls: str
    title: str = ""
    priority: bool = True
    index: bool = True
    max_pages: int = 1


@app.get("/api/kb/sources")
async def kb_sources():
    from . import websources
    return ok(sources=websources.list_sources())


@app.post("/api/kb/sources")
async def kb_sources_add(req: SourceReq):
    from . import websources
    try:
        ids = websources.add_sources(req.urls, req.title, req.priority, req.index, req.max_pages)
    except ValueError as e:
        raise HTTPException(400, str(e))
    results = []
    if req.index:
        if not get_settings().get("internet_enabled", True):
            raise HTTPException(400, "İnternet erişimi kapalı; kaynak eklendi ama içeriği indirilemedi.")
        for i in ids:
            try:
                results.append(await websources.index_source(i))
            except Exception as e:  # noqa
                results.append({"id": i, "status": f"Hata: {e}"})
    return ok(ids=ids, results=results)


@app.post("/api/kb/sources/{sid}/refresh")
async def kb_source_refresh(sid: int):
    from . import websources
    try:
        return ok(**await websources.index_source(sid))
    except ValueError as e:
        raise HTTPException(404, str(e))


@app.put("/api/kb/sources/{sid}")
async def kb_source_update(sid: int, data: dict):
    from . import websources
    websources.update_source(sid, **data)
    return ok()


@app.delete("/api/kb/sources/{sid}")
async def kb_source_delete(sid: int):
    from . import websources
    websources.delete_source(sid)
    return ok()


@app.post("/api/kb/refresh")
async def kb_refresh():
    return ok(updated=await asyncio.to_thread(memory.kb_refresh))


@app.get("/api/kb/search")
async def kb_search(q: str):
    return ok(hits=await memory.kb_search_hybrid(q, 15), embedder=embedder.info())


@app.get("/api/embeddings/status")
async def emb_status():
    return ok(embedder=embedder.info(), pending=embedder.pending_count() if db.conn else 0)


@app.post("/api/embeddings/download")
async def emb_download():
    return ok(job=await download_embedding())


@app.post("/api/embeddings/index")
async def emb_index():
    if not await embedder.start():
        raise HTTPException(400, embedder.error or "Embedding modeli hazır değil")
    total = 0
    while True:
        n = await embedder.index_pending()
        total += n
        if not n:
            break
    return ok(indexed=total)


@app.delete("/api/kb/{doc_id}")
async def kb_delete(doc_id: int):
    memory.kb_delete(doc_id)
    return ok()


# ------------------------------------------------------------------ dosyalar
@app.get("/api/files")
async def files_list():
    root = workspace()
    out = []
    for f in sorted(root.rglob("*"), key=lambda p: p.stat().st_mtime, reverse=True)[:500]:
        if f.is_file() and not f.name.startswith("."):
            out.append({"path": str(f), "name": f.name, "folder": str(f.parent.relative_to(root)),
                        "size_kb": round(f.stat().st_size / 1024, 1), "mtime": f.stat().st_mtime})
    return ok(files=out, root=str(root), allowed=[str(r) for r in allowed_roots()])


@app.get("/api/files/download")
async def files_download(path: str):
    p = resolve_path(path, must_exist=True)
    return FileResponse(p, filename=p.name)


@app.post("/api/files/open")
async def files_open(req: PathReq):
    p = resolve_path(req.path, must_exist=True)
    if os.name != "nt":
        return ok(path=str(p), note="Dosya açma yalnızca Windows'ta desteklenir.")
    if req.reveal:
        subprocess.Popen(["explorer", "/select,", str(p)])
    else:
        os.startfile(str(p))  # type: ignore[attr-defined]
    return ok(path=str(p))


@app.post("/api/system/pick-folder")
async def pick_folder():
    if os.name != "nt":
        raise HTTPException(400, "Klasör seçici yalnızca Windows'ta. Yolu elle yazın.")
    ps = ("Add-Type -AssemblyName System.Windows.Forms; $f=New-Object System.Windows.Forms.FolderBrowserDialog; "
          "$f.Description='AI OFFICE için klasör seçin'; if($f.ShowDialog() -eq 'OK'){$f.SelectedPath}")
    r = await asyncio.to_thread(subprocess.run, ["powershell", "-NoProfile", "-STA", "-Command", ps],
                                capture_output=True, text=True, creationflags=NO_WINDOW)
    return ok(path=(r.stdout or "").strip())


# ------------------------------------------------------------------ araçlar, ayarlar, onaylar, geçmiş
@app.get("/api/tools")
async def tools():
    agents = registry.all_agents()
    return ok(tools=[{"name": t.name, "label": t.label, "level": t.level, "desc": t.desc, "group": t.group,
                      "needs_internet": t.needs_internet, "needs_approval": t.needs_approval,
                      "agents": [a["title"] for a in agents if t.name in a.get("tools", []) and a["hired"]]}
                     for t in TOOLS.values()])


@app.get("/api/settings")
async def settings_get():
    return ok(settings=_masked(get_settings()))


SAFE_KEYS = {"internet_enabled", "files_enabled", "agents_paused", "engine_preference", "model_override",
             "max_steps", "max_tool_iters", "max_messages_per_task", "memory_enabled", "model_location", "mode",
             "code_exec_enabled", "max_parallel_tasks", "embedding_enabled", "smtp"}


def _masked(s: dict) -> dict:
    s = dict(s)
    if s.get("smtp", {}).get("password"):
        s["smtp"] = {**s["smtp"], "password": "********"}
    return s


@app.put("/api/settings")
async def settings_put(data: dict):
    changes = {k: v for k, v in data.items() if k in SAFE_KEYS}
    if "smtp" in changes:
        old = get_settings().get("smtp") or {}
        sm = {k: str(v) for k, v in (changes["smtp"] or {}).items() if k in ("host", "port", "user", "password", "from")}
        if sm.get("password") in (None, "", "********"):
            sm["password"] = old.get("password", "")
        changes["smtp"] = sm
    return ok(settings=_masked(update_settings(**changes)))


@app.post("/api/settings/folders")
async def folder_add(req: PathReq):
    p = Path(req.path).expanduser()
    if not p.exists() or not p.is_dir():
        raise HTTPException(400, "Klasör bulunamadı")
    cur = get_settings()["allowed_folders"]
    if str(p.resolve()) not in cur:
        cur.append(str(p.resolve()))
    return ok(settings=update_settings(allowed_folders=cur))


@app.post("/api/settings/folders/remove")
async def folder_remove(req: PathReq):
    cur = [f for f in get_settings()["allowed_folders"] if f != req.path]
    return ok(settings=update_settings(allowed_folders=cur))


@app.get("/api/approvals")
async def approvals():
    return ok(items=[public(i) for i in pending.values()])


class ApproveReq(BaseModel):
    approve: bool


@app.post("/api/approvals/{aid}")
async def approval_answer(aid: str, req: ApproveReq):
    return ok(done=resolve_approval(aid, req.approve))


@app.get("/api/audit")
async def audit(limit: int = 300):
    return ok(items=db.query("SELECT * FROM audit ORDER BY id DESC LIMIT ?", (min(limit, 2000),)))


# ------------------------------------------------------------------ Aşama 4 bileşenleri
@app.get("/api/tools/components")
async def tool_components():
    from .tools.extra import playwright_status
    return ok(ocr=importlib.util.find_spec("rapidocr_onnxruntime") is not None,
              data=importlib.util.find_spec("pandas") is not None and importlib.util.find_spec("matplotlib") is not None,
              browser=playwright_status(), code_exec=get_settings().get("code_exec_enabled", False),
              smtp=bool((get_settings().get("smtp") or {}).get("host")))


@app.post("/api/tools/install-browser")
async def install_browser():
    env = {**os.environ, "PLAYWRIGHT_BROWSERS_PATH": str(DIRS["dependencies"] / "ms-playwright")}
    logs = []
    for cmd in ([sys.executable, "-m", "pip", "install", "playwright", "--disable-pip-version-check"],
                [sys.executable, "-m", "playwright", "install", "chromium"]):
        r = await asyncio.to_thread(subprocess.run, cmd, capture_output=True, text=True, env=env, creationflags=NO_WINDOW)
        logs.append((r.stdout + r.stderr)[-2000:])
        if r.returncode != 0:
            return ok(success=False, log="\n".join(logs))
    return ok(success=True, log="\n".join(logs))


# ------------------------------------------------------------------ Aşama 6: kasa, senkronizasyon, model yönetimi
class PwReq(BaseModel):
    password: str
    include_workspace: bool = False


@app.get("/api/vault/status")
async def vault_status():
    return ok(locked=vault.is_locked())


@app.post("/api/vault/lock")
async def vault_lock(req: PwReq):
    await orch.cancel_all()
    await engine.stop()
    await embedder.stop()
    try:
        r = await asyncio.to_thread(vault.lock, req.password, req.include_workspace)
    except ValueError as e:
        raise HTTPException(400, str(e))
    (DIRS["runtime"] / "port.txt").unlink(missing_ok=True)
    await bus.emit("safe_exit", step="done", steps=[f"{r['files']} dosya şifrelendi ({r['vault']})",
                                                    "Açık kopyalar silindi", "AI motoru kapatıldı"],
                   message="Veriler şifrelendi. USB'yi güvenle çıkarabilirsiniz. Açarken parolanız sorulacak.")

    async def _bye():
        await asyncio.sleep(1.5)
        os._exit(0)
    asyncio.create_task(_bye())
    return ok(**r)


@app.post("/api/vault/unlock")
async def vault_unlock(req: PwReq):
    try:
        r = await asyncio.to_thread(vault.unlock, req.password)
    except ValueError as e:
        raise HTTPException(400, str(e))
    orch.recover_on_start()
    asyncio.create_task(_start_embedder())
    for a in registry.hired():
        bus.agent_state.setdefault(a["id"], {"status": "Müsait", "zone": "desk", "bubble": ""})
    return ok(**r)


class SyncReq(BaseModel):
    path: str
    password: str = ""


@app.post("/api/sync/compare")
async def sync_compare(req: SyncReq):
    try:
        return ok(**await asyncio.to_thread(sync.compare, req.path, req.password))
    except (ValueError, FileNotFoundError) as e:
        raise HTTPException(400, str(e))


class SyncApply(BaseModel):
    session: str
    decisions: dict[str, str] = {}
    import_new: bool = True


@app.post("/api/sync/apply")
async def sync_apply(req: SyncApply):
    try:
        return ok(**await asyncio.to_thread(sync.apply, req.session, req.decisions, req.import_new))
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.get("/api/models/files")
async def model_files():
    return ok(files=installer.model_files())


class ModelFileReq(BaseModel):
    file: str
    location: str


@app.post("/api/models/move")
async def model_move(req: ModelFileReq):
    await engine.stop()
    await embedder.stop()
    try:
        return ok(path=await asyncio.to_thread(installer.move_model, req.file, req.location))
    except (ValueError, FileNotFoundError) as e:
        raise HTTPException(400, str(e))


@app.post("/api/models/delete")
async def model_delete(req: ModelFileReq):
    await engine.stop()
    await embedder.stop()
    try:
        installer.delete_model(req.file, req.location)
    except FileNotFoundError as e:
        raise HTTPException(404, str(e))
    return ok()


class InstallReq(BaseModel):
    include_models: bool = True


@app.post("/api/setup/install-local")
async def install_local(req: InstallReq):
    try:
        return ok(**await asyncio.to_thread(installer.install_local, req.include_models))
    except ValueError as e:
        raise HTTPException(400, str(e))


# ------------------------------------------------------------------ yedekleme, USB, sistem
class BackupReq(BaseModel):
    parts: list[str] = ["agents", "memory", "projects", "settings", "database"]
    password: str = ""


@app.get("/api/backups")
async def backups():
    return ok(items=backup.list_backups(), parts=list(backup.PARTS))


@app.post("/api/backups")
async def backup_create(req: BackupReq):
    p = await asyncio.to_thread(backup.create_backup, req.parts, req.password)
    return ok(name=p.name)


class RestoreReq(BaseModel):
    name: str
    password: str = ""


@app.post("/api/backups/restore")
async def backup_restore(req: RestoreReq):
    if orch.running:
        raise HTTPException(400, "Önce çalışan görevleri durdurun.")
    try:
        return ok(**await asyncio.to_thread(backup.restore_backup, req.name, req.password))
    except (ValueError, FileNotFoundError) as e:
        raise HTTPException(400, str(e))


@app.get("/api/portable")
async def portable():
    s = get_settings()
    return ok(portable=is_portable(), info=portable_info(), root=str(ROOT), drive=drive_letter(),
              model_location=s["model_location"], machines=list_machines(), machine_id=machine_id(),
              models_on_usb=[f.name for f in DIRS["models"].glob("*.gguf")],
              engines={"vulkan": bool(mm.find_server("vulkan")), "cpu": bool(mm.find_server("cpu"))})


@app.get("/api/system/resources")
async def system_resources():
    return ok(resources=resources(), engine=engine.info(), embedder=embedder.info(), memory=memory.stats(),
              running_tasks=list(orch.running), approvals=len(pending))


@app.post("/api/system/stop-all")
async def stop_all():
    await orch.cancel_all()
    cancel_all_approvals()
    update_settings(agents_paused=False)
    for aid in list(bus.agent_state):
        await bus.set_agent(aid, "Müsait", "")
    return ok()


@app.post("/api/system/safe-exit")
async def safe_exit():
    steps = []
    await bus.emit("safe_exit", step="Aktif görevler durduruluyor…")
    await orch.cancel_all()
    cancel_all_approvals()
    for _ in range(20):
        if not orch.running:
            break
        await asyncio.sleep(0.5)
    steps.append(f"Aktif görevler durduruldu (kalan: {len(orch.running)})")
    await engine.stop()
    await embedder.stop()
    steps.append("AI motoru kapatıldı, model dosyası serbest bırakıldı")
    db.checkpoint()
    db.close()
    steps.append("Veritabanı ve hafıza diske yazıldı")
    (DIRS["runtime"] / "port.txt").unlink(missing_ok=True)
    steps.append("Geçici dosyalar temizlendi")
    await bus.emit("safe_exit", step="done", steps=steps,
                   message="USB çıkarılmaya hazır. Pencereyi kapatıp USB'yi güvenle çıkarabilirsiniz.")

    async def _bye():
        await asyncio.sleep(1.5)
        os._exit(0)
    asyncio.create_task(_bye())
    return ok(steps=steps, message="USB çıkarılmaya hazır.")


# ------------------------------------------------------------------ WebSocket & arayüz
@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket):
    await bus.connect(ws)
    try:
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        bus.disconnect(ws)
    except Exception:
        bus.disconnect(ws)


app.mount("/", StaticFiles(directory=str(FRONTEND), html=True), name="frontend")
