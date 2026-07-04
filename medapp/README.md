# TrueVision — interface clinique (Streamlit + Supabase)

Interface d'aide à la lecture de radiographies thoraciques, branchée sur le
pipeline d'analyse du projet. Gestion des comptes et des rôles, dossiers
patients, analyse d'images avec historique, et tableau de bord.

> ⚠️ Prototype pédagogique. Non destiné au diagnostic. Toute décision doit être
> validée par un professionnel qualifié.

## Deux modes de fonctionnement

L'application détecte automatiquement sa configuration :

- **Mode démo local** (par défaut, zéro configuration) : SQLite + images sur
  disque. Idéal pour lancer l'interface immédiatement ou faire une démonstration.
  Compte admin de test : `admin@demo.local` / `admin`.
- **Mode Supabase** : dès que `.streamlit/secrets.toml` contient des identifiants
  valides, l'app utilise l'authentification, la base Postgres et le stockage
  Supabase.

## Lancer en mode démo (immédiat)

```bash
pip install -r medapp/requirements.txt
streamlit run medapp/app.py
```

Ouvre l'URL affichée, connecte-toi avec `admin@demo.local` / `admin`, ou crée
un compte (Patient : actif immédiatement · Professionnel : à valider par un
admin dans l'onglet Administration).

## Passer en mode Supabase

1. Crée un projet sur https://supabase.com
2. Dans **SQL Editor**, colle et exécute `medapp/supabase/schema.sql`
   (crée tables, rôles, politiques RLS et le bucket d'images `radios`).
3. Copie `medapp/.streamlit/secrets.toml.example` en
   `medapp/.streamlit/secrets.toml` et renseigne :
   - `supabase_url` : Project Settings → API → URL
   - `supabase_anon_key` : Project Settings → API → clé `anon public`
4. Relance `streamlit run medapp/app.py`.
5. Inscris-toi via l'interface, puis promeus-toi admin (SQL Editor) :
   ```sql
   update public.profiles set role='admin'
   where id = (select id from auth.users where email='toi@exemple.fr');
   ```

## Fonctionnalités

| Section | Contenu |
|---------|---------|
| **Tableau de bord** | Compteurs (patients, analyses, opacités suspectes, taux de revue), répartition des classes, dernières analyses. |
| **Patients** | Création et recherche de dossiers, aperçu du dernier résultat, ouverture vers l'analyse. |
| **Analyse** | Upload d'une radio, choix du modèle, prédiction au schéma du projet (classe, confiance, observations, justification, JSON), enregistrement et historique, validation médicale. |
| **Mes examens** | Espace patient : uniquement ses propres résultats **validés par un médecin** (les analyses en attente ne sont pas divulguées). |
| **Mon profil** | Activation/désactivation du MFA (QR code + codes de secours), changement de mot de passe. |
| **Administration** | Réservée aux admins : validation des comptes professionnels, gestion des rôles (patient / médecin / admin), état MFA. |

## Modèles d'analyse

- `baseline` / `improved` : prédicteur de démonstration du dépôt
  (`src.inference.toy_predict`), fonctionne partout.
- `finetuned` : apparaît automatiquement **si** l'adaptateur MedGemma entraîné
  est présent dans `finetuning/outputs/medgemma-pneumo-lora/` **et** qu'un GPU
  est disponible. Utilise `finetuning.infer_finetuned`.

## Structure

```
medapp/
  app.py                    point d'entrée + navigation
  lib/
    config.py               détection du backend
    db.py                   accès données (Supabase + démo SQLite)
    auth.py                 connexion / session
    ai.py                   pont vers le pipeline d'analyse
    ui.py                   thème et composants
  supabase/schema.sql       schéma à exécuter dans Supabase
  .streamlit/
    config.toml             thème sombre radiologique
    secrets.toml.example    modèle d'identifiants Supabase
```

## Notification email à la création d'un patient

Quand tu enregistres un patient avec une adresse email, un message de
**confirmation de création de dossier** lui est envoyé. Par déontologie, cet
email ne contient **aucun résultat d'analyse** : les résultats ne se
communiquent que par un professionnel, en consultation.

Pour activer l'envoi, ajoute une section `[email]` dans
`.streamlit/secrets.toml` (voir `.example`). Deux options :

- **Resend** (recommandé, https://resend.com) : crée un compte, récupère une
  clé API `re_...`, renseigne `provider="resend"`, `resend_api_key`,
  `from_address`. Sans domaine vérifié, utilise l'expéditeur de test
  `onboarding@resend.dev`.
- **SMTP** (ex. Gmail avec un « mot de passe d'application ») :
  `provider="smtp"` + `smtp_host/port/user/password`.

Si aucune configuration email n'est présente, le dossier est créé normalement
et l'app signale simplement que la notification n'a pas été envoyée.

Une **Edge Function** Supabase équivalente est fournie dans
`supabase/functions/send-patient-email/` pour un envoi côté serveur (optionnel,
nécessite la CLI Supabase).

## Sécurité

Améliorations par rapport au prototype initial :

- **Mots de passe** : hachage PBKDF2-HMAC-SHA256 salé (200 000 itérations) en
  mode local, au lieu d'un SHA-256 simple. En mode Supabase, l'authentification
  est déléguée à Supabase Auth.
- **Politique de mot de passe** : minimum 8 caractères, majuscule, minuscule,
  chiffre, vérifiée à l'inscription.
- **Anti-bruteforce** : verrouillage temporaire (5 min) après 5 échecs de
  connexion consécutifs.
- **Validation** des adresses email (compte et patient).
- **Journal d'audit** inaltérable : connexions, créations de dossiers et de
  scans, envois d'email, changements de rôle. Consultable par les admins.
- **RLS Supabase durcies** : politiques séparées par opération, suppression de
  patients/scans réservée aux admins, journal d'audit en insertion seule et
  lecture admin uniquement.

- **MFA TOTP (RFC 6238)** : activable par compte depuis « Mon profil ».
  QR code `otpauth://` à scanner (Google Authenticator, Aegis, 2FAS…),
  vérification à 6 chiffres à chaque connexion, tolérance ±1 période, et
  **8 codes de secours à usage unique** (stockés hachés). Implémentation
  bibliothèque standard, vecteurs de test RFC 6238 vérifiés.
- **CAPTCHA image auto-hébergé** (Pillow, aucun service externe) :
  obligatoire à l'inscription et après 2 échecs de connexion. Le texte du
  défi n'est jamais stocké en clair (empreinte SHA-256 + expiration 3 min).
- **Trois rôles** : `patient` (lecture de son seul dossier, résultats
  validés uniquement), `doctor` (espace clinique), `admin` (gestion des
  comptes + audit). Contrôles appliqués **côté serveur** (routing + RLS
  Supabase), pas seulement dans l'interface.
- **Validation des comptes professionnels** : un compte médecin ne peut pas
  se connecter tant qu'un administrateur ne l'a pas validé (anti
  usurpation d'identité soignante).

Le mode démo local reste destiné à la démonstration. Pour un déploiement, utilise
Supabase (auth, RLS, storage) et sers l'application derrière HTTPS.
