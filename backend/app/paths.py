"""Tüm yollar uygulamanın bulunduğu klasöre göre DİNAMİK hesaplanır.

Sabit C:\\ veya D:\\ yolu kullanılmaz; USB'nin sürücü harfi değişse de çalışır.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

# backend/app/paths.py -> kök = iki üst klasör
ROOT: Path = Path(os.environ.get("AI_OFFICE_ROOT") or Path(__file__).resolve().parents[2]).resolve()

_DIR_NAMES = [
    "agent_profiles", "models", "memory", "knowledge_base", "projects", "workspace",
    "database", "logs", "config", "backups", "cache", "exports", "engines", "runtime",
    "tools", "dependencies",
]
DIRS: dict[str, Path] = {name: ROOT / name for name in _DIR_NAMES}
FRONTEND = ROOT / "frontend"
BACKEND = ROOT / "backend"


def ensure_dirs() -> None:
    for p in DIRS.values():
        p.mkdir(parents=True, exist_ok=True)
    (DIRS["config"] / "machines").mkdir(exist_ok=True)
    (DIRS["cache"] / "trash").mkdir(exist_ok=True)


def portable_info() -> dict:
    f = ROOT / "PORTABLE_MODE.json"
    if f.exists():
        try:
            return json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            return {"portable": True}
    return {"portable": False}


def is_portable() -> bool:
    return bool(portable_info().get("portable", False))


def local_appdata() -> Path:
    """Bilgisayara özel (USB'ye taşınmayan) veri klasörü."""
    base = os.environ.get("LOCALAPPDATA")
    if base:
        return Path(base) / "AI_OFFICE"
    return Path.home() / ".local" / "share" / "AI_OFFICE"


def drive_letter() -> str:
    return ROOT.drive or "/"


def workspace() -> Path:
    """Varsayılan çalışma klasörü: AI_OFFICE_WORKSPACE (taşınabilir modda USB üzerinde)."""
    p = DIRS["workspace"] / "AI_OFFICE_WORKSPACE"
    p.mkdir(parents=True, exist_ok=True)
    return p
