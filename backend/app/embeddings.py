"""Aşama 5: Yerel embedding (bge-m3, çok dilli) + vektör arama.

İkinci, küçük bir llama-server süreci --embedding modunda çalışır (CPU, ~0.5 GB RAM). Ollama'da 'bge-m3' varsa o da kullanılır.
Vektörler SQLite içinde float32 BLOB olarak saklanır; arama numpy kosinüs benzerliğiyle yapılır (internetsiz).
"""
from __future__ import annotations

import asyncio
import os
import subprocess
import time
from pathlib import Path

import httpx
import numpy as np

from . import model_manager as mm
from .config import get_settings, load_machine
from .db import db
from .engine import OLLAMA_URL, _free_port
from .events import bus
from .hardware import NO_WINDOW
from .paths import DIRS

EMB = mm.CATALOG["embedding"]


def find_model() -> Path | None:
    for d in mm.model_dirs():
        p = d / EMB["file"]
        if p.exists() and p.stat().st_size > 1024 * 1024:
            return p
    return None


class Embedder:
    def __init__(self) -> None:
        self.proc: subprocess.Popen | None = None
        self.base: str | None = None
        self.backend: str | None = None
        self.status = "kapalı"
        self.error: str | None = None
        self.lock = asyncio.Lock()
        self.version = 0          # vektörler değiştikçe artar (önbellek geçersiz kılma)
        self._cache: dict[str, tuple[int, np.ndarray, np.ndarray]] = {}

    def info(self) -> dict:
        return {"status": self.status, "backend": self.backend, "error": self.error,
                "model_file": bool(find_model()), "model": EMB["name"]}

    @property
    def ready(self) -> bool:
        return self.status == "hazır"

    async def start(self) -> bool:
        async with self.lock:
            if self.ready:
                return True
            if not get_settings().get("embedding_enabled", True):
                self.status = "kapalı"
                return False
            ext = os.environ.get("AI_OFFICE_EMBED_URL")
            if ext:
                self.base, self.backend, self.status = ext.rstrip("/"), "harici-yerel", "hazır"
                return True
            path = find_model()
            exe = mm.find_server("cpu") or mm.find_server("vulkan")
            if path and exe:
                port = _free_port(8090)
                threads = max(1, min((load_machine().get("hardware") or {}).get("cores_physical", 4) // 2, 4))
                cmd = [str(exe), "-m", str(path), "--embedding", "--host", "127.0.0.1", "--port", str(port),
                       "-c", "2048", "-b", "2048", "-ub", "2048", "-t", str(threads), "-ngl", "0"]
                log = open(DIRS["logs"] / "embedding.log", "ab")
                self.proc = subprocess.Popen(cmd, stdout=log, stderr=subprocess.STDOUT, cwd=str(exe.parent),
                                             creationflags=NO_WINDOW)
                base = f"http://127.0.0.1:{port}"
                async with httpx.AsyncClient(timeout=3) as c:
                    for _ in range(120):
                        if self.proc.poll() is not None:
                            break
                        try:
                            if (await c.get(base + "/health")).status_code == 200:
                                self.base, self.backend, self.status = base, "llama.cpp", "hazır"
                                await bus.emit("embedder", embedder=self.info())
                                return True
                        except Exception:
                            pass
                        await asyncio.sleep(1)
                self.error = "llama.cpp embedding sunucusu başlatılamadı (logs/embedding.log)"
                self.stop_proc()
            # Ollama yedeği
            try:
                async with httpx.AsyncClient(timeout=3) as c:
                    tags = [m["name"] for m in (await c.get(OLLAMA_URL + "/api/tags")).json().get("models", [])]
                if any(t.startswith(EMB.get("ollama", "bge-m3")) for t in tags):
                    self.base, self.backend, self.status = OLLAMA_URL, "ollama", "hazır"
                    return True
            except Exception:
                pass
            self.status = "yok"
            self.error = self.error or "Embedding modeli yok (Bilgi Bankası > Anlamsal arama modelini indir)."
            await bus.emit("embedder", embedder=self.info())
            return False

    def stop_proc(self) -> None:
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=5)
            except Exception:
                self.proc.kill()
        self.proc = None

    async def stop(self) -> None:
        self.stop_proc()
        self.status = "kapalı"
        self.base = None

    async def embed(self, texts: list[str]) -> np.ndarray:
        if not self.ready and not await self.start():
            raise RuntimeError(self.error or "Embedding hazır değil")
        out: list[list[float]] = []
        async with httpx.AsyncClient(timeout=httpx.Timeout(10, read=300)) as c:
            for i in range(0, len(texts), 16):
                batch = [t[:6000] for t in texts[i:i + 16]]
                if self.backend == "ollama":
                    r = await c.post(self.base + "/api/embed", json={"model": EMB.get("ollama", "bge-m3"), "input": batch})
                    r.raise_for_status()
                    out += r.json()["embeddings"]
                else:
                    r = await c.post(self.base + "/v1/embeddings", json={"input": batch, "model": "bge-m3"})
                    r.raise_for_status()
                    data = sorted(r.json()["data"], key=lambda d: d.get("index", 0))
                    out += [d["embedding"] for d in data]
        arr = np.asarray(out, dtype=np.float32)
        norms = np.linalg.norm(arr, axis=1, keepdims=True)
        return arr / np.maximum(norms, 1e-9)

    # -------------------------------------------------------------- indeksleme
    async def index_pending(self, limit: int = 256) -> int:
        if not self.ready:
            return 0
        done = 0
        rows = db.query("SELECT k.rowid AS id, k.doc_id, k.content FROM kb_fts k LEFT JOIN kb_vec v ON v.chunk_id=k.rowid "
                        "WHERE v.chunk_id IS NULL LIMIT ?", (limit,))
        if rows:
            vecs = await self.embed([r["content"] for r in rows])
            for r, v in zip(rows, vecs):
                db.execute("INSERT OR REPLACE INTO kb_vec(chunk_id, doc_id, vec) VALUES(?,?,?)", (r["id"], r["doc_id"], v.tobytes()))
            done += len(rows)
        mrows = db.query("SELECT m.id, m.content FROM memory m LEFT JOIN mem_vec v ON v.mem_id=m.id WHERE v.mem_id IS NULL LIMIT ?", (limit,))
        if mrows:
            vecs = await self.embed([r["content"] for r in mrows])
            for r, v in zip(mrows, vecs):
                db.execute("INSERT OR REPLACE INTO mem_vec(mem_id, vec) VALUES(?,?)", (r["id"], v.tobytes()))
            done += len(mrows)
        if done:
            self.version += 1
        return done

    def pending_count(self) -> int:
        a = db.one("SELECT COUNT(*) c FROM kb_fts k LEFT JOIN kb_vec v ON v.chunk_id=k.rowid WHERE v.chunk_id IS NULL")["c"]
        b = db.one("SELECT COUNT(*) c FROM memory m LEFT JOIN mem_vec v ON v.mem_id=m.id WHERE v.mem_id IS NULL")["c"]
        return a + b

    def _matrix(self, kind: str) -> tuple[np.ndarray, np.ndarray]:
        cached = self._cache.get(kind)
        if cached and cached[0] == self.version:
            return cached[1], cached[2]
        if kind == "kb":
            rows = db.query("SELECT chunk_id AS id, vec FROM kb_vec")
        else:
            rows = db.query("SELECT mem_id AS id, vec FROM mem_vec")
        if not rows:
            ids, mat = np.zeros(0, dtype=np.int64), np.zeros((0, 1), dtype=np.float32)
        else:
            ids = np.asarray([r["id"] for r in rows], dtype=np.int64)
            mat = np.vstack([np.frombuffer(r["vec"], dtype=np.float32) for r in rows])
        self._cache[kind] = (self.version, ids, mat)
        return ids, mat

    async def search(self, kind: str, query: str, k: int = 10) -> list[tuple[int, float]]:
        if not self.ready:
            return []
        ids, mat = self._matrix(kind)
        if not len(ids):
            return []
        q = (await self.embed([query]))[0]
        if mat.shape[1] != q.shape[0]:
            return []
        scores = mat @ q
        top = np.argsort(-scores)[:k]
        return [(int(ids[i]), float(scores[i])) for i in top]

    def invalidate(self) -> None:
        self.version += 1


embedder = Embedder()


def rrf(*lists: list[int], k: int = 60) -> list[int]:
    """Reciprocal Rank Fusion: anahtar kelime ve vektör sonuçlarını birleştirir."""
    score: dict[int, float] = {}
    for lst in lists:
        for rank, item in enumerate(lst):
            score[item] = score.get(item, 0) + 1 / (k + rank + 1)
    return [i for i, _ in sorted(score.items(), key=lambda x: -x[1])]


async def download_model() -> dict:
    job = mm._job("model", EMB["name"])

    async def run():
        try:
            dest = mm.DIRS["models"] / EMB["file"]
            await mm.download_file(EMB["url"], dest, mm._progress_cb(job), job["cancel"])
            job["status"] = "tamamlandı"
            await embedder.start()
        except Exception as e:  # noqa
            job["status"], job["error"] = "hata", str(e)
        await bus.emit("job", job=mm.job_public(job))
    asyncio.create_task(run())
    return mm.job_public(job)
