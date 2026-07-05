# Architecture cible
> **Author :** Badr TAJINI 
> **Solution Delivery - filière Data** 
>  **Année académique :** 2025-2026
## Pipeline

```text
Image upload → Preprocessing → MedGemma 4B (VLM) → Guardrails → JSON → UI → SQLite logs
```

## Composants

- `src/preprocessing.py` : validation de fichier, chargement image, resizing.
- `src/medgemma_inference.py` : inférence MedGemma 4B (prompts baseline/improved, GPU requis).
- `src/guardrails.py` : validation JSON, warning, incertitude.
- `src/metrics.py` : accuracy, macro-F1, sensibilité, spécificité, validité JSON.
- `src/database.py` : initialisation SQLite et stockage des runs.
- `api/main.py` : endpoint FastAPI `/predict`.
- `medapp/app.py` : interface clinique TrueVision (Streamlit).

## Endpoint attendu

```http
POST /predict
Content-Type: multipart/form-data
```

Réponse :

```json
{
  "predicted_class": "normal | suspected_opacity | uncertain",
  "confidence": 0.0,
  "visual_evidence": [],
  "justification": "...",
  "limitations": [],
  "warning": "Prototype pédagogique. Non destiné au diagnostic. Validation par un professionnel qualifié requise.",
  "model_name": "medgemma-4b-it-improved",
  "prompt_version": "improved_v1",
  "latency_ms": 0
}
```

## Objectifs d'intégration

- '>= 95 %' JSON valide.
- 100 % des sorties avec warning.
- 100 % des runs sauvegardés.
- Latence cible < 10 s en mode prototype.
