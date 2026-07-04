from __future__ import annotations

import sys
import tempfile
from pathlib import Path
from typing import Any

from .config import REPO_ROOT

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

def available_models() -> list[str]:
    models = ["baseline", "improved"]
    adapter = REPO_ROOT / "finetuning" / "outputs" / "medgemma-pneumo-lora"
    if adapter.exists():
        try:
            import torch

            if torch.cuda.is_available():
                models.append("finetuned")
        except Exception:
            pass
    return models

def analyze_image(image_bytes: bytes, filename: str, model: str) -> dict[str, Any]:
    import re

    from src.guardrails import apply_safety_guardrails

    suffix = Path(filename).suffix or ".png"
    stem = Path(filename).stem or "image"
    safe_stem = re.sub(r"[^A-Za-z0-9_.-]+", "_", stem)
    tmp_dir = Path(tempfile.mkdtemp(prefix="truevision_"))
    tmp_path = tmp_dir / f"{safe_stem}{suffix}"
    tmp_path.write_bytes(image_bytes)

    try:
        if model == "finetuned":
            pred = _predict_finetuned(tmp_path)
        else:
            from src.inference import toy_predict

            pred = apply_safety_guardrails(toy_predict(tmp_path, mode=model))
    finally:
        import shutil

        shutil.rmtree(tmp_dir, ignore_errors=True)
    return pred

_FT_CACHE: dict[str, Any] = {}

def _predict_finetuned(image_path: Path) -> dict[str, Any]:
    from finetuning.infer_finetuned import load_finetuned, predict_finetuned

    if "model" not in _FT_CACHE:
        adapter = REPO_ROOT / "finetuning" / "outputs" / "medgemma-pneumo-lora"
        model, processor = load_finetuned(str(adapter))
        _FT_CACHE["model"], _FT_CACHE["processor"] = model, processor
    return predict_finetuned(
        _FT_CACHE["model"], _FT_CACHE["processor"], image_path,
        sensitivity_threshold=0.5,
    )
