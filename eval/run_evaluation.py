from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DATASET_PATH = ROOT / "data" / "synthetic_cases.csv"

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.database import init_db, insert_run
from src.guardrails import apply_safety_guardrails, validate_prediction
from src.inference import toy_predict
from src.metrics import summarize_metrics


def run_evaluation(mode: str, out_dir: str | Path, db_path: str | Path) -> list[dict[str, Any]]:
    out_dir = Path(out_dir)
    db_path = Path(db_path)
    out_dir.mkdir(parents=True, exist_ok=True)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    init_db(db_path)

    summary_rows: list[dict[str, Any]] = []
    for eval_mode in ("baseline", "improved"):
        rows: list[dict[str, Any]] = []
        with DATASET_PATH.open("r", encoding="utf-8", newline="") as handle:
            cases = list(csv.DictReader(handle))

        for case in cases:
            image_path = ROOT / case["image_path"]
            pred = apply_safety_guardrails(toy_predict(image_path, mode=eval_mode))
            valid, _errors = validate_prediction(pred)
            rows.append(
                {
                    "case_id": case["case_id"],
                    "label": case["label"],
                    "predicted_class": pred["predicted_class"],
                    "json_valid": valid,
                    "warning": bool(pred.get("warning")),
                }
            )
            insert_run(
                db_path,
                case_id=case["case_id"],
                image_path=case["image_path"],
                prediction={
                    "model_name": pred.get("model_name"),
                    "prompt_version": pred.get("prompt_version"),
                    "predicted_class": pred.get("predicted_class"),
                    "confidence": pred.get("confidence"),
                    "latency_ms": pred.get("latency_ms"),
                },
            )

        summary = summarize_metrics(rows)
        summary_rows.append({"mode": eval_mode, **summary})

    summary_path = out_dir / "before_after_summary.csv"
    with summary_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["mode", "n", "json_valid_rate", "warning_rate", "accuracy", "uncertain_rate"])
        writer.writeheader()
        writer.writerows(summary_rows)

    return summary_rows


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the toy evaluation pipeline.")
    parser.add_argument("--mode", default="toy", choices=["toy", "baseline", "improved"])
    parser.add_argument("--out-dir", default=str(ROOT / "eval" / "outputs"))
    parser.add_argument("--db-path", default=str(ROOT / "medical_ai_evidence.sqlite"))
    args = parser.parse_args()

    summary_rows = run_evaluation(args.mode, args.out_dir, args.db_path)
    print(json.dumps(summary_rows, ensure_ascii=False))


if __name__ == "__main__":
    main()
