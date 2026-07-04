from __future__ import annotations

from pathlib import Path

import streamlit as st

APP_TITLE = "TrueVision — Assistant radiologue"
APP_SUBTITLE = "Aide à la lecture de radiographies thoraciques"
MEDICAL_DISCLAIMER = (
    "Prototype pédagogique. Non destiné au diagnostic. "
    "Toute décision doit être validée par un professionnel qualifié."
)

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
LOCAL_DATA_DIR = Path(__file__).resolve().parent.parent / "demo_data"
LOCAL_DB_PATH = LOCAL_DATA_DIR / "pneumoscan_demo.sqlite3"
LOCAL_IMAGE_DIR = LOCAL_DATA_DIR / "images"

def _read_supabase_secrets() -> tuple[str | None, str | None]:
    try:
        sb = st.secrets["supabase"]
        url = str(sb.get("supabase_url", "")).strip()
        key = str(sb.get("supabase_anon_key", "")).strip()
    except Exception:
        return None, None
    if not url or not key or "xxxxxxxx" in url or key.endswith("ta_cle_anon..."):
        return None, None
    return url, key

def get_backend() -> str:
    url, key = _read_supabase_secrets()
    return "supabase" if url and key else "local"

def supabase_credentials() -> tuple[str, str]:
    url, key = _read_supabase_secrets()
    if not (url and key):
        raise RuntimeError("Identifiants Supabase absents ou invalides.")
    return url, key

def supabase_service_key() -> str | None:
    try:
        key = str(st.secrets["supabase"].get("supabase_service_role_key", "")).strip()
    except Exception:
        return None
    if not key or "xxxx" in key.lower() or key.startswith("ta_cle"):
        return None
    return key

def get_email_config() -> dict | None:
    try:
        e = dict(st.secrets["email"])
    except Exception:
        return None
    provider = str(e.get("provider", "")).strip().lower()
    if provider == "resend" and e.get("resend_api_key") and e.get("from_address"):
        return e
    if provider == "smtp" and e.get("smtp_host") and e.get("smtp_user"):
        return e
    return None
