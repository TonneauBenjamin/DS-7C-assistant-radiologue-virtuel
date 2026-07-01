from __future__ import annotations

from collections import Counter
from statistics import median
from typing import Iterable, Optional

CLASSES = ["normal", "suspected_opacity", "uncertain"]


def accuracy(y_true: Iterable[str], y_pred: Iterable[str]) -> float:
    y_true = list(y_true); y_pred = list(y_pred)
    if not y_true:
        return 0.0
    return sum(a == b for a, b in zip(y_true, y_pred)) / len(y_true)


def macro_f1(y_true: Iterable[str], y_pred: Iterable[str], classes: list[str] = CLASSES) -> float:
    y_true = list(y_true); y_pred = list(y_pred)
    scores = []
    for c in classes:
        tp = sum(t == c and p == c for t, p in zip(y_true, y_pred))
        fp = sum(t != c and p == c for t, p in zip(y_true, y_pred))
        fn = sum(t == c and p != c for t, p in zip(y_true, y_pred))
        precision = tp / (tp + fp) if tp + fp else 0
        recall = tp / (tp + fn) if tp + fn else 0
        f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0
        scores.append(f1)
    return sum(scores) / len(scores)


def confusion_counts(y_true: Iterable[str], y_pred: Iterable[str]) -> dict[str, int]:
    counts = Counter()
    for t, p in zip(y_true, y_pred):
        counts[f"{t}__{p}"] += 1
    return dict(counts)


def class_recall(y_true: Iterable[str], y_pred: Iterable[str], target: str) -> Optional[float]:
    """Rappel d'une classe = (bien classes) / (tous les cas de cette classe).

    Sensibilite = class_recall(..., 'suspected_opacity')
    Specificite = class_recall(..., 'normal')
    Renvoie None si aucun cas de cette classe (denominateur nul).
    """
    y_true = list(y_true); y_pred = list(y_pred)
    support = sum(t == target for t in y_true)
    if support == 0:
        return None
    correct = sum(t == target and p == target for t, p in zip(y_true, y_pred))
    return correct / support


def summarize_metrics(rows: list[dict]) -> dict[str, float]:
    y_true = [r["label"] for r in rows]
    y_pred = [r["predicted_class"] for r in rows]
    json_valid = [r.get("json_valid", True) for r in rows]
    warnings = [bool(r.get("warning")) for r in rows]
    latencies = [float(r["latency_ms"]) for r in rows if r.get("latency_ms") is not None]

    sens = class_recall(y_true, y_pred, "suspected_opacity")
    spec = class_recall(y_true, y_pred, "normal")

    return {
        "n": len(rows),
        "accuracy": round(accuracy(y_true, y_pred), 4),
        "macro_f1": round(macro_f1(y_true, y_pred), 4),
        "sensitivity_opacity": round(sens, 4) if sens is not None else None,
        "specificity_normal": round(spec, 4) if spec is not None else None,
        "json_valid_rate": round(sum(json_valid) / len(json_valid), 4) if rows else 0,
        "warning_rate": round(sum(warnings) / len(warnings), 4) if rows else 0,
        "uncertain_rate": round(sum(p == "uncertain" for p in y_pred) / len(y_pred), 4) if rows else 0,
        "median_latency_ms": round(median(latencies), 1) if latencies else None,
    }
