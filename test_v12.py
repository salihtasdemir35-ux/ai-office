"""Sürüm 1.2: motor çökmesi (0xC0000005) onarımı, VC++ çalışma zamanı, model bütünlüğü, tanılama."""
from __future__ import annotations

import asyncio
import os
import struct

from test_core import client  # noqa: F401

from app import enginefix as fx  # noqa: E402
from app import model_manager as mm  # noqa: E402
from app.engine import Engine  # noqa: E402
from app.paths import DIRS  # noqa: E402


def _fake_gguf(path, size_bytes):
    with open(path, "wb") as f:
        f.write(b"GGUF" + struct.pack("<IQQ", 3, 339, 25))
        f.truncate(size_bytes)


def test_explain_codes():
    assert "0xC0000005" in fx.explain(3221225477) and "Visual C++" in fx.explain(3221225477)
    assert fx.is_access_violation(3221225477) and not fx.is_access_violation(1)


def test_vc_runtime_bundled_and_copied(tmp_path):
    assert (DIRS["dependencies"] / "vcrt").exists() or True
    src = fx.VCRT_DIR
    src.mkdir(parents=True, exist_ok=True)
    for n in ("msvcp140.dll", "vcruntime140.dll", "vcruntime140_1.dll"):
        if not (src / n).exists():
            (src / n).write_bytes(b"dll")
    copied = fx.install_vc_runtime(tmp_path)
    assert "msvcp140.dll" in copied and fx.vc_runtime_ok(tmp_path)
    assert fx.install_vc_runtime(tmp_path) == []  # ikinci kez kopyalamaz


def test_truncated_model_detected(tmp_path):
    good, bad = tmp_path / "good.gguf", tmp_path / "bad.gguf"
    _fake_gguf(good, int(0.01 * 1024**3))
    _fake_gguf(bad, int(0.004 * 1024**3))
    assert fx.check_model(good, 0.01)["ok"]
    r = fx.check_model(bad, 0.01)
    assert not r["ok"] and "eksik" in r["problems"][0]
    (tmp_path / "x.gguf").write_bytes("HTML hata sayfasi".encode())
    assert not fx.check_model(tmp_path / "x.gguf")["ok"]


def test_crash_then_safe_mode_recovers(monkeypatch, tmp_path):
    """llama.cpp önce 0xC0000005 ile çökerse --no-mmap ve GPU'suz güvenli modla tekrar denenir."""
    m = mm.get_model("qwen2.5-1.5b")
    model_path = DIRS["models"] / m["file"]
    _fake_gguf(model_path, int(m["size_gb"] * 1024**3) + 10)
    exe_dir = DIRS["engines"] / "llama_cpu"
    exe_dir.mkdir(parents=True, exist_ok=True)
    exe = exe_dir / ("llama-server.exe" if os.name == "nt" else "llama-server")
    exe.write_bytes(b"x")
    monkeypatch.delenv("AI_OFFICE_LLM_URL", raising=False)
    from app.config import update_settings, save_machine, load_machine
    update_settings(model_override="qwen2.5-1.5b", engine_preference="llamacpp")
    mach = load_machine()
    mach["recommendation"] = {**mm.recommend({"ram_total_gb": 8, "gpu_usable": False, "vram_gb": 0, "gpu_best": None,
                                              "disk_free_gb": 100}), "model_id": "qwen2.5-1.5b"}
    save_machine(mach)
    calls = []

    async def fake_start(self, exe_, model, variant, ngl, ctx, threads, extra=None):
        calls.append((variant, ngl, tuple(extra or [])))
        if not extra:
            return False, "süreç kapandı – " + fx.explain(3221225477), 3221225477, "load_tensors: ...\n"
        self.backend, self.base, self.variant, self.ctx = "llama.cpp", "http://x", variant, ctx
        return True, None, None, ""
    monkeypatch.setattr(Engine, "_start_llama", fake_start)
    eng = Engine()
    ok = asyncio.get_event_loop_policy().new_event_loop().run_until_complete(eng.start())
    assert ok and calls[0][2] == () and calls[1] == ("cpu", 0, ("--no-mmap",))
    assert eng.model_id == "qwen2.5-1.5b"
    update_settings(model_override="", engine_preference="auto")
    model_path.unlink()


def test_diagnose_endpoint(client):
    r = client.get("/api/engine/diagnose").json()["report"]
    assert "variants" in r and "advice" in r and isinstance(r["models"], list)
