"""NVIDIA GPU memory readings via NVML (nvidia-ml-py), falling back to nvidia-smi."""

import subprocess
import threading
import time

try:
    import pynvml

    pynvml.nvmlInit()
    _HANDLE = pynvml.nvmlDeviceGetHandleByIndex(0)
except Exception:  # package missing or no driver: use nvidia-smi instead
    _HANDLE = None


def _smi(field: str) -> int:
    try:
        out = subprocess.run(
            ["nvidia-smi", f"--query-gpu={field}", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=5,
        ).stdout  # fmt: skip
        return int(out.split()[0])
    except Exception:
        return 0


def _mem():
    # v2 reports the driver's reserved block (~380 MiB here) separately; v1 folds it
    # into "used". v2 matches nvidia-smi and what CUDA programs can actually get.
    return pynvml.nvmlDeviceGetMemoryInfo(_HANDLE, version=pynvml.nvmlMemory_v2)


def vram_used_mib() -> int:
    """Memory used by processes (excludes the driver reservation), like nvidia-smi."""
    if _HANDLE is None:
        return _smi("memory.used")
    return int(_mem().used // (1024 * 1024))


def vram_usable_mib() -> int:
    """Total minus the driver reservation: the most models can ever use (3714 MiB here)."""
    if _HANDLE is None:
        return _smi("memory.total") - _smi("memory.reserved")
    m = _mem()
    return int((m.total - m.reserved) // (1024 * 1024))


def vram_total_mib() -> int:
    if _HANDLE is None:
        return _smi("memory.total")
    return int(pynvml.nvmlDeviceGetMemoryInfo(_HANDLE).total // (1024 * 1024))


class PeakVram:
    """Context manager that samples VRAM in the background and keeps the peak."""

    def __init__(self, interval: float = 0.1):
        self.interval = interval
        self.peak = 0
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)

    def _run(self):
        while not self._stop.is_set():
            self.peak = max(self.peak, vram_used_mib())
            time.sleep(self.interval)

    def __enter__(self):
        self.peak = vram_used_mib()
        self._thread.start()
        return self

    def __exit__(self, *exc):
        self._stop.set()
        self._thread.join()
        self.peak = max(self.peak, vram_used_mib())
        return False
