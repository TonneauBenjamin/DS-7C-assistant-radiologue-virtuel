# Assistant radiologue virtuel responsable

> **Auteurs :** Benjamin Tonneau, Jules Zivkovic, Jingfan Xiao, Kogulaan Vimalan, Tony Vara, Antonin Victorion   
> **Solution Delivery - Filière Data**  
> **École :** EFREI  
> **Année académique :** 2025-2026

## Contexte

Prototype pédagogique d'IA médicale multimodale pour apprendre à construire une chaîne **prudente, traçable et évaluée** autour d'une radiographie thoracique frontale.

---

>  **Position non clinique.** Ce dépôt n'est pas un dispositif médical. Il ne doit jamais être utilisé pour diagnostiquer, trier ou orienter un patient. Toute sortie doit rester un résultat expérimental, vérifié par un professionnel qualifié.

---

## Contrat du projet

| Élément | Cadrage |
|---|---|
| Entrée | Une radiographie thoracique frontale |
| Sorties | `normal`, `suspected_opacity`, `uncertain` |
| Preuve minimale | JSON valide, warning, logs, métriques, cas d'erreur |
| Données | Synthétiques ou publiques, autorisées et dé-identifiées |
| Finalité | Prototype éducatif de data/IA, pas aide au diagnostic réelle |

Le bon rendu ne cherche pas à impressionner par un modèle spectaculaire. Il démontre une méthode : périmètre limité, baseline reproductible, garde-fous, évaluation, analyse d'erreurs et limites explicites.

## Démarrage rapide

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt -r medapp/requirements.txt
streamlit run medapp/app.py
```

## Smoke test du dépôt

Avant une soutenance, un push ou une livraison, lancer le contrôle court :

```bash
pip install -r requirements.txt
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -q
python -m compileall -q src api medapp eval finetuning tests
```

Ce smoke test vérifie la structure du dépôt, le contrat du dataset synthétique, le schéma de sortie, les garde-fous, l'API de démonstration et la compilation Python.

## Pipeline MedGemma (notebook principal)

Le notebook [`notebooks/MedGemma_Radios_final.ipynb`](notebooks/MedGemma_Radios_final.ipynb)
contient la chaîne complète sur cas réels (pensé pour Colab GPU, chargement 8-bit) :

1. **Modèle** : `google/medgemma-4b-it` quantifié 8-bit (*gated* — accepter les
   conditions sur Hugging Face puis se connecter avec un token).
2. **Données** : 24 radiographies réelles (12 `normal` + 12 `suspected_opacity`)
   tirées du dataset Kaggle *chest-xray-pneumonia*, converties au format du projet
   (`data/real_cases.csv`).
3. **Prompts versionnés** : `baseline_v1` (réponse en un mot) vs `improved_v2`
   (gabarit d'ancrage visuel + issue `UNCERTAIN` + confiance auto-déclarée),
   archivés dans [`prompts/baseline_prompt.txt`](prompts/baseline_prompt.txt) et
   [`prompts/improved_prompt.txt`](prompts/improved_prompt.txt).
4. **Évaluation** : accuracy, macro-F1, sensibilité/spécificité, matrice de
   confusion, registre d'erreurs FP/FN — sorties dans [`docs/resultats/`](docs/resultats/).

## Interface clinique complète (medapp)

Une interface plus aboutie (TrueVision) est disponible dans `medapp/` : comptes
et rôles (patient / professionnel / admin), dossiers patients, analyse d'images
branchée sur le pipeline du dépôt (`src/medgemma_inference` + `src/guardrails`) avec
historique, et tableau de bord.

```bash
pip install -r medapp/requirements.txt
streamlit run medapp/app.py
```

Zéro configuration en mode démo local (SQLite) — compte de test :
`admin@demo.local` / `admin`. Pour le mode Supabase (auth + Postgres + stockage),
voir `medapp/README.md`.

## API de démonstration

```bash
uvicorn api.main:app --reload
```

Exemple :

```bash
curl -X POST "http://127.0.0.1:8000/predict" \
  -F "file=@data/sample_images/CXR_SYN_002_suspected_opacity.png"
```

La réponse doit contenir une classe, une confiance, des observations visuelles, une justification, des limites et l'avertissement non clinique.

## Résultats

- **Registre d'erreurs analysé** : [`eval/error_register_filled.csv`](eval/error_register_filled.csv)
  — les 8 faux négatifs restants, avec commentaire et action corrective pour chacun.
- **Comparaison baseline vs improved** : [`docs/resultats/before_after_real.csv`](docs/resultats/before_after_real.csv)
  — à modèle constant, sensibilité opacités ×2 (0.17 → 0.33), accuracy 0.58 → 0.67,
  100 % JSON valide, 100 % warning.

## Organisation

```text
assistant-radiologue-virtuel/
├── README.md
├── Demo_MedGemma_Streamlit.ipynb  # démo Streamlit (Colab)
├── docs/          # appel d'offre, architecture, éthique, évaluation, résultats
├── data/          # cas synthétiques, cas réels (Kaggle) et images jouet
├── prompts/       # prompt baseline, prompt amélioré (notebook MedGemma), schéma JSON
├── src/           # inférence MedGemma, garde-fous, prétraitement, SQLite
├── api/           # FastAPI
├── medapp/        # interface clinique complète (TrueVision)
├── sql/           # schéma SQL (traçabilité des prédictions)
├── eval/          # métriques et registre d'erreurs
├── tests/         # smoke tests et contrat minimal
├── notebooks/     # MedGemma_Radios_final.ipynb : pipeline complet baseline vs improved
└── finetuning/    # stubs expérimentaux, non obligatoires
```

## Livrables attendus

| Niveau | Attendu |
|---|---|
| **MUST** | Baseline reproductible, sortie JSON valide, warning obligatoire, logs, métriques, mini-rapport |
| **SHOULD** | Prompt amélioré, règle d'incertitude, comparaison baseline/amélioration, analyse d'erreurs |
| **COULD** | LoRA expérimental, MedGemma/PEFT, localisation visuelle, ablations de prompts |

## Références techniques

Les pistes avancées doivent rester expérimentales, traçables et justifiées. En particulier, un groupe qui mobilise Gemma, MedGemma, Unsloth, MIMIC-CXR ou CheXpert doit citer la source exacte, la version, les conditions d'accès et les limites d'usage.

| Ressource | Usage possible | Référence à citer |
|---|---|---|
| Unsloth - Gemma 4 | Fine-tuning LoRA/QLoRA expérimental, uniquement après une baseline simple | [Guide Gemma 4](https://unsloth.ai/docs/models/gemma-4/train), [catalogue des modèles](https://unsloth.ai/docs/get-started/unsloth-model-catalog), [blog Unsloth](https://unsloth.ai/blog) |
| MedGemma | Baseline ou adaptation médicale image-texte, avec prudence sur les conditions d'accès | [Model card Hugging Face](https://huggingface.co/google/medgemma-4b-pt) |
| MIMIC-CXR / MIMIC-CXR-JPG | Jeu de données de radiographies thoraciques, accès contrôlé et non redistribuable | [MIMIC-CXR](https://physionet.org/content/mimic-cxr/2.1.0/), [MIMIC-CXR-JPG](https://physionet.org/content/mimic-cxr-jpg/2.1.0/) |
| CheXpert | Jeu de données public de radiographies thoraciques avec rapports associés | [Stanford AIMI - CheXpert](https://aimi.stanford.edu/datasets/chexpert-chest-x-rays) |

## Points de vigilance

- Ne pas inventer d'information clinique absente de l'image.
- Ne pas supprimer la classe `uncertain`; elle est un garde-fou, pas un échec.
- Ne pas afficher uniquement des réussites en soutenance.
- Ne jamais commiter de données patient réelles, identifiantes ou ambiguës.
- Ne pas présenter le prototype comme validé médicalement.

## Licence et sources externes

Le code pédagogique du dépôt est publié sous licence MIT. **Les datasets externes, modèles et bibliothèques utilisés conservent leurs licences propres** : les étudiants doivent vérifier et documenter les droits d'usage avant toute expérimentation.

Exigence minimale : indiquer dans le rapport la source, la version, la licence ou les conditions d'accès, les restrictions de redistribution, les traitements d'anonymisation et les limites d'interprétation. Aucun fichier patient réel, même pseudonymisé, ne doit être ajouté au dépôt sans autorisation explicite et traçable.
