"""Optional GPU discovery and explicit backend selection; CPU needs only NumPy."""

from functools import lru_cache
import os
from .engine import Network


@lru_cache(maxsize=1)
def devices():
    result = [dict(id="cpu", label="CPU · NumPy", available=True, reason="")]
    try:
        import torch
    except (ImportError, OSError) as exc:
        reason = "Установите requirements-gpu.txt и перезапустите сервер"
        return result + [
            dict(id=d, label=label, available=False, reason=f"{reason} ({type(exc).__name__})")
            for d, label in (("mps", "GPU · Apple Metal"), ("cuda:0", "GPU · NVIDIA CUDA"))
        ]
    mps = torch.backends.mps.is_available()
    fallback = os.environ.get("PYTORCH_ENABLE_MPS_FALLBACK") == "1"
    result.append(
        dict(
            id="mps",
            label="GPU · Apple Metal",
            available=mps and not fallback,
            reason=(
                "Отключите PYTORCH_ENABLE_MPS_FALLBACK и перезапустите сервер"
                if fallback
                else ""
                if mps
                else "Metal/MPS недоступен на этом сервере"
            ),
        )
    )
    if torch.cuda.is_available():
        result.extend(
            dict(
                id=f"cuda:{i}",
                label=f"GPU · {torch.cuda.get_device_name(i)} (CUDA {i})",
                available=True,
                reason="",
            )
            for i in range(torch.cuda.device_count())
        )
    else:
        result.append(
            dict(
                id="cuda:0",
                label="GPU · NVIDIA CUDA",
                available=False,
                reason="Нет доступного CUDA GPU или установлена сборка PyTorch без CUDA",
            )
        )
    return result


def create_network(topology, seed=42, device="cpu"):
    if device == "cpu":
        return Network(topology, seed)
    option = next((d for d in devices() if d["id"] == device), None)
    if not option or not option["available"]:
        raise ValueError(option["reason"] if option else "Неизвестное вычислительное устройство")
    from .gpu import GPUNetwork

    try:
        return GPUNetwork(topology, seed, device)
    except (RuntimeError, NotImplementedError) as exc:
        raise ValueError(f"Не удалось запустить {device}: {exc}") from exc
