from __future__ import annotations

import compileall
import csv
from pathlib import Path
import shutil

from fastapi.testclient import TestClient

from api.main import app
from api.main import health
from src.guardrails import WARNING_TEXT, apply_safety_guardrails, validate_prediction
from src.medgemma_inference import is_available
from src.metrics import summarize_metrics


ROOT = Path(__file__).resolve().parents[1]


def test_repository_student_contract_is_present() -> None:
    required_paths = [
        "README.md",
        "requirements.txt",
        ".github/workflows/ci.yml",
        "docs/appel_offre.md",
        "docs/architecture.md",
        "docs/ethique_et_limites.md",
        "docs/evaluation_protocol.md",
        "data/synthetic_cases.csv",
        "src/medgemma_inference.py",
        "src/guardrails.py",
        "api/main.py",
        "prompts/json_schema.md",
        "prompts/baseline_prompt.txt",
        "prompts/improved_prompt.txt",
        "prompts/optimized_v2_final_prompt.txt",
    ]
    forbidden_paths = [
        ".rollback_appel_offre_cleanup_20260516_205745",
        "VALIDATION_REPORT.md",
        "create_remote_repo.sh",
        "docs/expert_review_integration.md",
        "docs/github_push_instructions.md",
        "eval/outputs",
        "medical_ai_evidence.sqlite",
        "assets/assistant_radiologue_v3_notes_professeur_fr.pptx",
        "assets/notes_orales_assistant_radiologue_v3_style_professeur_fr.md",
    ]

    missing = [path for path in required_paths if not (ROOT / path).exists()]
    forbidden = [path for path in forbidden_paths if (ROOT / path).exists()]

    assert missing == []
    assert forbidden == []


def test_synthetic_dataset_contract_is_valid() -> None:
    path = ROOT / "data" / "synthetic_cases.csv"
    required_columns = {"case_id", "image_path", "source", "label", "split", "quality", "notes"}
    allowed_labels = {"normal", "suspected_opacity", "uncertain"}

    with path.open("r", encoding="utf-8", newline="") as file:
        rows = list(csv.DictReader(file))

    assert len(rows) >= 20
    assert required_columns <= set(rows[0])
    assert {row["label"] for row in rows} <= allowed_labels
    for row in rows:
        assert row["source"] == "synthetic_toy"
        assert (ROOT / row["image_path"]).exists()


def test_prediction_schema_warning_and_guardrails() -> None:
    pred = apply_safety_guardrails(
        {
            "image_quality": "good",
            "predicted_class": "suspected_opacity",
            "confidence": 0.85,
            "visual_evidence": ["right lower lobe opacity"],
            "justification": "Opacité focale compatible avec une pneumonie.",
            "limitations": ["no clinical context", "not a validated medical model"],
            "warning": WARNING_TEXT,
        }
    )
    valid, errors = validate_prediction(pred)

    assert valid, errors
    assert pred["predicted_class"] in {"normal", "suspected_opacity", "uncertain"}
    assert pred["warning"] == WARNING_TEXT
    assert "not a validated medical model" in pred["limitations"]


def test_python_source_tree_compiles() -> None:
    for folder in ("src", "api", "medapp", "finetuning", "tests"):
        assert compileall.compile_dir(ROOT / folder, quiet=1)


def test_invalid_model_output_falls_back_to_uncertain() -> None:
    pred = apply_safety_guardrails({"predicted_class": "diagnosis", "confidence": 0.99})

    assert pred["predicted_class"] == "uncertain"
    assert pred["confidence"] <= 0.5
    assert pred["warning"] == WARNING_TEXT
    assert pred["guardrail_errors"]


def test_metrics_and_api_health_contract() -> None:
    rows = [
        {"label": "normal", "predicted_class": "normal", "json_valid": True, "warning": WARNING_TEXT},
        {"label": "suspected_opacity", "predicted_class": "uncertain", "json_valid": True, "warning": WARNING_TEXT},
    ]
    metrics = summarize_metrics(rows)

    assert health()["status"] == "ok"
    assert health()["scope"] == "educational prototype, not diagnosis"
    assert metrics["n"] == 2
    assert metrics["json_valid_rate"] == 1.0
    assert metrics["warning_rate"] == 1.0


def test_api_predict_requires_gpu_or_returns_prediction() -> None:
    client = TestClient(app)
    image_path = ROOT / "data" / "sample_images" / "CXR_SYN_002_suspected_opacity.png"

    with image_path.open("rb") as file:
        response = client.post(
            "/predict",
            files={"file": (image_path.name, file, "image/png")},
        )

    if not is_available():
        # Sans GPU CUDA, l'API doit refuser proprement plutôt que planter.
        assert response.status_code == 503
    else:
        payload = response.json()
        assert response.status_code == 200
        assert payload["predicted_class"] in {"normal", "suspected_opacity", "uncertain"}
        assert payload["warning"] == WARNING_TEXT
    shutil.rmtree(ROOT / "tmp_uploads", ignore_errors=True)
