"""Make the CUDA libraries that faster-whisper (CTranslate2) and llama.cpp need visible to the loader."""

import os
import sys
from pathlib import Path

# CUDA 12 runtime, cuBLAS 12 and cuDNN 9 come from NVIDIA's wheels in .venv, so TARS
# doesn't depend on which CUDA toolkit the system has (it moved to CUDA 13, and the
# llama.cpp build and CTranslate2 both need the CUDA 12 libraries).
NVIDIA = (
    Path(sys.prefix) / "lib" / f"python{sys.version_info.major}.{sys.version_info.minor}"
    / "site-packages" / "nvidia"
)  # fmt: skip
LIB_DIRS = [NVIDIA / name / "lib" for name in ("cuda_runtime", "cublas", "cudnn")]


NEEDED = {"cuda_runtime": "libcudart.so.12", "cublas": "libcublas.so.12", "cudnn": "libcudnn.so.9"}


def missing_libs() -> list[str]:
    return [lib for d, lib in NEEDED.items() if not (NVIDIA / d / "lib" / lib).exists()]


def reexec_with_cuda_libs(module: str):
    """LD_LIBRARY_PATH is read only at process start, so re-exec once with it set."""
    if os.environ.get("TARS_CUDA_LIBS") == "1":
        return
    if missing := missing_libs():
        # Without them neither the model server nor speech recognition can start, and
        # the errors they give are far from obvious.
        sys.exit(f"TARS: CUDA 12 libraries missing from .venv ({', '.join(missing)}). "
                 "Reinstall them: .venv/bin/pip install --no-deps 'nvidia-cudnn-cu12>=9,<10' "
                 "nvidia-cuda-runtime-cu12==12.8.90 nvidia-cublas-cu12==12.8.4.1")  # fmt: skip
    current = [p for p in os.environ.get("LD_LIBRARY_PATH", "").split(":") if p]
    extra = [str(d) for d in LIB_DIRS if d.exists() and str(d) not in current]
    env = {
        **os.environ,
        "TARS_CUDA_LIBS": "1",
        "LD_LIBRARY_PATH": ":".join(extra + current),
        # cap what CTranslate2's allocator keeps cached (bin growth, min bin, max bin,
        # max cached bytes): the GPU is shared with the Brain and has little slack
        "CT2_CUDA_CACHING_ALLOCATOR_CONFIG": "4,3,12,104857600",
    }
    os.execve(sys.executable, [sys.executable, "-m", module, *sys.argv[1:]], env)
