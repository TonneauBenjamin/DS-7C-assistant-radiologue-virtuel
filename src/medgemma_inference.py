"""Inférence MedGemma 4B au schéma JSON du projet.

Factorise le code validé du notebook de démo (Demo_MedGemma_Streamlit.ipynb)
pour que toute interface (medapp/TrueVision, app simple, API) puisse appeler
le vrai modèle. Nécessite un GPU ; sur T4 Colab, le chargement 8-bit prend
quelques minutes la première fois puis reste en cache.

Prototype pédagogique. Non destiné au diagnostic.
"""
from __future__ import annotations

import re
import time
from pathlib import Path
from typing import Any

from src.guardrails import WARNING_TEXT

MODEL_ID = "google/medgemma-4b-it"

PROMPTS = {
    "baseline": {
        "name": "baseline",
        "system": "You are an expert radiologist.",
        "user": "Look at this chest X-ray. Answer with exactly one word: NORMAL if the "
                "lungs are clear, or PNEUMONIA if there is a lung opacity or consolidation.",
        "max_new_tokens": 10,
    },
    "improved": {
        "name": "improved",
        "system": "You are an expert chest radiologist. Missing a pneumonia is dangerous, "
                  "so when there is ANY sign of opacity, consolidation or infiltrate, classify as PNEUMONIA.",
        "user": "Analyze this chest X-ray step by step, then end with a final line exactly in "
                "the form \"FINAL: NORMAL\" or \"FINAL: PNEUMONIA\".",
        "max_new_tokens": 160,
    },
}

_CACHE: dict[str, Any] = {}


def is_available() -> bool:
    """MedGemma n'est proposé que si un GPU CUDA et transformers sont présents."""
    try:
        import torch
        import transformers  # noqa: F401

        return torch.cuda.is_available()
    except Exception:
        return False


def load_model():
    """Charge MedGemma 8-bit une seule fois (singleton module)."""
    if "model" not in _CACHE:
        from transformers import AutoModelForImageTextToText, AutoProcessor, BitsAndBytesConfig

        _CACHE["processor"] = AutoProcessor.from_pretrained(MODEL_ID)
        _CACHE["model"] = AutoModelForImageTextToText.from_pretrained(
            MODEL_ID,
            quantization_config=BitsAndBytesConfig(load_in_8bit=True),
            device_map="auto",
        )
    return _CACHE["processor"], _CACHE["model"]


def _classify(txt: str, mode: str) -> tuple[str, float]:
    # Choix de conception : ne trancher que sur une ligne FINAL explicite. Toute
    # sortie improved ambiguë ou tronquée retombe volontairement sur `uncertain`
    # (défère à l'humain plutôt que de prendre le risque d'une classe erronée).
    up = txt.upper()
    m = re.search(r"FINAL\s*:\s*(PNEUMONIA|NORMAL)", up)
    if m:
        return ("suspected_opacity", 0.85) if m.group(1) == "PNEUMONIA" else ("normal", 0.80)
    if mode == "baseline":
        debut = up[:40]
        if "PNEUMON" in debut:
            return "suspected_opacity", 0.75
        if "NORMAL" in debut:
            return "normal", 0.75
    return "uncertain", 0.40


def predict_medgemma(image_path: Path | str, mode: str = "improved") -> dict[str, Any]:
    """Prédit au schéma du projet. `mode` ∈ {baseline, improved}.

    Les garde-fous (`apply_safety_guardrails`) sont appliqués par l'appelant.
    """
    import torch
    from PIL import Image

    cfg = PROMPTS[mode]
    processor, model = load_model()
    image = Image.open(image_path).convert("RGB")

    eot = processor.tokenizer.convert_tokens_to_ids("<end_of_turn>")
    pad = processor.tokenizer.pad_token_id or 0
    messages = [
        {"role": "system", "content": [{"type": "text", "text": cfg["system"]}]},
        {"role": "user", "content": [
            {"type": "text", "text": cfg["user"]},
            {"type": "image", "image": image},
        ]},
    ]
    inputs = processor.apply_chat_template(
        messages, add_generation_prompt=True, tokenize=True,
        return_dict=True, return_tensors="pt",
    ).to(model.device)
    input_len = inputs["input_ids"].shape[-1]
    t0 = time.time()
    with torch.inference_mode():
        gen = model.generate(**inputs, max_new_tokens=cfg["max_new_tokens"], do_sample=False,
                             eos_token_id=eot, pad_token_id=pad,
                             repetition_penalty=1.3, no_repeat_ngram_size=3)
    latency_ms = int((time.time() - t0) * 1000)
    txt = processor.decode(gen[0][input_len:], skip_special_tokens=True)
    pred, conf = _classify(txt, cfg["name"])
    return {
        "image_quality": "good", "predicted_class": pred, "confidence": conf,
        "visual_evidence": [txt.strip()[:160]] if txt.strip() else [],
        "justification": txt.strip()[:600],
        "limitations": ["no clinical context", "not a validated medical model", "pediatric dataset"],
        "warning": WARNING_TEXT,
        "model_name": f"medgemma-4b-it-{cfg['name']}",
        "prompt_version": f"{cfg['name']}_v1", "latency_ms": latency_ms,
    }
