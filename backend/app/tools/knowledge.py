"""Hafıza ve bilgi bankası araçları."""
from __future__ import annotations

from .. import memory
from .base import ToolContext, tool


@tool("memory_search", "Hafıza arama", 1, "Ofis hafızasında (kendi, ortak ve kullanıcı tercihleri) arama yapar.",
      {"sorgu": "aranacak konu"}, "Araştırıyor", "Hafıza")
async def memory_search(ctx: ToolContext, sorgu: str) -> str:
    text = await memory.recall(ctx.agent_id, sorgu, limit=8)
    return ("Doğrulanmamış geçmiş bilgiler (eski veya çelişkili olabilir):\n" + text) if text else "Hafızada ilgili kayıt yok."


@tool("memory_save", "Hafızaya kaydetme", 2, "Önemli bir bilgiyi ortak ofis hafızasına kaydeder (kaynak belirt).",
      {"bilgi": "kaydedilecek bilgi", "kaynak": "kaynak adresi veya açıklaması"}, "Yazıyor", "Hafıza")
async def memory_save(ctx: ToolContext, bilgi: str, kaynak: str = "") -> str:
    mid = memory.add("ofis", bilgi, owner=ctx.agent_id, project=ctx.task_id or "", source=kaynak,
                     confidence=0.5, created_by=ctx.agent_id, shared=True)
    return f"Ortak hafızaya kaydedildi (#{mid})."


@tool("kb_search", "Bilgi bankası arama", 1, "Kullanıcının bilgi bankasına eklediği belgelerde arama yapar (internetsiz).",
      {"sorgu": "aranacak konu"}, "Araştırıyor", "Hafıza")
async def kb_search(ctx: ToolContext, sorgu: str) -> str:
    hits = await memory.kb_search_hybrid(sorgu)
    if not hits:
        return "Bilgi bankasında sonuç yok."
    for h in hits:
        ctx.sources.append(f"{h['title']} (bölüm {h['chunk_no'] + 1})")
    return "\n\n".join(f"[{h['title']} – bölüm {h['chunk_no'] + 1}]\n{h['content'][:700]}" for h in hits)
