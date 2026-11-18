"""Motor sorun giderme: Windows çökme kodlarını açıklar, güncel Visual C++ çalışma zamanını
llama.cpp klasörüne kopyalar (yönetici yetkisi gerekmez), model dosyalarını doğrular ve tanılama raporu üretir."""
from __future__ import annotations

import os
import shutil
import struct
import subprocess
from pathlib import Path

from .hardware import NO_WINDOW
from .paths import DIRS

VCRT_DIR = DIRS["dependencies"] / "vcrt"
VCRT_DLLS = ["msvcp140.dll", "msvcp140_1.dll", "msvcp140_2.dll", "msvcp140_atomic_wait.dll",
             "msvcp140_codecvt_ids.dll", "vcruntime140.dll", "vcruntime140_1.dll", "vcruntime140_threads.dll",
             "vcomp140.dll", "concrt140.dll"]

CODES = {
    0xC0000005: ("Bellek erişim ihlali", "Genellikle bilgisayardaki eski Visual C++ çalışma zamanı (msvcp140.dll), "
                 "eksik inmiş model dosyası veya yetersiz bellekten kaynaklanır."),
    0xC0000135: ("Gerekli DLL bulunamadı", "Visual C++ çalışma zamanı eksik."),
    0xC000001D: ("İşlemci komutu desteklenmiyor", "İşlemci AVX/AVX2 desteklemiyor olabilir."),
    0xC0000409: ("Program kendini durdurdu", "Model dosyası bozuk veya bağlam/bellek ayarı aşıldı."),
    0xC0000017: ("Bellek yetersiz", "Daha küçük bir model seçin."),
    0xC000007B: ("Uyumsuz DLL (32/64 bit)", "Klasörde yanlış mimariye ait DLL var."),
}


def explain(code: int | None) -> str:
    if code is None:
        return ""
    c = code & 0xFFFFFFFF
    if c in CODES:
        t, d = CODES[c]
        return f"{t} (0x{c:08X}): {d}"
    return f"çıkış kodu {code}"


def is_access_violation(code: int | None) -> bool:
    return code is not None and (code & 0xFFFFFFFF) in (0xC0000005, 0xC0000135, 0xC0000409, 0xC000007B)


def install_vc_runtime(target: Path) -> list[str]:
    """Paketteki güncel VC++ DLL'lerini llama-server.exe'nin yanına kopyalar (uygulama yerel dağıtım)."""
    copied = []
    if not VCRT_DIR.exists():
        return copied
    for name in VCRT_DLLS:
        src = VCRT_DIR / name
        dst = target / name
        if not src.exists():
            continue
        try:
            if not dst.exists() or dst.stat().st_size != src.stat().st_size:
                shutil.copy2(src, dst)
                copied.append(name)
        except OSError:
            continue
    return copied


def vc_runtime_ok(target: Path) -> bool:
    return all((target / n).exists() for n in ("msvcp140.dll", "vcruntime140.dll", "vcruntime140_1.dll"))


def system_msvcp_version() -> str | None:
    if os.name != "nt":
        return None
    dll = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "msvcp140.dll"
    if not dll.exists():
        return "yok"
    try:
        ps = f"(Get-Item '{dll}').VersionInfo.FileVersion"
        r = subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True, text=True,
                           timeout=10, creationflags=NO_WINDOW)
        return r.stdout.strip() or "?"
    except Exception:
        return "?"


# ------------------------------------------------------------------ model doğrulama
def check_model(path: Path, expected_gb: float | None = None) -> dict:
    """GGUF başlığını okur ve dosya boyutunu katalogla karşılaştırır (yarım inmiş dosya llama.cpp'yi çökertir)."""
    res = {"path": str(path), "ok": True, "size_gb": 0.0, "problems": []}
    try:
        size = path.stat().st_size
        res["size_gb"] = round(size / 1024**3, 2)
        with open(path, "rb") as f:
            head = f.read(24)
        if head[:4] != b"GGUF":
            res["problems"].append("GGUF imzası yok (dosya model değil veya bozuk)")
        else:
            version, tensors, kvs = struct.unpack("<IQQ", head[4:24])
            res.update({"gguf_version": version, "tensors": tensors})
            if version not in (2, 3) or tensors == 0 or tensors > 100000 or kvs > 100000:
                res["problems"].append("GGUF başlığı geçersiz")
        if expected_gb:
            ratio = size / (expected_gb * 1024**3)
            if ratio < 0.97:
                res["problems"].append(f"Dosya eksik: {res['size_gb']} GB, beklenen ≈{expected_gb} GB (indirme yarım kalmış)")
        part = path.with_name(path.name + ".part")
        if part.exists():
            res["problems"].append("Yarım kalmış .part dosyası duruyor")
    except OSError as e:
        res["problems"].append(f"Okunamadı: {e}")
    res["ok"] = not res["problems"]
    return res


def run_version(exe: Path) -> dict:
    """llama-server --version: model olmadan programın kendisi çalışıyor mu?"""
    try:
        r = subprocess.run([str(exe), "--version"], capture_output=True, text=True, timeout=30,
                           cwd=str(exe.parent), creationflags=NO_WINDOW, encoding="utf-8", errors="ignore")
        out = (r.stdout + r.stderr).strip()
        return {"ok": r.returncode == 0, "code": r.returncode, "explain": explain(r.returncode) if r.returncode else "",
                "output": out[-600:]}
    except Exception as e:  # noqa
        return {"ok": False, "code": None, "explain": str(e), "output": ""}


def log_tail(n: int = 2500, start: int = 0) -> str:
    p = DIRS["logs"] / "engine.log"
    try:
        with open(p, "rb") as f:
            f.seek(start)
            data = f.read()
        return data.decode("utf-8", "ignore")[-n:]
    except OSError:
        return ""
