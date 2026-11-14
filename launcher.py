"""AI_OFFICE.exe kaynak kodu (GitHub Actions'ta PyInstaller ile derlenir). START_AI_OFFICE.bat'i kendi klasöründen çalıştırır."""
import os
import subprocess
import sys

here = os.path.dirname(sys.executable if getattr(sys, "frozen", False) else os.path.abspath(__file__))
subprocess.call(["cmd", "/c", os.path.join(here, "START_AI_OFFICE.bat")], cwd=here)
