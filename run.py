"""AI OFFICE başlatıcı: boş port bulur, sunucuyu 127.0.0.1'de başlatır, tarayıcıda arayüzü açar."""
from __future__ import annotations

import os
import socket
import sys
import threading
import time
import webbrowser
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from app.config import get_settings  # noqa: E402
from app.paths import DIRS, ensure_dirs  # noqa: E402


def free_port(start: int) -> int:
    for p in range(start, start + 50):
        with socket.socket() as s:
            try:
                s.bind(("127.0.0.1", p))
                return p
            except OSError:
                continue
    raise SystemExit("Boş port bulunamadı.")


def main() -> None:
    ensure_dirs()
    port = free_port(int(get_settings().get("port", 8765)))
    (DIRS["runtime"] / "port.txt").write_text(str(port), encoding="utf-8")
    url = f"http://127.0.0.1:{port}"
    print("=" * 60)
    print("  AI OFFICE – Autonomous AI Workforce")
    print(f"  Arayüz: {url}")
    print("  Bu pencereyi KAPATMAYIN. Kapatmak için arayüzde 'Güvenli Kapat' kullanın.")
    print("=" * 60)
    if "--no-browser" not in sys.argv:
        def _open():
            time.sleep(2.0)
            webbrowser.open(url)
        threading.Thread(target=_open, daemon=True).start()
    import uvicorn
    uvicorn.run("app.main:app", host="127.0.0.1", port=port, log_level="warning", access_log=False)


if __name__ == "__main__":
    os.chdir(HERE)
    main()
