"""Ayarlar (USB ile taşınır) ve bilgisayara özel donanım ayarları (her PC için ayrı)."""
from __future__ import annotations

import copy
import hashlib
import json
import platform
import threading
import uuid
from pathlib import Path

from .paths import DIRS

DEFAULTS: dict = {
    "setup_complete": False,
    "mode": "portable",            # portable | installed
    "model_location": "usb",       # usb | local | hybrid
    "allowed_folders": [],         # kullanıcının izin verdiği ek klasörler
    "internet_enabled": True,
    "files_enabled": True,
    "shell_enabled": False,        # keyfi shell erişimi varsayılan KAPALI
    "agents_paused": False,
    "hired_agents": ["ceo"],
    "port": 8765,
    "engine_preference": "auto",   # auto | llamacpp | ollama
    "model_override": "",          # boşsa donanıma göre otomatik
    "max_steps": 6,
    "max_tool_iters": 4,
    "max_messages_per_task": 80,
    "memory_enabled": True,
    "code_exec_enabled": False,    # Python kodu çalıştırma (her seferinde onay ister)
    "max_parallel_tasks": 1,       # aynı anda çalışan görev (düşük donanımda 1)
    "smtp": {},                    # {host, port, user, password, from}
    "embedding_enabled": True,     # bge-m3 varsa anlamsal arama
}

_lock = threading.RLock()
_SETTINGS_FILE = DIRS["config"] / "settings.json"


def _read(path: Path, default: dict) -> dict:
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        pass
    return copy.deepcopy(default)


def _write(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def get_settings() -> dict:
    with _lock:
        data = copy.deepcopy(DEFAULTS)
        data.update(_read(_SETTINGS_FILE, {}))
        if "ceo" not in data["hired_agents"]:
            data["hired_agents"].insert(0, "ceo")
        return data


def update_settings(**changes) -> dict:
    with _lock:
        data = get_settings()
        data.update(changes)
        _write(_SETTINGS_FILE, data)
        return data


def machine_id() -> str:
    node = uuid.getnode()
    if (node >> 40) & 1:  # MAC okunamadı → rastgele değer; sadece bilgisayar adını kullan
        node = 0
    raw = f"{platform.node()}-{node}"
    return hashlib.sha1(raw.encode()).hexdigest()[:12]


def machine_file() -> Path:
    return DIRS["config"] / "machines" / f"{machine_id()}.json"


def load_machine() -> dict:
    return _read(machine_file(), {})


def save_machine(data: dict) -> None:
    data = dict(data)
    data["machine_id"] = machine_id()
    data["hostname"] = platform.node()
    _write(machine_file(), data)


def list_machines() -> list[dict]:
    out = []
    for f in sorted((DIRS["config"] / "machines").glob("*.json")):
        d = _read(f, {})
        out.append({
            "machine_id": d.get("machine_id", f.stem),
            "hostname": d.get("hostname", "?"),
            "tier_label": d.get("recommendation", {}).get("tier_label"),
            "model_id": d.get("model_id"),
            "last_seen": d.get("last_seen"),
            "current": f.stem == machine_id(),
        })
    return out
