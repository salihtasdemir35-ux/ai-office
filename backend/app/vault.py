"""Aşama 6: USB veri kasası (parolalı şifreleme).

'Kilitle': ajanlar, hafıza, bilgi bankası, projeler, veritabanı ve ayarlar tek bir şifreli dosyada (VAULT.aioffice)
toplanır, açık kopyalar silinir. USB kaybolsa bile parola olmadan okunamaz. Açılışta parola sorulur.
AES (Fernet) + PBKDF2-SHA256 390.000 tur. Parola unutulursa veriler KURTARILAMAZ.
"""
from __future__ import annotations

import io
import shutil
import zipfile

from .backup import decrypt_bytes, encrypt_bytes
from .db import db
from .paths import DIRS, ROOT

VAULT = ROOT / "VAULT.aioffice"
DIR_PARTS = ["database", "memory", "knowledge_base", "projects", "agent_profiles"]
FILE_PARTS = ["config/settings.json"]


def is_locked() -> bool:
    return VAULT.exists()


def lock(password: str, include_workspace: bool = False) -> dict:
    if len(password) < 6:
        raise ValueError("Parola en az 6 karakter olmalı.")
    if is_locked():
        raise ValueError("Kasa zaten kilitli.")
    db.checkpoint()
    db.close()
    dirs = DIR_PARTS + (["workspace"] if include_workspace else [])
    buf = io.BytesIO()
    count = 0
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for d in dirs:
            base = ROOT / d
            for f in base.rglob("*") if base.exists() else []:
                if f.is_file() and f.name != ".gitkeep":
                    z.write(f, f.relative_to(ROOT).as_posix())
                    count += 1
        for fp in FILE_PARTS:
            f = ROOT / fp
            if f.exists():
                z.write(f, fp)
                count += 1
    blob = encrypt_bytes(buf.getvalue(), password)
    # Silmeden önce doğrula: şifreli dosya gerçekten açılabiliyor mu?
    if decrypt_bytes(blob, password) != buf.getvalue():
        db.open()
        raise RuntimeError("Şifreleme doğrulaması başarısız; hiçbir veri silinmedi.")
    tmp = VAULT.with_suffix(".tmp")
    tmp.write_bytes(blob)
    tmp.replace(VAULT)
    for d in dirs:
        p = ROOT / d
        if p.exists():
            shutil.rmtree(p)
            p.mkdir()
    for fp in FILE_PARTS:
        (ROOT / fp).unlink(missing_ok=True)
    return {"files": count, "vault": VAULT.name}


def unlock(password: str) -> dict:
    if not is_locked():
        return {"files": 0}
    data = decrypt_bytes(VAULT.read_bytes(), password)  # yanlış parolada ValueError
    n = 0
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        for info in z.infolist():
            target = (ROOT / info.filename).resolve()
            if ROOT not in target.parents:
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with z.open(info) as s, open(target, "wb") as d:
                shutil.copyfileobj(s, d)
            n += 1
    VAULT.unlink()
    for p in DIRS.values():
        p.mkdir(parents=True, exist_ok=True)
    db.open()
    return {"files": n}
