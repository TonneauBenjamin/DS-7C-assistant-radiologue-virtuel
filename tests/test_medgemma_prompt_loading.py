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
