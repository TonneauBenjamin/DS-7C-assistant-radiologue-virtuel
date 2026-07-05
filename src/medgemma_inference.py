"""Inférence MedGemma 4B au schéma JSON du projet.

Factorise le code évalué du notebook principal (notebooks/MedGemma_Radios_final.ipynb :
prompts baseline_v1 / improved_v2, parsing du gabarit, règles d'incertitude) pour
que toute interface (medapp/TrueVision, API) déploie exactement la version mesurée
dans docs/resultats/baseline_vs_v2_final.csv. Nécessite un GPU ; sur T4 Colab, le
chargement 8-bit prend quelques minutes la première fois puis reste en cache.

Prototype pédagogique. Non destiné au diagnostic.
"""
from __future__ import annotations

import re
import time
from pathlib import Path
from typing import Any

from src.guardrails import WARNING_TEXT

MODEL_ID = "google/medgemma-4b-it"

# Mêmes prompts que prompts/baseline_prompt.txt et prompts/improved_prompt.txt,
# c'est-à-dire les versions évaluées dans notebooks/MedGemma_Radios_final.ipynb
# (résultats : docs/resultats/baseline_vs_v2_final.csv).
PROMPTS = {
    "baseline": {
        "name": "baseline",
        "version": "baseline_v1",
        "system": "You are an expert radiologist.",
        "user": "Look at this chest X-ray. Answer with exactly one word: NORMAL if the "
                "lungs are clear, or PNEUMONIA if there is a lung opacity or consolidation.",
        "max_new_tokens": 10,
    },
    "improved": {
        "name": "improved",
        "version": "improved_v2",
        "system": ("You are a meticulous radiology assistant in an educational project. "
                   "You never give a diagnosis; a qualified clinician always reviews your output. "
                   "Missing a real lung opacity is the most harmful error, so inspect both lungs "
                   "carefully before answering. Only answer NORMAL when both lung fields are "
                   "clearly and symmetrically clear. If the image is unreadable or the findings "
                   "are ambiguous, answer UNCERTAIN instead of guessing."),
        "user": ("Examine this frontal chest X-ray and reply using EXACTLY this template, "
                 "one line each, no extra text. On the FINAL line write ONE single word.\n"
                 "QUALITY: good, limited or poor\n"
                 "RIGHT LUNG: clear, or describe any opacity/consolidation/infiltrate\n"
                 "LEFT LUNG: clear, or describe any opacity/consolidation/infiltrate\n"
                 "EVIDENCE: one short sentence citing only what is visible in this image\n"
                 "FINAL: NORMAL or PNEUMONIA or UNCERTAIN\n"
                 "CONFIDENCE: low, medium or high\n"
                 "Rules: any focal opacity, consolidation or infiltrate means FINAL: PNEUMONIA. "
                 "Base FINAL only on the visible evidence above, never on assumptions. "
                 "If you cannot decide from the image alone, write FINAL: UNCERTAIN."),
        "max_new_tokens": 160,
    },
}

# Confiance auto-déclarée par le modèle -> score chiffré traçable dans le JSON.
CONF = {
    ("PNEUMONIA", "HIGH"): 0.85, ("NORMAL", "HIGH"): 0.80,
    ("PNEUMONIA", "MEDIUM"): 0.65, ("NORMAL", "MEDIUM"): 0.65,
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
    """Extrait (classe, confiance) du texte généré.

    Principe « ne jamais mentir » : on ne tranche que sur une ligne de conclusion
    explicite et non ambiguë. Tout le reste (ligne absente, plusieurs classes sur
    la même ligne, confiance LOW) retombe sur `uncertain` — on défère à l'humain
    plutôt que de deviner.
    """
    up = txt.upper()
    m = re.search(r"(?:FINAL|CONCLUSION|ANSWER|DIAGNOSIS)[^:\n]*:([^\n]*)", up)
    if m:
        trouves = set(re.findall(r"PNEUMONIA|NORMAL|UNCERTAIN", m.group(1)))
        if len(trouves) == 1:               # une seule classe citée = conclusion nette
            klass = trouves.pop()
            if klass == "UNCERTAIN":
                return "uncertain", 0.40
            c = re.search(r"CONFIDENCE[^:\n]*:[\s\*]*(LOW|MEDIUM|HIGH)", up)
            level = c.group(1) if c else "MEDIUM"
            if level == "LOW":              # confiance faible assumée => on ne tranche pas
                return "uncertain", 0.45
            conf = CONF[(klass, level)]
            return ("suspected_opacity", conf) if klass == "PNEUMONIA" else ("normal", conf)
    # Baseline : réponse en un seul mot, on lit le début.
    if mode == "baseline":
        debut = up[:40]
        if "PNEUMON" in debut:
            return "suspected_opacity", 0.75
        if "NORMAL" in debut:
            return "normal", 0.75
    # Rien d'exploitable : incertitude assumée (garde-fou conservé).
    return "uncertain", 0.40


def _extract_fields(txt: str) -> tuple[str, list[str]]:
    """Qualité d'image et observations lisibles depuis les lignes du gabarit."""
    quality = "good"
    q = re.search(r"QUALITY[^:\n]*:[\s\*]*(GOOD|LIMITED|POOR)", txt.upper())
    if q:
        quality = q.group(1).lower()
    evidence = []
    for tag in ("RIGHT LUNG", "LEFT LUNG", "EVIDENCE"):
        m = re.search(rf"{tag}[^:\n]*:[\s\*]*([^\n]+)", txt, re.IGNORECASE)
        if m:
            evidence.append(f"{tag.lower()}: {m.group(1).strip().strip('*')[:120]}")
    return quality, evidence


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
        # Greedy pur : pas de repetition_penalty ni no_repeat_ngram_size — sur une
        # sortie à gabarit fixe, ces pénalités peuvent empêcher le modèle de
        # réécrire "PNEUMONIA" sur la ligne FINAL alors qu'il l'a cité plus haut.
        gen = model.generate(**inputs, max_new_tokens=cfg["max_new_tokens"],
                             do_sample=False, eos_token_id=eot, pad_token_id=pad)
    latency_ms = int((time.time() - t0) * 1000)
    txt = processor.decode(gen[0][input_len:], skip_special_tokens=True)
    pred, conf = _classify(txt, cfg["name"])
    quality, evidence = _extract_fields(txt)
    return {
        "image_quality": quality, "predicted_class": pred, "confidence": conf,
        "visual_evidence": evidence or ([txt.strip()[:160]] if txt.strip() else []),
        "justification": txt.strip()[:300],
        "limitations": ["no clinical context", "not a validated medical model", "pediatric dataset"],
        "warning": WARNING_TEXT,
        "model_name": f"medgemma-4b-it-{cfg['name']}",
        "prompt_version": cfg["version"], "latency_ms": latency_ms,
    }
