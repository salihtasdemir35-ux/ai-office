"""Gerçek zamanlı olay yayını (WebSocket) ve ajan durumları."""
from __future__ import annotations

import asyncio
import json
import time

from fastapi import WebSocket

AGENT_STATUSES = [
    "Müsait", "Görev bekliyor", "Düşünüyor", "Araştırıyor", "Yazıyor", "Dosya inceliyor",
    "Toplantıda", "Başka ajanla görüşüyor", "Kontrol yapıyor", "Tamamlandı", "Hata",
]


class EventBus:
    def __init__(self) -> None:
        self.clients: set[WebSocket] = set()
        self.agent_state: dict[str, dict] = {}

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        self.clients.add(ws)
        await ws.send_text(json.dumps({"type": "agent_states", "states": self.agent_state}, ensure_ascii=False))

    def disconnect(self, ws: WebSocket) -> None:
        self.clients.discard(ws)

    async def emit(self, type_: str, **data) -> None:
        msg = json.dumps({"type": type_, "ts": time.time(), **data}, ensure_ascii=False, default=str)
        dead = []
        for ws in list(self.clients):
            try:
                await ws.send_text(msg)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.clients.discard(ws)

    def emit_nowait(self, type_: str, **data) -> None:
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(self.emit(type_, **data))
        except RuntimeError:
            pass

    async def set_agent(self, agent_id: str, status: str, bubble: str | None = None,
                        task_id: str | None = None, with_: str | None = None, zone: str = "desk") -> None:
        st = self.agent_state.setdefault(agent_id, {})
        st.update({"status": status, "zone": zone, "with": with_, "updated": time.time()})
        if bubble is not None:
            st["bubble"] = bubble[:160]
        if task_id is not None:
            st["task_id"] = task_id
        if status in ("Müsait",):
            st["task_id"] = None
            st["with"] = None
        await self.emit("agent_state", agent_id=agent_id, state=st)


bus = EventBus()
