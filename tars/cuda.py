"""Make CUDA libraries that faster-whisper (CTranslate2) needs visible to the loader."""

import os
import sys
from pathlib import Path

# cuDNN 9 comes from the nvidia-cudnn-cu12 wheel in .venv; cuBLAS 12 from the
# CUDA 12.8 toolkit already on the system (saves a ~450 MB duplicate download).
LIB_DIRS = [
    Path(sys.prefix) / "lib" / f"python{sys.version_info.major}.{sys.version_info.minor}"
    / "site-packages" / "nvidia" / "cudnn" / "lib",
    Path("/usr/local/cuda/lib64"),
]  # fmt: skip


def reexec_with_cuda_libs(module: str):
    """LD_LIBRARY_PATH is read only at process start, so re-exec once with it set."""
    if os.environ.get("TARS_CUDA_LIBS") == "1":
        return
    current = [p for p in os.environ.get("LD_LIBRARY_PATH", "").split(":") if p]
    extra = [str(d) for d in LIB_DIRS if d.exists() and str(d) not in current]
    env = {**os.environ, "TARS_CUDA_LIBS": "1", "LD_LIBRARY_PATH": ":".join(extra + current)}
    os.execve(sys.executable, [sys.executable, "-m", module, *sys.argv[1:]], env)
