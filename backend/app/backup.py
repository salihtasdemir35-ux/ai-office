"""Tek tıkla yedekleme (ZIP), isteğe bağlı parolalı şifreleme (AES/Fernet + PBKDF2) ve geri yükleme."""
from __future__ import annotations

import base64
import io
import os
import shutil
import time
import zipfile
from pathlib import Path

from .db import db
from .paths import DIRS, ROOT

MAGIC = b"AIOFFENC1"
PARTS = {
    "agents": ["agent_profiles"],
    "memory": ["memory", "knowledge_base"],
    "projects": ["projects"],
    "settings": ["config"],
    "database": ["database"],
    "workspace": ["workspace"],
}


def _key(password: str, salt: bytes) -> bytes:
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
    kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=390_000)
    return base64.urlsafe_b64encode(kdf.derive(password.encode("utf-8")))


def encrypt_bytes(data: bytes, password: str) -> bytes:
    from cryptography.fernet import Fernet
    salt = os.urandom(16)
    return MAGIC + salt + Fernet(_key(password, salt)).encrypt(data)


def decrypt_bytes(blob: bytes, password: str) -> bytes:
    from cryptography.fernet import Fernet, InvalidToken
    if not blob.startswith(MAGIC):
        raise ValueError("Şifreli yedek biçimi tanınmadı.")
    salt = blob[len(MAGIC):len(MAGIC) + 16]
    try:
        return Fernet(_key(password, salt)).decrypt(blob[len(MAGIC) + 16:])
    except InvalidToken as e:
        raise ValueError("Parola yanlış veya yedek bozuk.") from e


def create_backup(parts: list[str] | None = None, password: str = "") -> Path:
    parts = parts or ["agents", "memory", "projects", "settings", "database"]
    db.checkpoint()
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for part in parts:
            for d in PARTS.get(part, []):
                base = ROOT / d
                if not base.exists():
                    continue
                for f in base.rglob("*"):
                    if f.is_file() and not f.name.endswith((".part", ".tmp")):
                        z.write(f, f.relative_to(ROOT).as_posix())
        z.writestr("YEDEK_BILGI.txt", f"AI OFFICE yedeği\nTarih: {time.strftime('%Y-%m-%d %H:%M:%S')}\nBölümler: {', '.join(parts)}\n")
    name = f"AI_OFFICE_YEDEK_{time.strftime('%Y%m%d_%H%M%S')}"
    DIRS["backups"].mkdir(parents=True, exist_ok=True)
    if password:
        out = DIRS["backups"] / f"{name}.aioffice"
        out.write_bytes(encrypt_bytes(buf.getvalue(), password))
    else:
        out = DIRS["backups"] / f"{name}.zip"
        out.write_bytes(buf.getvalue())
    return out


def list_backups() -> list[dict]:
    out = []
    for f in sorted(DIRS["backups"].glob("AI_OFFICE_YEDEK_*"), reverse=True):
        out.append({"name": f.name, "size_mb": round(f.stat().st_size / 1024**2, 2),
                    "encrypted": f.suffix == ".aioffice", "date": time.strftime("%d.%m.%Y %H:%M", time.localtime(f.stat().st_mtime))})
    return out


def restore_backup(name: str, password: str = "") -> dict:
    src = DIRS["backups"] / Path(name).name
    if not src.exists():
        raise FileNotFoundError("Yedek bulunamadı")
    data = src.read_bytes()
    if src.suffix == ".aioffice":
        if not password:
            raise ValueError("Bu yedek şifreli; parola gerekli.")
        data = decrypt_bytes(data, password)
    # Geri yüklemeden önce mevcut durumu güvenceye al
    safety = create_backup(["agents", "memory", "projects", "settings", "database"])
    db.close()
    restored = 0
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            for info in z.infolist():
                target = (ROOT / info.filename).resolve()
                if ROOT not in target.parents or info.filename == "YEDEK_BILGI.txt":
                    continue  # zip slip koruması
                target.parent.mkdir(parents=True, exist_ok=True)
                with z.open(info) as s, open(target, "wb") as d:
                    shutil.copyfileobj(s, d)
                restored += 1
    finally:
        db.open()
    return {"restored_files": restored, "safety_backup": safety.name}
