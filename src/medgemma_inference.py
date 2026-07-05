"""Inférence MedGemma 4B au schéma JSON du projet.

Factorise le code évalué du notebook principal (notebooks/MedGemma_Radios_final.ipynb :
prompts baseline / optimized_v2_final, classification par mots-clés, règles
d'incertitude) pour que toute interface (medapp/TrueVision, API) déploie exactement
la version mesurée dans docs/resultats/baseline_vs_v2_final.csv. Nécessite un GPU ;
sur T4 Colab, le chargement 8-bit prend quelques minutes la première fois puis reste
en cache.

Prototype pédagogique. Non destiné au diagnostic.
"""
from __future__ import annotations

import re
import time
from pathlib import Path
from typing import Any

from src.guardrails import WARNING_TEXT

MODEL_ID = "google/medgemma-4b-it"
PROMPTS_DIR = Path(__file__).resolve().parents[1] / "prompts"


def _read_prompt_file(filename: str) -> tuple[str, str]:
    path = PROMPTS_DIR / filename
    if not path.exists():
        raise FileNotFoundError(f"Prompt file not found: {path}")
    content = path.read_text(encoding="utf-8").strip()
    if "\n\n" not in content:
        raise ValueError(f"Prompt file {path} must contain SYSTEM/USER sections")
    sections = [section.strip() for section in content.split("\n\n", 1)]
    system = ""
    user = ""
    for section in sections:
        if section.upper().startswith("SYSTEM:"):
            system = section.split(":", 1)[1].strip()
        elif section.upper().startswith("USER:"):
            user = section.split(":", 1)[1].strip()
    if not system or not user:
        raise ValueError(f"Prompt file {path} is missing SYSTEM or USER content")
    return system, user


def load_prompt_config(mode: str) -> dict[str, Any]:
    """Charge la configuration de prompt depuis les fichiers du dépôt."""
    if mode == "baseline":
        return {
            "name": "baseline",
            "version": "baseline_v1",
            "system": "You are an expert radiologist.",
            "user": "Look at this chest X-ray. Answer with exactly one word: NORMAL if the "
                    "lungs are clear, or PNEUMONIA if there is a lung opacity or consolidation.",
            "max_new_tokens": 10,
        }

    if mode == "improved":
        prompt_candidates = ["improved_prompt.txt", "optimized_v2_final_prompt.txt"]
        for filename in prompt_candidates:
            try:
                system, user = _read_prompt_file(filename)
                return {
                    "name": "optimized_v2_final",
                    "version": "optimized_v2_final_v1",
                    "system": system,
                    "user": user,
                    "max_new_tokens": 80,
                }
            except FileNotFoundError:
                continue
        raise FileNotFoundError(
            f"No improved prompt file found in {PROMPTS_DIR}; tried {prompt_candidates}"
        )

    raise ValueError(f"Unknown mode: {mode}")


PROMPTS = {
    "baseline": load_prompt_config("baseline"),
    "improved": load_prompt_config("improved"),
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


def _extract_observations_and_justification(txt: str) -> tuple[list[str], str]:
    """Extrait des observations et une justification à partir du texte généré.

    Le modèle peut répondre sous forme libre, ou avec un schéma simple en lignes.
    Cette fonction tente d'abord de reconnaître des sections explicites
    OBSERVATIONS/JUSTIFICATION, puis retombe sur un texte libre ou un fallback
    minimal pour éviter d'afficher un champ vide.
    """
    text = (txt or "").strip()
    if not text:
        return ["Aucune observation claire n'a pu être extraite de l'image."], "Le modèle n'a pas produit de justification exploitable."

    lines = [line.strip() for line in text.splitlines() if line.strip()]

    obs: list[str] = []
    justification = ""

    section = None
    for line in lines:
        upper = line.upper()
        if upper.startswith("OBSERVATIONS") or upper.startswith("- OBSERVATIONS"):
            section = "obs"
            continue
        if upper.startswith("JUSTIFICATION") or upper.startswith("- JUSTIFICATION"):
            section = "just"
            remainder = line.split(":", 1)[1].strip() if ":" in line else ""
            if remainder:
                justification = remainder
            continue
        if upper.startswith("CLASS") or upper.startswith("DIAGNOSIS") or upper.startswith("CONCLUSION"):
            section = None
            continue

        if section == "obs":
            cleaned = re.sub(r"^[-*•]\s*", "", line).strip()
            if cleaned and not cleaned.upper().startswith("JUSTIFICATION"):
                obs.append(cleaned)
        elif section == "just":
            if not justification:
                justification = line
            else:
                justification = f"{justification} {line}"

    if obs:
        return obs, justification.strip() or "The model identified suspicious visual findings and summarized them below."

    # Fallback: try to reuse the whole response as a justification and create a generic observation.
    if justification:
        return ["A visual abnormality was reported by the model."], justification.strip()

    if re.search(r"\b(PNEUMONIA|OPACITY|CONSOLIDATION|INFILTRATE|ABNORMAL|NORMAL)\b", text, re.I):
        label = "suspicious findings" if re.search(r"\b(PNEUMONIA|OPACITY|CONSOLIDATION|INFILTRATE|ABNORMAL)\b", text, re.I) else "no clear abnormality"
        if label == "suspicious findings":
            return ["The model detected signs of abnormality in the X-ray."], text[:300]
        return ["No clear abnormality was identified in the image."], text[:300]

    return ["No clear observation could be extracted from the image."], text[:300] or "The model did not produce a usable justification."


def _classify(txt: str, mode: str) -> tuple[str, float]:
    """Extrait (classe, confiance) du texte généré.

    Portage à l'identique de la fonction `classer` du notebook principal :
    on ne tranche que sur des mots-clés explicites, tout le reste retombe sur
    `uncertain` — on défère à l'humain plutôt que de deviner.
    """
    up = txt.upper()

    if mode == "baseline":
        m = re.search(r"(?:FINAL|CONCLUSION|ANSWER|DIAGNOSIS)[^:]*:\s*\**\s*(PNEUMONIA|NORMAL)", up)
        if m:
            return ("suspected_opacity", 0.85) if m.group(1) == "PNEUMONIA" else ("normal", 0.80)
        debut = up[:40]
        if "PNEUMON" in debut:
            return ("suspected_opacity", 0.75)
        if "NORMAL" in debut:
            return ("normal", 0.75)
        hits = re.findall(r"PNEUMON\w*|NORMAL", up)
        if hits:
            return ("suspected_opacity", 0.65) if hits[-1].startswith("PNEUMON") else ("normal", 0.65)
        return ("uncertain", 0.40)

    # Mode optimized_v2_final : mots-clés anormaux comptés, issue `uncertain` conservée.
    abnormal_keywords = [
        r"OPACIT[YE]", r"CONSOLIDATION", r"INFILTRAT",
        r"ANOMALIE", r"ABNORMAL", r"HAZY", r"DENSITY",
        r"INFECT", r"CONSOLID", r"INFILTR", r"OPACITY",
        r"ABNORM", r"INFECTION", r"PNEUMON",
    ]
    abnormal_hits = sum(1 for p in abnormal_keywords if re.search(p, up))
    has_normal = re.search(r"\bNORMAL\b", up)

    if re.search(r"\bPNEUMONIA\b", up):
        return ("suspected_opacity", 0.90)
    if abnormal_hits >= 2:
        return ("suspected_opacity", 0.85)
    if abnormal_hits == 1:
        return ("suspected_opacity", 0.72)
    if re.search(r"NO\s+(?:SIGN|EVIDENCE|ABNORMALITY|PATHOLOGY)", up):
        if not re.search(r"BUT|HOWEVER|ALTHOUGH", up):
            return ("normal", 0.85)
    if has_normal:
        weakeners = [r"SLIGHT", r"MILD", r"MINIMAL", r"SUBTLE", r"EARLY", r"BEGINNING"]
        if any(re.search(w, up) for w in weakeners):
            return ("suspected_opacity", 0.65)  # anomalie légère -> signalée par prudence
        return ("normal", 0.85)
    uncertain_patterns = [
        r"UNCERTAIN", r"MAYBE", r"POSSIBLE", r"PROBABLY",
        r"COULD BE", r"MIGHT BE", r"AMBIGUOUS", r"UNCLEAR",
        r"NOT CLEAR", r"DIFFICULT TO", r"HARD TO", r"CANNOT DETERMINE",
    ]
    if any(re.search(p, up) for p in uncertain_patterns):
        return ("uncertain", 0.50)
    return ("uncertain", 0.45)


def predict_medgemma(image_path: Path | str, mode: str = "improved") -> dict[str, Any]:
    """Prédit au schéma du projet. `mode` ∈ {baseline, improved}.

    Le mode "improved" applique le prompt `optimized_v2_final` du notebook.
    Les garde-fous (`apply_safety_guardrails`) sont appliqués par l'appelant.
    """
    import torch
    from PIL import Image

    cfg = load_prompt_config(mode)
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
        gen = model.generate(**inputs, max_new_tokens=cfg["max_new_tokens"],
                             do_sample=False, eos_token_id=eot, pad_token_id=pad,
                             repetition_penalty=1.3, no_repeat_ngram_size=3)
    latency_ms = int((time.time() - t0) * 1000)
    txt = processor.decode(gen[0][input_len:], skip_special_tokens=True)
    pred, conf = _classify(txt, cfg["name"])
    observations, justification = _extract_observations_and_justification(txt)
    return {
        "image_quality": "good", "predicted_class": pred, "confidence": conf,
        "visual_evidence": observations,
        "justification": justification,
        "limitations": ["no clinical context", "not a validated medical model", "pediatric dataset"],
        "warning": WARNING_TEXT,
        "model_name": f"medgemma-4b-it-{cfg['name']}",
        "prompt_version": cfg["version"], "latency_ms": latency_ms,
    }
