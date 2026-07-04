from __future__ import annotations

import streamlit as st

from .db import get_backend_db
from .config import get_backend
from . import security

CAPTCHA_AFTER_FAILURES = 2

def get_current_user():
    if st.session_state.get("mfa_pending"):
        return None
    db = get_backend_db()
    return db.current_user()

def pending_mfa_user():
    if not st.session_state.get("mfa_pending"):
        return None
    db = get_backend_db()
    return db.current_user()

def failed_attempts(email: str) -> int:
    rec = st.session_state.get(f"failcount::{email.lower()}", 0)
    return int(rec)

def captcha_required(email: str) -> bool:
    return failed_attempts(email) >= CAPTCHA_AFTER_FAILURES

def _register_failure(email: str) -> None:
    key = f"failcount::{email.lower()}"
    st.session_state[key] = failed_attempts(email) + 1
    security.register_failed_attempt(st.session_state, email)

def _clear_failures(email: str) -> None:
    st.session_state.pop(f"failcount::{email.lower()}", None)
    security.clear_attempts(st.session_state, email)

def do_sign_in(email: str, password: str) -> tuple[bool, str]:
    email = (email or "").strip()
    remaining = security.lockout_remaining(st.session_state, email)
    if remaining > 0:
        return False, f"Trop de tentatives. Réessaie dans {remaining} s."

    db = get_backend_db()
    session, msg = db.sign_in(email, password)
    if session is None:
        _register_failure(email)
        try:
            db.log_audit("login_failed", "auth", None,
                         {"email": security.mask_email(email)})
        except Exception:
            pass
        return False, msg

    _clear_failures(email)
    if get_backend() == "local":
        st.session_state["local_user_id"] = session["user_id"]

    user = db.current_user()
    if user and user.get("role") in ("doctor", "admin") and not user.get("approved", True):
        do_sign_out()
        return False, "Compte en attente de validation par un administrateur."

    if user and user.get("mfa_enabled"):
        st.session_state["mfa_pending"] = True
        try:
            db.log_audit("login_password_ok_mfa_pending", "auth")
        except Exception:
            pass
        return True, "Mot de passe validé. Saisis ton code d'authentification."

    st.session_state["authenticated"] = True
    try:
        db.log_audit("login", "auth")
    except Exception:
        pass
    return True, msg

def do_verify_mfa(code: str) -> tuple[bool, str]:
    db = get_backend_db()
    user = pending_mfa_user()
    if not user:
        return False, "Session expirée, reconnecte-toi."

    secret = user.get("mfa_secret")
    if secret and security.verify_totp(secret, code):
        st.session_state.pop("mfa_pending", None)
        st.session_state["authenticated"] = True
        try:
            db.log_audit("login_mfa_ok", "auth")
        except Exception:
            pass
        return True, "Connecté."

    remaining = security.consume_backup_code(code, user.get("mfa_backup_codes") or [])
    if remaining is not None:
        db.set_mfa(user["id"], secret, True, remaining)
        st.session_state.pop("mfa_pending", None)
        st.session_state["authenticated"] = True
        try:
            db.log_audit("login_backup_code_used", "auth", user["id"],
                         {"codes_restants": len(remaining)})
        except Exception:
            pass
        return True, (f"Connecté avec un code de secours "
                      f"({len(remaining)} restant(s)).")

    try:
        db.log_audit("login_mfa_failed", "auth")
    except Exception:
        pass
    return False, "Code invalide."

def cancel_mfa() -> None:
    st.session_state.pop("mfa_pending", None)
    do_sign_out()

def do_sign_up(email: str, password: str, full_name: str,
               role: str = "doctor", doctor_id=None) -> tuple[bool, str]:
    email = (email or "").strip()
    if not security.is_valid_email(email):
        return False, "Adresse email invalide."
    issues = security.password_issues(password)
    if issues:
        return False, "Mot de passe trop faible : il faut " + ", ".join(issues) + "."
    db = get_backend_db()
    ok, msg = db.sign_up(email, password, full_name, role,
                         doctor_id=doctor_id)
    if ok:
        try:
            db.log_audit("signup", "auth", None,
                         {"email": security.mask_email(email), "role": role})
        except Exception:
            pass
    return ok, msg

def do_sign_out():
    db = get_backend_db()
    db.sign_out()
    for k in ("authenticated", "local_user_id", "active_patient",
              "mfa_pending", "nav", "nav_goto"):
        st.session_state.pop(k, None)

def begin_mfa_enrollment(user) -> str:
    key = f"mfa_enroll::{user['id']}"
    if key not in st.session_state:
        st.session_state[key] = security.generate_totp_secret()
    return st.session_state[key]

def confirm_mfa_enrollment(user, code: str) -> tuple[bool, list[str], str]:
    key = f"mfa_enroll::{user['id']}"
    secret = st.session_state.get(key)
    if not secret:
        return False, [], "Aucun enrôlement en cours."
    if not security.verify_totp(secret, code):
        return False, [], "Code invalide, vérifie ton application."
    codes = security.generate_backup_codes()
    hashed = [security.hash_backup_code(c) for c in codes]
    db = get_backend_db()
    db.set_mfa(user["id"], secret, True, hashed)
    st.session_state.pop(key, None)
    try:
        db.log_audit("mfa_enabled", "user", user["id"])
    except Exception:
        pass
    return True, codes, "MFA activé. Conserve tes codes de secours."

def disable_mfa(user, password: str) -> tuple[bool, str]:
    db = get_backend_db()
    session, _ = db.sign_in(user["email"], password)
    if session is None:
        return False, "Mot de passe incorrect."
    db.set_mfa(user["id"], None, False, [])
    try:
        db.log_audit("mfa_disabled", "user", user["id"])
    except Exception:
        pass
    return True, "MFA désactivé."

def require_admin(user) -> bool:
    return bool(user) and user.get("role") == "admin"

def require_doctor(user) -> bool:
    return bool(user) and user.get("role") in ("doctor", "admin")

def is_patient(user) -> bool:
    return bool(user) and user.get("role") == "patient"

def request_password_reset(email: str) -> tuple[bool, str]:
    from .config import get_email_config
    from .email_service import send_email, reset_code_html

    email = (email or "").strip()
    if not security.is_valid_email(email):
        return False, "Adresse email invalide."

    wait = security.reset_cooldown_remaining(st.session_state, email)
    if wait > 0:
        return False, f"Un code vient d'être envoyé. Réessaie dans {wait} s."

    neutral = ("Si un compte existe pour cette adresse, un code de "
               "réinitialisation vient d'être envoyé (valable 10 min).")

    db = get_backend_db()
    if getattr(db, "admin", "n/a") is None:
        return False, ("Réinitialisation indisponible : ajoute la clé "
                       "service_role dans les secrets (voir "
                       "secrets.toml.example), ou demande à un administrateur.")
    user = db.get_user_by_email(email)
    if not user:
        return True, neutral

    email_cfg = get_email_config()
    if not email_cfg:
        return False, ("L'envoi d'email n'est pas configuré (section [email] "
                       "des secrets). Demande à un administrateur de changer "
                       "ton mot de passe.")

    code = security.new_reset_code()
    ok, msg = send_email(email, "Code de réinitialisation — TrueVision",
                         reset_code_html(code), email_cfg)
    if not ok:
        return False, f"Envoi impossible : {msg}"
    security.store_reset_code(st.session_state, email, code)
    try:
        db.log_audit("password_reset_requested", "auth", None,
                     {"email": security.mask_email(email)})
    except Exception:
        pass
    return True, neutral

def confirm_password_reset(email: str, code: str,
                           new_password: str) -> tuple[bool, str]:
    email = (email or "").strip()
    issues = security.password_issues(new_password)
    if issues:
        return False, ("Mot de passe trop faible : il faut " +
                       ", ".join(issues) + ".")
    if not security.verify_reset_code(st.session_state, email, code):
        return False, "Code invalide ou expiré. Redemande un code."

    db = get_backend_db()
    if not db.set_password_by_email(email, new_password):
        return False, ("Impossible de mettre à jour le mot de passe. "
                       "En mode Supabase, la clé service_role doit être "
                       "renseignée dans les secrets ; sinon demande à un "
                       "administrateur.")
    try:
        db.log_audit("password_reset_done", "auth", None,
                     {"email": security.mask_email(email)})
    except Exception:
        pass
    return True, "Mot de passe mis à jour. Tu peux te connecter."
