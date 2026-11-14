"""Ajan kayıt defteri: hazır ajanlar + kullanıcının oluşturduğu ajanlar (agent_profiles/*.json, USB'de taşınır)."""
from __future__ import annotations

import json
import re

from ..config import get_settings, update_settings
from ..paths import DIRS
from .catalog import builtin_agents, system_prompt

PROFILES = DIRS["agent_profiles"]


def _custom() -> list[dict]:
    out = []
    for f in sorted(PROFILES.glob("*.json")):
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
            d["builtin"] = False
            out.append(d)
        except Exception:
            continue
    return out


def all_agents() -> list[dict]:
    agents = {a["id"]: a for a in builtin_agents()}
    for c in _custom():
        agents[c["id"]] = c
    hired = set(get_settings()["hired_agents"])
    return [{**a, "hired": a["id"] in hired} for a in agents.values()]


def get(agent_id: str) -> dict | None:
    return next((a for a in all_agents() if a["id"] == agent_id), None)


def hired() -> list[dict]:
    return [a for a in all_agents() if a["hired"]]


def hire(ids: list[str]) -> list[str]:
    valid = {a["id"] for a in all_agents()}
    cur = get_settings()["hired_agents"]
    for i in ids:
        if i in valid and i not in cur:
            cur.append(i)
    update_settings(hired_agents=cur)
    return cur


def set_team(ids: list[str]) -> list[str]:
    valid = {a["id"] for a in all_agents()}
    team = ["ceo"] + [i for i in ids if i in valid and i != "ceo"]
    update_settings(hired_agents=team)
    return team


def fire(agent_id: str) -> list[str]:
    if agent_id == "ceo":
        raise ValueError("CEO ajanı ofisten çıkarılamaz.")
    cur = [i for i in get_settings()["hired_agents"] if i != agent_id]
    update_settings(hired_agents=cur)
    return cur


def slug(text: str) -> str:
    tr = str.maketrans("çğıöşüÇĞİÖŞÜ ", "cgiosuCGIOSU_")
    s = re.sub(r"[^a-z0-9_]", "", text.translate(tr).lower())
    return s or "ajan"


def create_custom(data: dict) -> dict:
    name = data.get("name", "").strip() or "Yeni Ajan"
    title = data.get("title", "").strip() or "Uzman"
    aid = "ozel_" + slug(data.get("id") or title)
    expertise = data.get("expertise", "").strip()
    duty = data.get("duty", "").strip()
    from ..tools.base import TOOLS
    tools = [t for t in data.get("tools", []) if t in TOOLS]
    agent = {
        "id": aid, "name": name, "title": title, "category": "Özel",
        "department": data.get("department") or "Ortak Çalışma Alanı",
        "avatar": data.get("avatar") or "🧑", "color": data.get("color") or "#14b8a6",
        "expertise": expertise, "duty": duty,
        "system_prompt": data.get("system_prompt") or system_prompt(name, title, expertise, duty),
        "tools": tools, "permission": max(1, min(3, int(data.get("permission", 1)))),
        "memory_access": data.get("memory_access", "own+shared"),
        "can_talk_to": data.get("can_talk_to", "all"),
        "folders": [f for f in data.get("folders", []) if isinstance(f, str)],
    }
    PROFILES.mkdir(parents=True, exist_ok=True)
    (PROFILES / f"{aid}.json").write_text(json.dumps(agent, ensure_ascii=False, indent=2), encoding="utf-8")
    hire([aid])
    return agent


def delete_custom(agent_id: str) -> None:
    f = PROFILES / f"{agent_id}.json"
    if not f.exists():
        raise ValueError("Yalnızca özel ajanlar silinebilir.")
    f.unlink()
    try:
        fire(agent_id)
    except ValueError:
        pass
