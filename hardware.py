"""Donanım analizi: Windows sürümü, işlemci, RAM, GPU (AMD/NVIDIA/Intel), VRAM, disk, Python, internet."""
from __future__ import annotations

import json
import os
import platform
import shutil
import socket
import subprocess
import sys

import psutil

from .paths import DIRS, ROOT

NO_WINDOW = 0x08000000 if os.name == "nt" else 0


def _run(cmd: list[str], timeout: int = 15) -> str:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout,
                           creationflags=NO_WINDOW, encoding="utf-8", errors="ignore")
        return r.stdout or ""
    except Exception:
        return ""


def _vendor(name: str) -> str:
    n = name.lower()
    if any(k in n for k in ("nvidia", "geforce", "quadro", "rtx", "gtx")):
        return "NVIDIA"
    if any(k in n for k in ("amd", "radeon", "ati ")):
        return "AMD"
    if "intel" in n:
        return "Intel"
    return "Diğer"


def _gpus_windows() -> list[dict]:
    gpus: list[dict] = []
    try:  # Kayıt defteri: 4 GB üstü VRAM'i de doğru verir (WMI AdapterRAM 4 GB'ta takılır)
        import winreg
        base = r"SYSTEM\CurrentControlSet\Control\Class\{4d36e968-e325-11ce-bfc1-08002be10318}"
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, base) as k:
            i = 0
            while True:
                try:
                    sub = winreg.EnumKey(k, i)
                except OSError:
                    break
                i += 1
                if not sub.isdigit():
                    continue
                try:
                    with winreg.OpenKey(k, sub) as sk:
                        name = winreg.QueryValueEx(sk, "DriverDesc")[0]
                        vram = 0
                        for val in ("HardwareInformation.qwMemorySize", "HardwareInformation.MemorySize"):
                            try:
                                v = winreg.QueryValueEx(sk, val)[0]
                                if isinstance(v, bytes):
                                    v = int.from_bytes(v[:8], "little")
                                vram = int(v)
                                break
                            except OSError:
                                continue
                        gpus.append({"name": name, "vendor": _vendor(name), "vram_gb": round(vram / 1024**3, 1)})
                except OSError:
                    continue
    except Exception:
        pass
    if not gpus:
        out = _run(["powershell", "-NoProfile", "-Command",
                    "Get-CimInstance Win32_VideoController | Select-Object Name,AdapterRAM | ConvertTo-Json"])
        try:
            data = json.loads(out)
            data = [data] if isinstance(data, dict) else data
            for d in data:
                nm = d.get("Name") or ""
                gpus.append({"name": nm, "vendor": _vendor(nm), "vram_gb": round((d.get("AdapterRAM") or 0) / 1024**3, 1)})
        except Exception:
            pass
    return gpus


def _gpus_other() -> list[dict]:
    gpus = []
    out = _run(["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader,nounits"])
    for line in out.strip().splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) == 2:
            try:
                gpus.append({"name": parts[0], "vendor": "NVIDIA", "vram_gb": round(float(parts[1]) / 1024, 1)})
            except ValueError:
                pass
    if not gpus and shutil.which("lspci"):
        for line in _run(["lspci"]).splitlines():
            if "VGA" in line or "3D controller" in line:
                nm = line.split(":", 2)[-1].strip()
                gpus.append({"name": nm, "vendor": _vendor(nm), "vram_gb": 0.0})
    return gpus


def _cpu_name() -> str:
    if os.name == "nt":
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"HARDWARE\DESCRIPTION\System\CentralProcessor\0") as k:
                return winreg.QueryValueEx(k, "ProcessorNameString")[0].strip()
        except Exception:
            pass
    try:
        with open("/proc/cpuinfo", encoding="utf-8") as f:
            for line in f:
                if line.startswith("model name"):
                    return line.split(":", 1)[1].strip()
    except Exception:
        pass
    return platform.processor() or "Bilinmiyor"


def _windows_version() -> str:
    if os.name != "nt":
        return f"{platform.system()} {platform.release()} (Windows değil – geliştirme ortamı)"
    ver = platform.version()  # 10.0.22631
    try:
        build = int(ver.split(".")[-1])
    except ValueError:
        build = 0
    name = "Windows 11" if build >= 22000 else "Windows 10"
    return f"{name} (sürüm {ver})"


def _internet() -> bool:
    for host, port in (("1.1.1.1", 443), ("8.8.8.8", 53)):
        try:
            with socket.create_connection((host, port), timeout=2):
                return True
        except OSError:
            continue
    return False


def _vulkan_runtime() -> bool:
    if os.name == "nt":
        sysroot = os.environ.get("SystemRoot", r"C:\Windows")
        return os.path.exists(os.path.join(sysroot, "System32", "vulkan-1.dll"))
    return bool(shutil.which("vulkaninfo"))


def detect() -> dict:
    vm = psutil.virtual_memory()
    try:
        disk = shutil.disk_usage(ROOT)
        disk_free = round(disk.free / 1024**3, 1)
        disk_total = round(disk.total / 1024**3, 1)
    except Exception:
        disk_free = disk_total = 0.0
    gpus = _gpus_windows() if os.name == "nt" else _gpus_other()
    seen, clean = set(), []
    for g in gpus:
        low = g["name"].lower()
        if any(k in low for k in ("basic display", "basic render", "virtual", "remote", "parsec", "meta")):
            continue
        if g["name"] in seen:
            continue
        seen.add(g["name"])
        clean.append(g)
    # Kullanılabilir GPU: en az 3 GB ayrık bellek. Paylaşımlı küçük iGPU'lar CPU modunda daha kararlı.
    usable = [g for g in clean if g["vendor"] in ("NVIDIA", "AMD", "Intel") and g["vram_gb"] >= 3]
    best = max(usable, key=lambda g: g["vram_gb"]) if usable else None
    return {
        "os": _windows_version(),
        "is_windows": os.name == "nt",
        "cpu": _cpu_name(),
        "cores_physical": psutil.cpu_count(logical=False) or 1,
        "cores_logical": psutil.cpu_count(logical=True) or 1,
        "ram_total_gb": round(vm.total / 1024**3, 1),
        "ram_available_gb": round(vm.available / 1024**3, 1),
        "gpus": clean,
        "gpu_best": best,
        "gpu_usable": best is not None,
        "vram_gb": best["vram_gb"] if best else 0.0,
        "vulkan_runtime": _vulkan_runtime(),
        "disk_free_gb": disk_free,
        "disk_total_gb": disk_total,
        "drive": ROOT.drive or "/",
        "python": sys.version.split()[0],
        "python_embedded": str(DIRS["runtime"]) in sys.executable,
        "internet": _internet(),
    }


_gpu_cache = {"ts": 0.0, "value": None}


def gpu_usage() -> dict | None:
    """GPU kullanımı: NVIDIA için nvidia-smi; Windows'ta tüm üreticiler (AMD/Intel dahil) için
    dil bağımsız WMI performans sınıfı Win32_PerfFormattedData_GPUPerformanceCounters_GPUEngine."""
    import time as _t
    if _t.time() - _gpu_cache["ts"] < 8:
        return _gpu_cache["value"]
    _gpu_cache["ts"] = _t.time()
    val = None
    out = _run(["nvidia-smi", "--query-gpu=utilization.gpu,memory.used,memory.total", "--format=csv,noheader,nounits"], 5)
    if out.strip():
        try:
            u, used, total = [float(x) for x in out.strip().splitlines()[0].split(",")]
            val = {"percent": u, "vram_used_gb": round(used / 1024, 1), "vram_total_gb": round(total / 1024, 1), "source": "nvidia-smi"}
        except ValueError:
            pass
    if val is None and os.name == "nt":
        ps = ("$e=Get-CimInstance Win32_PerfFormattedData_GPUPerformanceCounters_GPUEngine -ErrorAction SilentlyContinue | "
              "Where-Object {$_.Name -like '*engtype_3D*' -or $_.Name -like '*engtype_Compute*'}; "
              "[math]::Min(100, ($e | Measure-Object -Property UtilizationPercentage -Sum).Sum)")
        out = _run(["powershell", "-NoProfile", "-Command", ps], 10).strip()
        try:
            val = {"percent": float(out.replace(",", ".")), "source": "Windows WMI"}
        except ValueError:
            val = None
    _gpu_cache["value"] = val
    return val


def resources() -> dict:
    vm = psutil.virtual_memory()
    try:
        d = shutil.disk_usage(ROOT)
        disk = {"free_gb": round(d.free / 1024**3, 1), "percent": round(d.used / d.total * 100, 1)}
    except Exception:
        disk = {"free_gb": 0, "percent": 0}
    return {
        "cpu_percent": psutil.cpu_percent(interval=None),
        "ram_percent": vm.percent,
        "ram_used_gb": round((vm.total - vm.available) / 1024**3, 1),
        "ram_total_gb": round(vm.total / 1024**3, 1),
        "disk": disk,
        "gpu": _gpu_cache["value"],
    }
