"""Komut satırı araçları (BAT dosyaları bunları kullanır).

  python cli.py hw                      -> donanım analizi ve önerilen model
  python cli.py prepare [--model ID] [--location usb|local|hybrid] [--all-engines]
                                        -> llama.cpp motoru + donanıma uygun modeli indirir (paketler)
  python cli.py backup [--password P]   -> yedek alır
  python cli.py restore NAME [--password P]
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from app import model_manager as mm  # noqa: E402
from app.config import load_machine, save_machine  # noqa: E402
from app.hardware import detect  # noqa: E402
from app.paths import ensure_dirs  # noqa: E402


def _bar(job: dict):
    def cb(done: int, total: int):
        pct = done / total * 100 if total else 0
        sys.stdout.write(f"\r  {job['label'][:40]:40s} {done/1024**2:8.1f} / {total/1024**2:8.1f} MB  %{pct:5.1f}")
        sys.stdout.flush()
    return cb


async def prepare(model: str | None, location: str, all_models: bool) -> None:
    hw = detect()
    rec = mm.recommend(hw)
    m = load_machine()
    m.update({"hardware": hw, "recommendation": rec})
    save_machine(m)
    print(f"Donanım: {hw['cpu']} | RAM {hw['ram_total_gb']} GB | GPU: {hw['gpu_best']['name'] if hw['gpu_best'] else 'yok/uygun değil'}")
    print(f"Çalışma modu: {rec['tier_label']} → önerilen model: {rec['model_id']}")
    for r in rec["reasons"]:
        print("  •", r)
    print("\n[1/2] Yerel AI motoru (llama.cpp – Vulkan GPU + CPU sürümleri) indiriliyor…")
    job = {"label": "llama.cpp", "cancel": asyncio.Event()}
    orig = mm._progress_cb
    mm._progress_cb = lambda j: _bar(j)  # konsol ilerleme çubuğu
    try:
        await mm.download_engine(job=job)
        print("\n  Motor hazır.")
    except Exception as e:  # noqa
        print(f"\n  UYARI: Motor indirilemedi: {e}")
    ids = [x["id"] for x in mm.CATALOG["models"]] if all_models else [model or rec["model_id"]]
    for mid in ids:
        mdl = mm.get_model(mid)
        print(f"\n[2/2] Model: {mdl['name']} ({mdl['size_gb']} GB, en az {mdl['ram_gb']} GB RAM)")
        print(f"  Lisans: {mdl['license']}")
        job = {"label": mdl["name"], "cancel": asyncio.Event()}
        try:
            p = await mm.download_model(mid, location, job)
            print(f"\n  Kaydedildi: {p}")
        except Exception as e:  # noqa
            print(f"\n  HATA: {e}  (Komutu tekrar çalıştırırsanız kaldığı yerden devam eder.)")
    emb = mm.CATALOG["embedding"]
    print(f"\n[+] Anlamsal arama modeli: {emb['name']} ({emb['size_gb']} GB, lisans {emb['license']})")
    try:
        dest = mm.DIRS["models"] / emb["file"]
        if not dest.exists():
            await mm.download_file(emb["url"], dest, _bar({"label": "bge-m3"}))
        print("\n  Hazır.")
    except Exception as e:  # noqa
        print(f"\n  UYARI: indirilemedi ({e}); anahtar kelime araması yine çalışır.")
    mm._progress_cb = orig
    print("\nPaketleme tamamlandı. Artık internet olmadan çalışabilirsiniz.")


def main() -> None:
    ensure_dirs()
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd")
    sub.add_parser("hw")
    p = sub.add_parser("prepare")
    p.add_argument("--model")
    p.add_argument("--location", default="usb", choices=["usb", "local", "hybrid"])
    p.add_argument("--all-models", action="store_true")
    b = sub.add_parser("backup")
    b.add_argument("--password", default="")
    r = sub.add_parser("restore")
    r.add_argument("name", nargs="?")
    r.add_argument("--password", default="")
    a = ap.parse_args()
    if a.cmd == "hw":
        hw = detect()
        print(json.dumps({"hardware": hw, "recommendation": mm.recommend(hw)}, ensure_ascii=False, indent=2))
    elif a.cmd == "prepare":
        asyncio.run(prepare(a.model, a.location, a.all_models))
    elif a.cmd in ("backup", "restore"):
        from app import backup
        from app.db import db
        db.open()
        if a.cmd == "backup":
            print("Yedek oluşturuldu:", backup.create_backup(password=a.password))
        else:
            items = backup.list_backups()
            if not a.name:
                for i, it in enumerate(items, 1):
                    print(f"{i}. {it['name']}  ({it['size_mb']} MB{' , şifreli' if it['encrypted'] else ''})")
                if not items:
                    print("Yedek yok."); return
                sel = input("Geri yüklenecek yedek numarası: ").strip()
                a.name = items[int(sel) - 1]["name"]
                if a.name.endswith(".aioffice") and not a.password:
                    a.password = input("Parola: ")
            print(backup.restore_backup(a.name, a.password))
        db.close()
    else:
        ap.print_help()


if __name__ == "__main__":
    main()
