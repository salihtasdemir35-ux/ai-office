"""Yetki ve güvenlik: izinli klasörler, kullanıcı onayı gerektiren işlemler, kapatma anahtarları."""
from __future__ import annotations

import asyncio
import time
import uuid
from pathlib import Path

from .config import get_settings
from .events import bus
from .paths import workspace

LEVEL_NAMES = {1: "Okuma", 2: "Düzenleme", 3: "İşlem"}
pending: dict[str, dict] = {}


class SecurityError(PermissionError):
    pass


def allowed_roots() -> list[Path]:
    roots = [workspace().resolve()]
    for f in get_settings().get("allowed_folders", []):
        try:
            p = Path(f).expanduser().resolve()
            if p.exists():
                roots.append(p)
        except Exception:
            continue
    return roots


def resolve_path(path_str: str, must_exist: bool = False) -> Path:
    """Göreli yollar çalışma klasörüne göre çözülür. İzinli klasör dışına çıkış engellenir."""
    if not get_settings().get("files_enabled", True):
        raise SecurityError("Dosya erişimi kullanıcı tarafından kapatıldı.")
    raw = (path_str or ".").strip().strip('"')
    p = Path(raw).expanduser()
    if not p.is_absolute():
        p = workspace() / p
    p = p.resolve()
    for root in allowed_roots():
        if p == root or root in p.parents:
            if must_exist and not p.exists():
                raise FileNotFoundError(f"Bulunamadı: {p}")
            return p
    raise SecurityError(f"Bu klasöre erişim izni yok: {p}. İzinli klasörler: " +
                        ", ".join(str(r) for r in allowed_roots()))


def unique_path(p: Path) -> Path:
    """Üzerine yazmayı önler: dosya varsa _2, _3 ekler."""
    if not p.exists():
        return p
    i = 2
    while True:
        cand = p.with_name(f"{p.stem}_{i}{p.suffix}")
        if not cand.exists():
            return cand
        i += 1


async def request_approval(agent_id: str, action: str, detail: str, task_id: str | None = None,
                           timeout: float = 900) -> bool:
    aid = uuid.uuid4().hex[:8]
    fut: asyncio.Future = asyncio.get_running_loop().create_future()
    pending[aid] = {"id": aid, "agent": agent_id, "action": action, "detail": detail,
                    "task_id": task_id, "ts": time.time(), "future": fut}
    await bus.emit("approval_request", approval=public(pending[aid]))
    try:
        return bool(await asyncio.wait_for(fut, timeout))
    except asyncio.TimeoutError:
        return False
    finally:
        pending.pop(aid, None)
        await bus.emit("approval_closed", id=aid)


def resolve_approval(aid: str, approve: bool) -> bool:
    item = pending.get(aid)
    if not item or item["future"].done():
        return False
    item["future"].set_result(approve)
    return True


def public(item: dict) -> dict:
    return {k: v for k, v in item.items() if k != "future"}


def cancel_all_approvals() -> None:
    for item in list(pending.values()):
        if not item["future"].done():
            item["future"].set_result(False)
