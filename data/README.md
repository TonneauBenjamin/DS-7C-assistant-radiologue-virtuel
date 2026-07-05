# Données

Ce dossier contient un jeu **synthétique jouet** (validation du pipeline logiciel)
et un petit jeu de **cas réels publics** (évaluation baseline vs improved). Aucune
donnée patient identifiante.

## `real_cases.csv` — cas réels (évaluation)

24 radiographies thoraciques frontales (12 `normal` + 12 `suspected_opacity`)
tirées du dataset public Kaggle *chest-xray-pneumonia* (licence CC BY 4.0,
`source = kaggle_pneumonia_ccby4`). Préparation : téléchargement via `kagglehub`,
échantillonnage équilibré, conversion RGB et renommage au format du projet — voir
`notebooks/MedGemma_Radios_final.ipynb`. C'est le **même jeu d'images** qui sert à
comparer les prompts `baseline_v1` et `improved_v2`
(résultats : `docs/resultats/baseline_vs_v2_final.csv`). Limite connue : dataset
pédiatrique, listé dans les `limitations` de chaque sortie JSON.

## `synthetic_cases.csv`

Colonnes :

- `case_id`
- `image_path`
- `source`
- `label`
- `split`
- `quality`
- `notes`

## Images synthétiques

Les images dans `sample_images/` imitent grossièrement une radiographie thoracique uniquement pour vérifier les flux de code. Elles ne doivent pas être utilisées pour évaluer une performance médicale.
