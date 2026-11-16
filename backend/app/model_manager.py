"""Model kataloğu, donanıma göre OTOMATİK model seçimi, devam ettirilebilir indirme, llama.cpp motoru indirme."""
from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
import time
import uuid
import zipfile
from pathlib import Path
from typing import Callable

import httpx

from .events import bus
from .paths import DIRS, local_appdata

CATALOG: dict = json.loads((Path(__file__).parent / "data" / "models_catalog.json").read_text(encoding="utf-8"))
TIER_LABELS = {"cok_dusuk": "Düşük donanım (çok zayıf)", "dusuk": "Düşük donanım",
               "dengeli": "Dengeli performans", "yuksek": "Yüksek performans"}
LLAMA_RELEASES_API = "https://api.github.com/repos/ggml-org/llama.cpp/releases?per_page=40"
LLAMA_RELEASES_PAGE = "https://github.com/ggml-org/llama.cpp/releases"

jobs: dict[str, dict] = {}


def get_model(model_id: str) -> dict | None:
    return next((m for m in CATALOG["models"] if m["id"] == model_id), None)


def model_dirs() -> list[Path]:
    return [DIRS["models"], local_appdata() / "models"]


def find_local(model_id: str) -> Path | None:
    m = get_model(model_id)
    if not m:
        return None
    for d in model_dirs():
        p = d / m["file"]
        if p.exists() and p.stat().st_size > 1024 * 1024:
            return p
    return None


def local_models() -> list[str]:
    return [m["id"] for m in CATALOG["models"] if find_local(m["id"])]


def target_dir(location: str, model: dict) -> Path:
    if location == "local":
        return local_appdata() / "models"
    if location == "hybrid":  # küçük model USB'de, büyük model bilgisayarda
        return DIRS["models"] if model["size_gb"] <= 2.5 else local_appdata() / "models"
    return DIRS["models"]


def recommend(hw: dict) -> dict:
    """Donanıma göre en verimli modeli ve çalışma ayarlarını seçer."""
    ram = hw.get("ram_total_gb", 8)
    vram = hw.get("vram_gb", 0) if hw.get("gpu_usable") else 0
    reasons = []
    if ram >= 30 and (vram >= 10 or ram >= 48):
        mid, tier = "qwen2.5-14b", "yuksek"
        reasons.append(f"{ram} GB RAM" + (f" ve {vram} GB VRAM" if vram else "") + " yüksek performans için yeterli.")
    elif ram >= 14 or vram >= 6:
        mid, tier = "qwen2.5-7b", "dengeli"
        reasons.append(f"{ram} GB RAM" + (f", {vram} GB VRAM" if vram else "") + " ile 7B model dengeli çalışır.")
    elif ram >= 7:
        mid, tier = "qwen2.5-3b", "dusuk"
        reasons.append(f"{ram} GB RAM için 3B model en verimli seçim (8 GB sistemler için optimize).")
    else:
        mid, tier = "qwen2.5-1.5b", "cok_dusuk"
        reasons.append(f"{ram} GB RAM çok düşük; en hafif model seçildi.")
    m = get_model(mid)
    # Disk yetmiyorsa küçült
    order = ["qwen2.5-14b", "qwen2.5-7b", "qwen2.5-3b", "qwen2.5-1.5b"]
    while hw.get("disk_free_gb", 99) < m["size_gb"] + 1 and mid != order[-1] and not find_local(mid):
        mid = order[order.index(mid) + 1]
        m = get_model(mid)
        reasons.append("Disk alanı yetersiz olduğu için daha küçük model seçildi.")
    gpu_mode = bool(hw.get("gpu_usable"))
    if gpu_mode and vram >= m["size_gb"] * 1.15:
        ngl = 99
        reasons.append(f"GPU ({hw['gpu_best']['vendor']}) modelin tamamını taşıyabilir → Vulkan GPU hızlandırma.")
    elif gpu_mode:
        ngl = 99 if vram >= m["size_gb"] * 0.9 else max(0, int(28 * vram / max(m["size_gb"], 0.1)))
        reasons.append("GPU belleği kısmen yeterli → katmanların bir kısmı GPU'da.")
    else:
        ngl = 0
        reasons.append("Uygun GPU bulunamadı veya VRAM < 3 GB → CPU modu.")
    threads = max(1, min(hw.get("cores_physical", 4), 8))
    return {"model_id": mid, "tier": tier, "tier_label": TIER_LABELS[tier], "gpu_mode": gpu_mode and ngl > 0,
            "ngl": ngl, "ctx": m["ctx"], "threads": threads, "reasons": reasons}


def list_models(hw: dict) -> list[dict]:
    rec = recommend(hw)
    out = []
    for m in CATALOG["models"]:
        p = find_local(m["id"])
        out.append({**m, "local_path": str(p) if p else None, "installed": bool(p),
                    "fits_ram": hw.get("ram_total_gb", 0) >= m["ram_gb"] + 1.5,
                    "fits_disk": hw.get("disk_free_gb", 0) >= m["size_gb"] + 0.5 or bool(p),
                    "recommended": m["id"] == rec["model_id"]})
    return out


# ------------------------------------------------------------------ indirme
async def download_file(url: str, dest: Path, progress: Callable[[int, int], None] | None = None,
                        cancel: asyncio.Event | None = None) -> Path:
    """Yarıda kalırsa kaldığı yerden devam eden indirme (.part dosyası + HTTP Range)."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_name(dest.name + ".part")
    start = part.stat().st_size if part.exists() else 0
    headers = {"Range": f"bytes={start}-"} if start else {}
    timeout = httpx.Timeout(30.0, read=180.0)
    async with httpx.AsyncClient(follow_redirects=True, timeout=timeout) as client:
        async with client.stream("GET", url, headers=headers) as r:
            if r.status_code == 416:  # zaten tamamlanmış
                part.replace(dest)
                return dest
            if r.status_code not in (200, 206):
                raise RuntimeError(f"İndirme hatası HTTP {r.status_code}: {url}")
            if start and r.status_code == 200:
                start = 0  # sunucu devam ettirmeyi desteklemiyor
            total = start + int(r.headers.get("content-length", 0) or 0)
            done = start
            last = 0.0
            with open(part, "ab" if start else "wb") as f:
                async for chunk in r.aiter_bytes(1 << 20):
                    if cancel and cancel.is_set():
                        raise asyncio.CancelledError("İndirme iptal edildi")
                    f.write(chunk)
                    done += len(chunk)
                    if progress and time.time() - last > 0.5:
                        last = time.time()
                        progress(done, total)
    if progress:
        progress(done, total)
    part.replace(dest)
    return dest


def _job(kind: str, label: str) -> dict:
    jid = uuid.uuid4().hex[:8]
    jobs[jid] = {"id": jid, "kind": kind, "label": label, "status": "çalışıyor", "done": 0, "total": 0,
                 "error": None, "cancel": asyncio.Event()}
    return jobs[jid]


def job_public(j: dict) -> dict:
    return {k: v for k, v in j.items() if k != "cancel"}


def _progress_cb(job: dict):
    def cb(done: int, total: int) -> None:
        job["done"], job["total"] = done, total
        bus.emit_nowait("job", job=job_public(job))
    return cb


async def download_model(model_id: str, location: str = "usb", job: dict | None = None) -> Path:
    m = get_model(model_id)
    if not m:
        raise ValueError("Bilinmeyen model")
    existing = find_local(model_id)
    if existing:
        return existing
    dest = target_dir(location, m) / m["file"]
    job = job or _job("model", m["name"])
    path = await download_file(m["url"], dest, _progress_cb(job), job["cancel"])
    with open(path, "rb") as f:
        if f.read(4) != b"GGUF":
            path.unlink(missing_ok=True)
            raise RuntimeError("İndirilen dosya geçerli bir GGUF modeli değil.")
    return path


def start_model_download(model_id: str, location: str) -> dict:
    m = get_model(model_id)
    job = _job("model", m["name"] if m else model_id)

    async def run():
        try:
            await download_model(model_id, location, job)
            job["status"] = "tamamlandı"
        except Exception as e:  # noqa
            job["status"], job["error"] = "hata", str(e)
        await bus.emit("job", job=job_public(job))
    asyncio.create_task(run())
    return job_public(job)


# ------------------------------------------------------------------ llama.cpp motoru
ENGINE_INFO = DIRS["engines"] / "engine_info.json"
VARIANT_PATTERNS = {
    "vulkan": [r"bin-win-vulkan-x64\.zip$"],
    "cpu": [r"bin-win-cpu-x64\.zip$", r"bin-win-avx2-x64\.zip$", r"bin-win-noavx-x64\.zip$"],
}


def engine_info() -> dict:
    try:
        return json.loads(ENGINE_INFO.read_text(encoding="utf-8"))
    except Exception:
        return {}


def find_server(variant: str) -> Path | None:
    exe = "llama-server.exe" if os.name == "nt" else "llama-server"
    info = engine_info().get(variant)
    if info:
        p = DIRS["engines"] / info["dir"] / exe
        if p.exists():
            return p
    d = DIRS["engines"] / f"llama_{variant}"
    if d.exists():
        for p in d.rglob(exe):
            return p
    # Kullanıcının elle engines klasörüne koyduğu herhangi bir llama.cpp
    for p in DIRS["engines"].rglob(exe):
        low = str(p).lower()
        if variant in low or (variant == "cpu" and "vulkan" not in low and "cuda" not in low):
            return p
    if variant == "cpu" and os.name != "nt":
        w = shutil.which("llama-server")
        if w:
            return Path(w)
    return None


def _variant_of(name: str) -> str | None:
    for variant, pats in VARIANT_PATTERNS.items():
        if any(re.search(p, name) for p in pats):
            return variant
    return None


def _extract_engine(zpath: Path, variant: str, tag: str) -> dict:
    out = DIRS["engines"] / f"llama_{variant}"
    out.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zpath) as z:
        for m in z.infolist():
            target = (out / m.filename).resolve()
            if out.resolve() in target.parents or target == out.resolve():
                z.extract(m, out)
    exe = next(out.rglob("llama-server.exe"), None) or next(out.rglob("llama-server"), None)
    if not exe:
        raise RuntimeError(f"{zpath.name} içinde llama-server.exe bulunamadı.")
    info = engine_info()
    info[variant] = {"dir": str(exe.parent.relative_to(DIRS["engines"])), "tag": tag}
    ENGINE_INFO.write_text(json.dumps(info, indent=2), encoding="utf-8")
    return info


def pick_asset(releases: list[dict], variant: str) -> tuple[dict | None, str | None]:
    """Windows paketi bulunan en yeni sürümü seçer ('latest' sürümde paket olmayabilir)."""
    for rel in releases:
        if rel.get("draft"):
            continue
        for a in rel.get("assets", []):
            if _variant_of(a["name"]) == variant:
                return a, rel.get("tag_name")
    return None, None


def import_local_engines() -> list[str]:
    """İnternetten inemediyse: kullanıcının indirdiği llama.cpp ZIP'lerini engines, cache ve İndirilenler
    klasörlerinde bulup otomatik kurar (llama-bNNNN-bin-win-vulkan-x64.zip / ...-cpu-x64.zip)."""
    found = []
    dirs = [DIRS["engines"], DIRS["cache"], Path.home() / "Downloads", Path.home() / "İndirilenler"]
    for d in dirs:
        if not d.exists():
            continue
        for z in sorted(d.glob("llama-*bin-win-*.zip"), key=lambda p: p.stat().st_mtime, reverse=True):
            variant = _variant_of(z.name)
            if not variant or find_server(variant) or variant in found:
                continue
            try:
                _extract_engine(z, variant, z.name.split("-bin-")[0].replace("llama-", ""))
                found.append(variant)
            except Exception:
                continue
    return found


async def download_engine(variants: tuple[str, ...] = ("vulkan", "cpu"), job: dict | None = None) -> dict:
    """llama.cpp hem sürüm numaralı (v0.x) hem derleme (bNNNNN) sürümleri yayınlar; 'latest' sürümde Windows
    paketleri olmayabilir. Bu yüzden son 40 sürüm taranır ve paketi OLAN en yeni sürüm seçilir."""
    job = job or _job("engine", "llama.cpp yerel AI motoru")
    import_local_engines()
    need = [v for v in variants if not find_server(v)]
    if not need:
        return engine_info()
    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=30) as c:
            r = await c.get(LLAMA_RELEASES_API, headers={"Accept": "application/vnd.github+json",
                                                         "User-Agent": "AI-OFFICE"})
            if r.status_code == 403:
                raise RuntimeError("GitHub geçici indirme sınırı (saatte 60 istek) doldu; 1 saat sonra tekrar deneyin.")
            r.raise_for_status()
            releases = r.json()
    except httpx.HTTPError as e:
        raise RuntimeError(f"GitHub'a ulaşılamadı ({type(e).__name__}).") from e
    errors = []
    for variant in need:
        asset, tag = pick_asset(releases, variant)
        if not asset:
            errors.append(variant)
            continue
        zpath = DIRS["cache"] / asset["name"]
        job["label"] = f"llama.cpp ({variant}) {tag}"
        await download_file(asset["browser_download_url"], zpath, _progress_cb(job), job["cancel"])
        _extract_engine(zpath, variant, tag)
        zpath.unlink(missing_ok=True)
    if errors and not (find_server("vulkan") or find_server("cpu")):
        raise RuntimeError(
            f"Son sürümlerde Windows paketi bulunamadı ({', '.join(errors)}). Elle kurulum: {LLAMA_RELEASES_PAGE} "
            "adresinden 'llama-…-bin-win-vulkan-x64.zip' (ekran kartı) ve 'llama-…-bin-win-cpu-x64.zip' dosyalarını "
            "indirip İndirilenler klasöründe bırakın, sonra 'Klasörleri tara' düğmesine basın.")
    return engine_info()


def start_engine_download() -> dict:
    job = _job("engine", "llama.cpp yerel AI motoru")

    async def run():
        try:
            await download_engine(job=job)
            job["status"] = "tamamlandı"
        except Exception as e:  # noqa
            job["status"], job["error"] = "hata", str(e)
        await bus.emit("job", job=job_public(job))
    asyncio.create_task(run())
    return job_public(job)
