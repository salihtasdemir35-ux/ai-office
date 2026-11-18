"""'Bilgisayara kur' seçeneği ve model dosyası yönetimi (taşıma/silme)."""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

from . import model_manager as mm
from .hardware import NO_WINDOW
from .paths import DIRS, ROOT, local_appdata

SKIP = {"cache", "logs", "backups", "__pycache__"}


def install_local(include_models: bool = True) -> dict:
    """Taşınabilir klasörü %LOCALAPPDATA%\\AI_OFFICE\\app altına kopyalar (yönetici yetkisi gerekmez),
    taşınabilir mod dosyasını kaldırır ve masaüstü + Başlat menüsü kısayolu oluşturur."""
    dest = local_appdata() / "app"
    if dest.resolve() == ROOT.resolve():
        raise ValueError("Zaten bu bilgisayarda kurulu konumdan çalışıyorsunuz.")

    def ignore(d, names):
        out = {n for n in names if n in SKIP}
        if not include_models and Path(d).name == "models":
            out |= {n for n in names if n.endswith(".gguf")}
        return out
    shutil.copytree(ROOT, dest, ignore=ignore, dirs_exist_ok=True)
    (dest / "PORTABLE_MODE.json").unlink(missing_ok=True)
    shortcuts = []
    if os.name == "nt":
        target = dest / "START_AI_OFFICE.bat"
        for folder in ("Desktop", "Programs"):
            ps = (f"$s=(New-Object -ComObject WScript.Shell); "
                  f"$p=if('{folder}' -eq 'Desktop'){{[Environment]::GetFolderPath('Desktop')}}else{{[Environment]::GetFolderPath('Programs')}}; "
                  f"$l=$s.CreateShortcut((Join-Path $p 'AI OFFICE.lnk')); $l.TargetPath='{target}'; "
                  f"$l.WorkingDirectory='{dest}'; $l.Save(); Write-Output (Join-Path $p 'AI OFFICE.lnk')")
            r = subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True, text=True, creationflags=NO_WINDOW)
            if r.stdout.strip():
                shortcuts.append(r.stdout.strip())
    return {"path": str(dest), "shortcuts": shortcuts,
            "note": "Kurulum tamamlandı. Bu pencereyi kapatıp masaüstündeki 'AI OFFICE' kısayolundan başlatın."}


def model_files() -> list[dict]:
    out = []
    for d, label in ((DIRS["models"], "usb"), (local_appdata() / "models", "local")):
        for f in d.glob("*.gguf") if d.exists() else []:
            m = next((x for x in mm.CATALOG["models"] + [mm.CATALOG["embedding"]] if x["file"] == f.name), None)
            out.append({"file": f.name, "location": label, "size_gb": round(f.stat().st_size / 1024**3, 2),
                        "id": m["id"] if m else None, "license": m.get("license") if m else "bilinmiyor"})
    return out


def _find(file: str, location: str) -> Path:
    d = DIRS["models"] if location == "usb" else local_appdata() / "models"
    p = (d / Path(file).name)
    if not p.exists() or p.suffix != ".gguf":
        raise FileNotFoundError("Model dosyası bulunamadı")
    return p


def move_model(file: str, location: str) -> str:
    src = _find(file, location)
    dst_dir = local_appdata() / "models" if location == "usb" else DIRS["models"]
    dst_dir.mkdir(parents=True, exist_ok=True)
    if shutil.disk_usage(dst_dir).free < src.stat().st_size + 200 * 1024**2:
        raise ValueError("Hedefte yeterli disk alanı yok.")
    shutil.move(str(src), str(dst_dir / src.name))
    return str(dst_dir / src.name)


def delete_model(file: str, location: str) -> None:
    _find(file, location).unlink()
