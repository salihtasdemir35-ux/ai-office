"""Yerel AI motoru yöneticisi.

Öncelik: paket içindeki llama.cpp (llama-server, Vulkan GPU veya CPU) -> bilgisayarda kurulu Ollama.
Her iki motor da OpenAI uyumlu /v1/chat/completions sunar; dış API yoktur, her şey localhost.
Tek model, tüm ajan rolleri için paylaşılır; çağrılar kuyrukta (Semaphore) sıraya alınır.
"""
from __future__ import annotations

import asyncio
import os
import socket
import subprocess
import time
from pathlib import Path

import httpx

from . import model_manager as mm
from .config import get_settings, load_machine, save_machine
from .events import bus
from .hardware import NO_WINDOW, detect
from .paths import DIRS

OLLAMA_URL = "http://127.0.0.1:11434"


def _free_port(preferred: int = 8081) -> int:
    for port in [preferred] + list(range(8082, 8150)):
        with socket.socket() as s:
            try:
                s.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    raise RuntimeError("Boş port bulunamadı")


class Engine:
    def __init__(self) -> None:
        self.proc: subprocess.Popen | None = None
        self.backend: str | None = None
        self.base: str | None = None
        self.model_name: str | None = None
        self.model_id: str | None = None
        self.variant: str | None = None
        self.ctx: int = 4096
        self.status = "durdu"
        self.error: str | None = None
        self.sem = asyncio.Semaphore(1)
        self.lock = asyncio.Lock()
        self.waiting = 0
        self.calls = 0
        self.last_speed: float | None = None

    def info(self) -> dict:
        return {"status": self.status, "backend": self.backend, "model_id": self.model_id,
                "model_name": self.model_name, "variant": self.variant, "ctx": self.ctx,
                "error": self.error, "queue": self.waiting, "calls": self.calls,
                "tokens_per_sec": self.last_speed,
                "llama_vulkan": bool(mm.find_server("vulkan")), "llama_cpu": bool(mm.find_server("cpu")),
                "local_models": mm.local_models()}

    async def _set(self, status: str, error: str | None = None) -> None:
        self.status, self.error = status, error
        await bus.emit("engine", engine=self.info())

    # ------------------------------------------------------------ başlatma
    async def start(self, model_id: str | None = None) -> bool:
        async with self.lock:
            if self.status == "hazir" and (model_id is None or model_id == self.model_id):
                return True
            await self._stop_proc()
            await self._set("baslatiliyor")
            settings = get_settings()
            machine = load_machine()
            rec = machine.get("recommendation")
            if not rec:
                rec = mm.recommend(detect())
                machine["recommendation"] = rec
                save_machine(machine)
            errors: list[str] = []

            # 0) Harici yerel OpenAI uyumlu sunucu (ör. LM Studio) – isteğe bağlı
            ext = os.environ.get("AI_OFFICE_LLM_URL")
            if ext:
                if await self._probe_openai(ext):
                    self.backend, self.base, self.model_name = "harici-yerel", ext.rstrip("/"), "local"
                    self.model_id = "harici"
                    await self._set("hazir")
                    return True
                errors.append(f"Harici sunucuya ulaşılamadı: {ext}")

            wanted = model_id or settings.get("model_override") or machine.get("model_id") or rec["model_id"]
            pref = settings.get("engine_preference", "auto")

            # 1) Paket içindeki llama.cpp
            if pref in ("auto", "llamacpp"):
                import psutil
                total_ram = psutil.virtual_memory().total / 1024**3
                candidates = [wanted] + [m for m in ("qwen2.5-7b", "qwen2.5-3b", "qwen2.5-1.5b", "qwen2.5-14b")
                                         if m != wanted]
                # RAM koruması: bu bilgisayarın belleğini aşacak modeli yükleme (USB başka PC'ye takıldığında önemli)
                fit = [m for m in candidates if mm.get_model(m)["ram_gb"] <= total_ram - 1.0]
                if wanted not in fit and fit:
                    errors.append(f"{wanted} bu bilgisayarın RAM'i ({total_ram:.0f} GB) için büyük; daha küçük model seçildi.")
                candidates = fit or candidates[-2:]
                path = None
                for mid in candidates:
                    path = mm.find_local(mid)
                    if path:
                        if mid != wanted:
                            errors.append(f"{wanted} bulunamadı, mevcut {mid} kullanılıyor.")
                        wanted = mid
                        break
                if not path:
                    errors.append("Yerel model dosyası yok (Kurulum > AI motoru adımından indirin).")
                else:
                    m = mm.get_model(wanted)
                    order = ["vulkan", "cpu"] if rec.get("gpu_mode") else ["cpu", "vulkan"]
                    for variant in order:
                        exe = mm.find_server(variant)
                        if not exe:
                            continue
                        ngl = rec.get("ngl", 0) if variant == "vulkan" and rec.get("gpu_mode") else 0
                        ok, err = await self._start_llama(exe, path, variant, ngl, m["ctx"], rec.get("threads", 4))
                        if ok:
                            self.model_id, self.model_name = wanted, m["name"]
                            machine.update({"model_id": wanted, "variant": variant, "last_ok": time.time()})
                            save_machine(machine)
                            await self._set("hazir")
                            return True
                        errors.append(f"llama.cpp ({variant}) başlatılamadı: {err}")
                    if not (mm.find_server("vulkan") or mm.find_server("cpu")):
                        errors.append("llama.cpp motoru paket içinde yok (engines klasörü boş).")

            # 2) Bilgisayarda kurulu Ollama
            if pref in ("auto", "ollama"):
                tag = await self._ollama_model(wanted)
                if tag:
                    self.backend, self.base, self.model_name = "ollama", OLLAMA_URL, tag
                    self.model_id, self.variant, self.ctx = wanted, "ollama", mm.get_model(wanted)["ctx"] if mm.get_model(wanted) else 4096
                    await self._set("hazir")
                    return True
                errors.append("Ollama çalışmıyor veya uygun model yüklü değil.")

            await self._set("hata", " | ".join(errors))
            return False

    async def _probe_openai(self, base: str) -> bool:
        try:
            async with httpx.AsyncClient(timeout=3) as c:
                r = await c.get(base.rstrip("/") + "/v1/models")
                return r.status_code == 200
        except Exception:
            return False

    async def _ollama_model(self, wanted: str) -> str | None:
        try:
            async with httpx.AsyncClient(timeout=3) as c:
                r = await c.get(OLLAMA_URL + "/api/tags")
                names = [m["name"] for m in r.json().get("models", [])]
        except Exception:
            return None
        m = mm.get_model(wanted)
        if m and any(n.startswith(m["ollama"]) for n in names):
            return next(n for n in names if n.startswith(m["ollama"]))
        chat = [n for n in names if "embed" not in n]
        return chat[0] if chat else None

    async def _start_llama(self, exe: Path, model: Path, variant: str, ngl: int, ctx: int, threads: int):
        port = _free_port()
        log = open(DIRS["logs"] / "engine.log", "ab")
        cmd = [str(exe), "-m", str(model), "--host", "127.0.0.1", "--port", str(port),
               "-c", str(ctx), "-t", str(threads), "-ngl", str(ngl), "--parallel", "1"]
        try:
            self.proc = subprocess.Popen(cmd, stdout=log, stderr=subprocess.STDOUT, cwd=str(exe.parent),
                                         creationflags=NO_WINDOW)
        except Exception as e:  # noqa
            return False, str(e)
        base = f"http://127.0.0.1:{port}"
        deadline = time.time() + 240  # USB'den büyük model yüklemek zaman alabilir
        async with httpx.AsyncClient(timeout=3) as c:
            while time.time() < deadline:
                if self.proc.poll() is not None:
                    return False, f"süreç kapandı (kod {self.proc.returncode}); ayrıntı logs/engine.log"
                try:
                    r = await c.get(base + "/health")
                    if r.status_code == 200:
                        self.backend, self.base, self.variant, self.ctx = "llama.cpp", base, variant, ctx
                        return True, None
                except Exception:
                    pass
                await asyncio.sleep(1)
        await self._stop_proc()
        return False, "zaman aşımı"

    async def _stop_proc(self) -> None:
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=8)
            except Exception:
                self.proc.kill()
        self.proc = None

    async def stop(self) -> None:
        async with self.lock:
            await self._stop_proc()
            self.backend = self.base = None
            await self._set("durdu")

    # ------------------------------------------------------------ çağrı
    async def chat(self, messages: list[dict], max_tokens: int = 900, temperature: float = 0.3,
                   json_mode: bool = False) -> str:
        if self.status != "hazir":
            ok = await self.start()
            if not ok:
                raise RuntimeError(f"Yerel AI motoru hazır değil: {self.error}")
        self.waiting += 1
        acquired = False
        await bus.emit("engine", engine=self.info())
        try:
            async with self.sem:
                self.waiting -= 1
                acquired = True
                payload = {"model": self.model_name, "messages": messages, "temperature": temperature,
                           "max_tokens": max_tokens, "stream": False}
                if json_mode:
                    payload["response_format"] = {"type": "json_object"}
                t0 = time.time()
                async with httpx.AsyncClient(timeout=httpx.Timeout(15.0, read=900.0)) as c:
                    r = await c.post(self.base + "/v1/chat/completions", json=payload)
                    if r.status_code >= 400 and json_mode:
                        payload.pop("response_format", None)
                        r = await c.post(self.base + "/v1/chat/completions", json=payload)
                    r.raise_for_status()
                    data = r.json()
                self.calls += 1
                toks = (data.get("usage") or {}).get("completion_tokens")
                if toks:
                    self.last_speed = round(toks / max(time.time() - t0, 0.01), 1)
                return data["choices"][0]["message"]["content"] or ""
        except httpx.HTTPError as e:
            if self.proc and self.proc.poll() is not None:
                await self._set("hata", "Motor beklenmedik şekilde kapandı")
            raise RuntimeError(f"Model çağrısı başarısız: {e}") from e
        finally:
            if not acquired:
                self.waiting = max(0, self.waiting - 1)
            await bus.emit("engine", engine=self.info())


engine = Engine()
