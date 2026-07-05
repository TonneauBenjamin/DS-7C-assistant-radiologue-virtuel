from pathlib import Path

from src import medgemma_inference


def test_load_prompt_config_reads_prompt_file_contents(tmp_path, monkeypatch):
    prompt_file = tmp_path / "optimized_v2_final_prompt.txt"
    prompt_file.write_text(
        "SYSTEM:\nCustom system prompt\n\nUSER:\nCustom user prompt",
        encoding="utf-8",
    )

    monkeypatch.setattr(medgemma_inference, "PROMPTS_DIR", tmp_path)

    cfg = medgemma_inference.load_prompt_config("improved")

    assert cfg["system"] == "Custom system prompt"
    assert cfg["user"] == "Custom user prompt"
    assert cfg["name"] == "optimized_v2_final"


def test_extract_observations_and_justification_parses_structured_output():
    text = (
        "CLASS: suspected_opacity\n"
        "OBSERVATIONS:\n"
        "- Focal opacity in the right lower lung\n"
        "- Mild consolidation near the hilum\n"
        "JUSTIFICATION: These findings are compatible with pneumonia."
    )

    observations, justification = medgemma_inference._extract_observations_and_justification(text)

    assert observations == [
        "Focal opacity in the right lower lung",
        "Mild consolidation near the hilum",
    ]
    assert justification == "These findings are compatible with pneumonia."


def test_extract_observations_and_justification_falls_back_when_response_is_sparse():
    observations, justification = medgemma_inference._extract_observations_and_justification("NORMAL")

    assert observations == ["No clear abnormality was identified in the image."]
    assert "classification" in justification.lower() or "normal" in justification.lower()
