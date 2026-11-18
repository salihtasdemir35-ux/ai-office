"""Ajan kayıt defteri: hazır ajanlar + kullanıcının oluşturduğu ajanlar (agent_profiles/*.json, USB'de taşınır)."""
from __future__ import annotations

import json
import re

from ..config import get_settings, update_settings
from ..paths import DIRS
from .catalog import builtin_agents, system_prompt

PROFILES = DIRS["agent_profiles"]
OVERRIDES = PROFILES / "_overrides.json"   # hazır ajanlara verilen özel ad / avatar
MAX_COPIES = 10
NAME_POOL = ["Ali", "Ayşe", "Mehmet", "Fatma", "Mustafa", "Zehra", "Emre", "Büşra", "Hasan", "Esra", "Yusuf",
             "Merve", "Kaan", "Derya", "Okan", "Pınar", "Serkan", "Tuğba", "Volkan", "Gül", "Cem", "Nur",
             "Arda", "Sibel", "Eren", "Aslı", "Uğur", "Damla", "Berk", "İrem"]


def _overrides() -> dict:
    try:
        return json.loads(OVERRIDES.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _apply_name(agent: dict, name: str | None, avatar: str | None = None) -> dict:
    a = dict(agent)
    if name and name != a["name"]:
        old = a["name"]
        a["name"] = name
        if a.get("system_prompt", "").startswith(f"Sen {old}."):
            a["system_prompt"] = system_prompt(name, a["title"], a.get("expertise", ""), a.get("duty", ""))
        else:
            a["system_prompt"] = a.get("system_prompt", "").replace(old, name)
    if avatar:
        a["avatar"] = avatar
    return a


def _custom(builtins: dict[str, dict]) -> list[dict]:
    out = []
    for f in sorted(PROFILES.glob("*.json")):
        if f.name.startswith("_"):
            continue
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            continue
        base_id = d.get("instance_of")
        if base_id:  # aynı uzmanlıktan ek kişi: temel profili miras alır
            base = builtins.get(base_id)
            if not base:
                continue
            a = _apply_name({**base, "id": d["id"]}, d.get("name"), d.get("avatar"))
            a.update({"instance_of": base_id, "builtin": False, "copy": True})
            out.append(a)
        else:
            d["builtin"] = False
            out.append(d)
    return out


def all_agents() -> list[dict]:
    ov = _overrides()
    builtins = {}
    for a in builtin_agents():
        o = ov.get(a["id"], {})
        builtins[a["id"]] = _apply_name(a, o.get("name"), o.get("avatar"))
    agents = dict(builtins)
    for c in _custom(builtins):
        agents[c["id"]] = c
    hired = set(get_settings()["hired_agents"])
    counts: dict[str, int] = {}
    for a in agents.values():
        base = a.get("instance_of") or a["id"]
        if a["id"] in hired:
            counts[base] = counts.get(base, 0) + 1
    return [{**a, "hired": a["id"] in hired, "team_count": counts.get(a.get("instance_of") or a["id"], 0)}
            for a in agents.values()]


def rename(agent_id: str, name: str, avatar: str | None = None) -> dict:
    name = (name or "").strip()[:40]
    if not name:
        raise ValueError("Ad boş olamaz.")
    a = get(agent_id)
    if not a:
        raise ValueError("Ajan bulunamadı.")
    if a.get("builtin", True) and not a.get("copy"):
        ov = _overrides()
        ov[agent_id] = {**ov.get(agent_id, {}), "name": name, **({"avatar": avatar} if avatar else {})}
        PROFILES.mkdir(parents=True, exist_ok=True)
        OVERRIDES.write_text(json.dumps(ov, ensure_ascii=False, indent=2), encoding="utf-8")
    else:
        f = PROFILES / f"{agent_id}.json"
        d = json.loads(f.read_text(encoding="utf-8"))
        if not d.get("instance_of"):
            d = _apply_name(d, name, avatar)
        else:
            d["name"] = name
            if avatar:
                d["avatar"] = avatar
        f.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")
    return get(agent_id)


def _free_name(used: set[str], base_first: str) -> str:
    for n in NAME_POOL:
        if n not in used and n != base_first:
            return n
    i = 2
    while f"{base_first} {i}" in used:
        i += 1
    return f"{base_first} {i}"


def set_count(base_id: str, count: int, names: list[str] | None = None) -> list[dict]:
    """Bir uzmanlıktan ofiste kaç kişi çalışacağını ayarlar (0–10). Fazlası kopya ajan olarak oluşturulur."""
    agents = all_agents()
    base = next((a for a in agents if a["id"] == base_id and not a.get("copy")), None)
    if not base:
        raise ValueError("Ajan bulunamadı.")
    count = 1 if base_id == "ceo" else max(0, min(MAX_COPIES, int(count)))  # tek CEO
    names = [(n or "").strip()[:40] for n in (names or [])]  # sıra korunur; boş = otomatik ad
    copies = sorted([a for a in agents if a.get("instance_of") == base_id], key=lambda a: a["id"])
    hired_ids = get_settings()["hired_agents"]
    if count == 0:
        for c in copies:
            (PROFILES / f"{c['id']}.json").unlink(missing_ok=True)
        update_settings(hired_agents=[i for i in hired_ids if i != base_id and not i.startswith(base_id + "__")])
        return []
    if base_id not in hired_ids:
        hired_ids.append(base_id)
    for c in copies[count - 1:]:  # fazla kopyaları kaldır
        (PROFILES / f"{c['id']}.json").unlink(missing_ok=True)
        hired_ids = [i for i in hired_ids if i != c["id"]]
    keep = copies[:count - 1]
    used = {a["name"].split(" ")[0] for a in agents} | {a["name"] for a in agents}
    n = 2
    existing_ids = {c["id"] for c in keep}
    PROFILES.mkdir(parents=True, exist_ok=True)
    while len(keep) < count - 1:
        while f"{base_id}__{n}" in existing_ids:
            n += 1
        cid = f"{base_id}__{n}"
        idx = len(keep) + 1
        name = names[idx] if idx < len(names) and names[idx] else _free_name(used, base["name"].split(" ")[0])
        used.add(name)
        (PROFILES / f"{cid}.json").write_text(json.dumps({"id": cid, "instance_of": base_id, "name": name},
                                                          ensure_ascii=False, indent=2), encoding="utf-8")
        keep.append({"id": cid})
        existing_ids.add(cid)
        n += 1
    for c in keep:
        if c["id"] not in hired_ids:
            hired_ids.append(c["id"])
    update_settings(hired_agents=hired_ids)
    if names and names[0]:
        rename(base_id, names[0])
    for i, c in enumerate(keep, start=1):  # mevcut kopyaların adlarını güncelle
        if i < len(names) and names[i]:
            rename(c["id"], names[i])
    return [a for a in all_agents() if a["id"] == base_id or a.get("instance_of") == base_id]


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
    ids = list(ids) + [i for i in get_settings()["hired_agents"] if "__" in i and i.split("__")[0] in ids]
    team = ["ceo"] + [i for i in ids if i in valid and i != "ceo"]
    update_settings(hired_agents=team)
    return team


def fire(agent_id: str) -> list[str]:
    if agent_id == "ceo":
        raise ValueError("CEO ajanı ofisten çıkarılamaz.")
    cur = [i for i in get_settings()["hired_agents"] if i != agent_id]
    update_settings(hired_agents=cur)
    if "__" in agent_id:
        (PROFILES / f"{agent_id}.json").unlink(missing_ok=True)
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
