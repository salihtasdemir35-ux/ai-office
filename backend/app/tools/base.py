"""Araç merkezi altyapısı. Yeni araç eklemek için @tool dekoratörünü kullanmak yeterlidir."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Awaitable, Callable


@dataclass
class ToolContext:
    agent_id: str
    task_id: str | None = None
    output_dir: str | None = None
    created_files: list[str] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)


@dataclass
class Tool:
    name: str
    label: str
    level: int                # 1 okuma, 2 düzenleme, 3 işlem
    desc: str
    params: dict[str, str]
    func: Callable[..., Awaitable[str]]
    status: str = "Çalışıyor"  # ofiste gösterilecek durum
    needs_internet: bool = False
    needs_approval: bool = False
    group: str = "Genel"


TOOLS: dict[str, Tool] = {}


def tool(name: str, label: str, level: int, desc: str, params: dict[str, str], status: str,
         group: str, needs_internet: bool = False, needs_approval: bool = False):
    def deco(fn):
        TOOLS[name] = Tool(name, label, level, desc, params, fn, status, needs_internet, needs_approval, group)
        return fn
    return deco


def describe(names: list[str]) -> str:
    lines = []
    for n in names:
        t = TOOLS.get(n)
        if t:
            ps = ", ".join(f'"{k}": {v}' for k, v in t.params.items())
            lines.append(f"- {t.name}: {t.desc} Parametreler: {{{ps}}}")
    return "\n".join(lines) or "- (araç yok; sadece kendi bilginle çalış)"
