"""Make pip-installed NVIDIA runtime DLLs (cuBLAS/cuDNN) loadable.

CTranslate2's Windows wheel dlopens cublas64_12.dll / cudnn64_9.dll at first
use. We ship those via the nvidia-*-cu12 pip packages and point both the
DLL search path AND PATH at them (ctranslate2 uses plain LoadLibrary, which
ignores os.add_dll_directory alone).

On unsupported-by-binary GPU architectures (e.g. Blackwell sm_120) the first
CUDA call triggers a one-time PTX JIT compile (~10-30 s); the driver caches
the result, so later runs start fast.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

_done = False


def setup_cuda_dll_dirs() -> None:
    global _done
    if _done or sys.platform != "win32":
        return
    _done = True

    site = Path(sys.prefix) / "Lib" / "site-packages"
    dirs = []
    for sub in ("nvidia/cublas/bin", "nvidia/cudnn/bin", "nvidia/cuda_nvrtc/bin"):
        p = site / sub
        if p.is_dir():
            try:
                os.add_dll_directory(str(p))
            except OSError:
                pass
            dirs.append(str(p))
    if dirs:
        os.environ["PATH"] = os.pathsep.join(dirs) + os.pathsep + os.environ.get("PATH", "")
