from __future__ import annotations

from typing import Any


def summarize_metrics(rows: list[dict[str, Any]]) -> dict[str, float]:
    """Summarize evaluation rows with simple, transparent metrics."""
    n = len(rows)
    if n == 0:
        return {
            "n": 0,
            "json_valid_rate": 0.0,
            "warning_rate": 0.0,
            "accuracy": 0.0,
            "uncertain_rate": 0.0,
        }

    json_valid_rate = sum(1 for row in rows if row.get("json_valid")) / n
    warning_rate = sum(1 for row in rows if row.get("warning")) / n
    accuracy = sum(
        1
        for row in rows
        if row.get("predicted_class") and row.get("label") and row.get("predicted_class") == row.get("label")
    ) / n
    uncertain_rate = sum(1 for row in rows if row.get("predicted_class") == "uncertain") / n

    return {
        "n": n,
        "json_valid_rate": json_valid_rate,
        "warning_rate": warning_rate,
        "accuracy": accuracy,
        "uncertain_rate": uncertain_rate,
    }
