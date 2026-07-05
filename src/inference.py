from __future__ import annotations

from pathlib import Path
from typing import Any

from src.guardrails import WARNING_TEXT
from src.preprocessing import basic_quality_flag


def _classify_from_name(path: Path, mode: str) -> tuple[str, float]:
    """Return a deterministic toy prediction based on the image filename.

    The goal is to keep the prototype simple, reproducible and auditable.
    A real clinical pipeline should replace this with a validated model.
    """
    name = path.name.lower()
    if any(token in name for token in ("suspected_opacity", "opacity", "pneumonia")):
        return ("suspected_opacity", 0.84 if mode == "improved" else 0.78)
    if any(token in name for token in ("normal", "clear", "healthy")):
        return ("normal", 0.82 if mode == "improved" else 0.74)
    if any(token in name for token in ("uncertain", "limited", "ambiguous")):
        return ("uncertain", 0.63)
    return ("uncertain", 0.50)


def toy_predict(image_path: str | Path, mode: str = "improved") -> dict[str, Any]:
    """Create a toy prediction payload that matches the project schema."""
    path = Path(image_path)
    predicted_class, confidence = _classify_from_name(path, mode)
    return {
        "image_quality": basic_quality_flag(path),
        "predicted_class": predicted_class,
        "confidence": confidence,
        "visual_evidence": ["Deterministic toy heuristic based on filename and image metadata"],
        "justification": "This educational prototype uses a simple, auditable rule instead of a validated medical model.",
        "limitations": ["toy heuristic only", "not a validated medical model", "no clinical context"],
        "warning": WARNING_TEXT,
        "model_name": f"toy-{mode}",
        "prompt_version": mode,
        "latency_ms": 5,
    }
