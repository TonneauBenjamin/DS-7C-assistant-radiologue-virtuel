from __future__ import annotations

import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Any

def patient_welcome_html(patient_name: str, clinic_name: str = "TrueVision") -> str:
    safe = (patient_name or "").strip() or "Madame, Monsieur"
    return f"""\
<div style="font-family:Arial,sans-serif;max-width:520px;margin:auto;color:#0f172a">
  <div style="height:4px;background:#22d3ee;border-radius:2px"></div>
  <h2 style="margin:18px 0 6px">Votre dossier a été créé</h2>
  <p>Bonjour {safe},</p>
  <p>Un dossier a été enregistré à votre nom au sein du service d'imagerie
     <strong>{clinic_name}</strong>. Ce message confirme uniquement la création
     de votre dossier administratif.</p>
  <p>Aucun résultat d'examen n'est communiqué par email. Les résultats vous
     seront transmis exclusivement par un professionnel de santé lors de votre
     consultation.</p>
  <p style="color:#64748b;font-size:13px;margin-top:22px">
     Message automatique — prototype pédagogique, ne pas répondre.</p>
</div>"""

def send_email(to_email: str, subject: str, html_body: str, cfg: dict[str, Any] | None):
    if not cfg:
        return False, "Email non configuré (notification ignorée)."
    provider = (cfg.get("provider") or "").lower()
    from_addr = cfg.get("from_address") or "no-reply@pneumoscan.local"

    if provider == "resend":
        return _send_resend(to_email, subject, html_body, from_addr, cfg)
    if provider == "smtp":
        return _send_smtp(to_email, subject, html_body, from_addr, cfg)
    return False, f"Fournisseur email inconnu : {provider!r}"

def _send_resend(to_email, subject, html_body, from_addr, cfg):
    import requests

    api_key = cfg.get("resend_api_key")
    if not api_key:
        return False, "Clé API Resend manquante."
    try:
        r = requests.post(
            "https://api.resend.com/emails",
            headers={"Authorization": f"Bearer {api_key}"},
            json={"from": from_addr, "to": [to_email],
                  "subject": subject, "html": html_body},
            timeout=15,
        )
        if r.status_code in (200, 201):
            return True, "Email envoyé."
        return False, f"Resend a répondu {r.status_code} : {r.text[:200]}"
    except Exception as e:
        return False, f"Échec de l'envoi (Resend) : {e}"

def _send_smtp(to_email, subject, html_body, from_addr, cfg):
    host = cfg.get("smtp_host")
    port = int(cfg.get("smtp_port", 587))
    user = cfg.get("smtp_user")
    password = cfg.get("smtp_password")
    if not (host and user and password):
        return False, "Configuration SMTP incomplète."
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = from_addr
    msg["To"] = to_email
    msg.attach(MIMEText(html_body, "html"))
    try:
        with smtplib.SMTP(host, port, timeout=20) as server:
            server.starttls()
            server.login(user, password)
            server.sendmail(from_addr, [to_email], msg.as_string())
        return True, "Email envoyé."
    except Exception as e:
        return False, f"Échec de l'envoi (SMTP) : {e}"

def reset_code_html(code: str, clinic_name: str = "TrueVision") -> str:
    return f"""\
<div style="font-family:Arial,sans-serif;max-width:520px;margin:auto;color:#16323f">
  <div style="height:4px;background:#0f766e;border-radius:2px"></div>
  <h2 style="margin:18px 0 6px">Réinitialisation de votre mot de passe</h2>
  <p>Une demande de réinitialisation a été faite pour votre compte
     <strong>{clinic_name}</strong>. Saisissez ce code dans l'application :</p>
  <p style="font-size:28px;font-weight:bold;letter-spacing:6px;
     font-family:monospace;text-align:center;margin:18px 0">{code}</p>
  <p>Ce code expire dans <strong>10 minutes</strong> et n'est utilisable
     qu'une seule fois.</p>
  <p style="color:#5b7282;font-size:13px;margin-top:22px">
     Si vous n'êtes pas à l'origine de cette demande, ignorez ce message :
     votre mot de passe reste inchangé.</p>
</div>"""
