from __future__ import annotations

import json
from datetime import date

import streamlit as st

from lib.config import (
    APP_TITLE,
    MEDICAL_DISCLAIMER,
    get_backend,
    get_email_config,
)
from lib import security
from lib.captcha import captcha_image_bytes, qr_png_bytes
from lib.email_service import send_email, patient_welcome_html
from lib.ui import (
    inject_css,
    app_header,
    auth_brand,
    class_badge,
    metric_card,
    confidence_bar,
    CLASS_STYLE,
    INK,
    ACCENT,
)
from lib import auth
from lib.auth import (
    get_current_user,
    pending_mfa_user,
    do_sign_in,
    do_verify_mfa,
    cancel_mfa,
    do_sign_up,
    do_sign_out,
    require_admin,
    require_doctor,
    is_patient,
)
from lib.db import get_backend_db
from lib.ai import available_models, analyze_image

from pathlib import Path as _Path
_FAVICON = str(_Path(__file__).resolve().parent / "assets" / "favicon.png")
st.set_page_config(page_title=APP_TITLE, page_icon=_FAVICON, layout="wide")
inject_css()

def _rotate_captcha(key: str) -> None:
    st.session_state[f"{key}::nonce"] = st.session_state.get(f"{key}::nonce", 0) + 1
    text = security.new_captcha_text()
    security.store_captcha(st.session_state, text, key=key)
    st.session_state[f"{key}::img"] = captcha_image_bytes(text)

def captcha_widget(key: str) -> str:
    if f"{key}::hash" not in st.session_state or f"{key}::img" not in st.session_state:
        _rotate_captcha(key)
    nonce = st.session_state.get(f"{key}::nonce", 0)

    c1, c2 = st.columns([5, 2], vertical_alignment="bottom")
    c1.image(st.session_state[f"{key}::img"])
    if c2.button("↻", key=f"{key}::refresh", help="Nouveau défi",
                 width="stretch"):
        _rotate_captcha(key)
        st.rerun()
    return st.text_input("Recopie les caractères de l'image",
                         key=f"{key}::answer::{nonce}", max_chars=8)

def _consume_captcha(key: str, answer: str) -> bool:
    ok = security.verify_captcha(st.session_state, answer, key=key)
    _rotate_captcha(key)
    return ok

def _centered():
    _, mid, _ = st.columns([1, 1.3, 1])
    return mid

def render_mfa_step():
    with _centered():
        with st.container(border=True):
            auth_brand("Vérification en deux étapes")
            user = pending_mfa_user()
            if not user:
                st.error("Session expirée.")
                if st.button("Retour à la connexion", width="stretch"):
                    cancel_mfa()
                    st.rerun()
                return
            st.caption(f"Compte **{security.mask_email(user['email'])}** — "
                       "saisis le code à 6 chiffres de ton application "
                       "d'authentification, ou un code de secours.")
            code = st.text_input("Code de vérification", max_chars=9,
                                 key="mfa_code", placeholder="123456 ou XXXX-XXXX")
            if st.button("Vérifier", type="primary", width="stretch"):
                ok, msg = do_verify_mfa(code)
                if ok:
                    st.rerun()
                else:
                    st.error(msg)
            if st.button("Annuler et revenir à la connexion",
                         width="stretch"):
                cancel_mfa()
                st.rerun()

def render_auth():
    db_public = get_backend_db()
    with _centered():
        with st.container(border=True):
            auth_brand("Aide à la lecture de radiographies thoraciques")
            tab_login, tab_signup = st.tabs(["Se connecter", "Créer un compte"])

            with tab_login:
                li_flash = st.session_state.pop("li_flash", None)
                if li_flash:
                    st.error(li_flash)

                email = st.text_input("Email", key="li_email",
                                      placeholder="prenom.nom@exemple.fr")
                pw = st.text_input("Mot de passe", type="password", key="li_pw")

                need_captcha = auth.captcha_required(email)
                cap_answer = ""
                if need_captcha:
                    st.caption("🤖 Plusieurs échecs : vérification anti-robot requise.")
                    cap_answer = captcha_widget("cap_login")

                if st.button("Se connecter", type="primary",
                             width="stretch"):
                    if need_captcha and not _consume_captcha("cap_login", cap_answer):
                        st.session_state["li_flash"] = (
                            "CAPTCHA incorrect — recopie la nouvelle image.")
                        st.rerun()
                    ok, msg = do_sign_in(email.strip(), pw)
                    if ok:
                        st.rerun()
                    st.session_state["li_flash"] = msg
                    st.rerun()
                if get_backend() == "local":
                    st.caption("Mode démo — admin de test : `admin@demo.local` "
                               "/ `admin`")

                with st.expander("Mot de passe oublié ?",
                                 expanded=bool(st.session_state.get("rp_sent"))):
                    flash = st.session_state.pop("rp_flash", None)
                    if flash:
                        (st.success if flash[0] else st.error)(flash[1])
                    r_email = st.text_input("Ton email de compte",
                                            key="rp_email")
                    if not st.session_state.get("rp_sent"):
                        if st.button("M'envoyer un code",
                                     width="stretch", key="rp_send"):
                            ok, msg = auth.request_password_reset(r_email)
                            st.session_state["rp_flash"] = (ok, msg)
                            if ok:
                                st.session_state["rp_sent"] = True
                            st.rerun()
                    else:
                        st.caption("Un code à 6 chiffres a été envoyé "
                                   "(valable 10 min). Vérifie aussi les spams.")
                        r_code = st.text_input("Code reçu par email",
                                               max_chars=6, key="rp_code")
                        r_pw = st.text_input("Nouveau mot de passe",
                                             type="password", key="rp_pw",
                                             help="8 caractères minimum, avec "
                                                  "majuscule, minuscule et chiffre.")
                        c1, c2 = st.columns(2)
                        if c1.button("Changer le mot de passe", type="primary",
                                     width="stretch", key="rp_do"):
                            ok, msg = auth.confirm_password_reset(
                                r_email, r_code, r_pw)
                            if ok:
                                st.session_state.pop("rp_sent", None)
                            st.session_state["rp_flash"] = (ok, msg)
                            st.rerun()
                        if c2.button("Renvoyer un code",
                                     width="stretch", key="rp_again"):
                            ok, msg = auth.request_password_reset(r_email)
                            st.session_state["rp_flash"] = (ok, msg)
                            st.rerun()

            with tab_signup:
                kind = st.radio(
                    "Je suis…",
                    ["Patient", "Professionnel de santé"],
                    horizontal=True, label_visibility="collapsed",
                )
                role = "patient" if kind == "Patient" else "doctor"
                chosen_doctor = None
                if role == "patient":
                    st.caption("Accès à ton dossier et à tes résultats validés.")
                    doctors = db_public.list_doctors()
                    if not doctors:
                        st.warning("Aucun médecin n'est encore inscrit et "
                                   "validé sur la plateforme : l'inscription "
                                   "patient sera possible dès qu'un médecin "
                                   "sera disponible.", icon="🩺")
                    else:
                        d_ids = [d["id"] for d in doctors]
                        d_lbl = {d["id"]: f"Dr {d.get('full_name') or d.get('email')}"
                                 for d in doctors}
                        chosen_doctor = st.selectbox(
                            "Ton médecin traitant *",
                            [None] + d_ids,
                            format_func=lambda i: "— Choisis ton médecin —"
                            if i is None else d_lbl[i],
                            help="Obligatoire. Ce médecin aura accès à ton "
                                 "dossier et à tes examens sur la plateforme.")
                else:
                    st.caption("Compte activé après validation par un "
                               "administrateur.")
                name = st.text_input("Nom complet", key="su_name")
                email2 = st.text_input("Email", key="su_email")
                pw2 = st.text_input("Mot de passe", type="password", key="su_pw",
                                    help="8 caractères minimum, avec majuscule, "
                                         "minuscule et chiffre.")
                if pw2:
                    issues = security.password_issues(pw2)
                    st.caption(("🔒 Manque : " + ", ".join(issues))
                               if issues else "🔒 Mot de passe conforme.")
                su_flash = st.session_state.pop("su_flash", None)
                if su_flash:
                    (st.success if su_flash[0] else st.error)(su_flash[1])

                cap_answer2 = captcha_widget("cap_signup")
                if st.button("Créer le compte", type="primary",
                             width="stretch"):
                    if role == "patient" and chosen_doctor is None:
                        st.error("Choisis ton médecin traitant pour "
                                 "finaliser l'inscription.")
                    elif not _consume_captcha("cap_signup", cap_answer2):
                        st.session_state["su_flash"] = (
                            False, "CAPTCHA incorrect ou expiré — recopie "
                                   "la nouvelle image ci-dessous.")
                        st.rerun()
                    else:
                        ok, msg = do_sign_up(email2.strip(), pw2,
                                             name.strip(), role,
                                             doctor_id=chosen_doctor)
                        st.session_state["su_flash"] = (ok, msg)
                        st.rerun()

        st.caption(MEDICAL_DISCLAIMER)

def render_dashboard(db, user):
    app_header("Tableau de bord")
    doc_filter = user["id"] if user.get("role") == "doctor" else None
    s = db.stats(doctor_id=doc_filter)

    cols = st.columns(4)
    cards = [
        (s["n_patients"], "Patients", INK),
        (s["n_scans"], "Analyses", ACCENT),
        (s["n_suspected"], "Opacités suspectes", CLASS_STYLE["suspected_opacity"][0]),
        (f'{int(s["reviewed_rate"]*100)}%', "Revues par un médecin",
         CLASS_STYLE["normal"][0]),
    ]
    for col, (value, label, color) in zip(cols, cards):
        col.markdown(metric_card(value, label, color), unsafe_allow_html=True)

    st.markdown("")
    left, right = st.columns([1, 1])

    with left:
        st.markdown("##### Répartition des classes")
        by = s["by_class"]
        if by:
            import pandas as pd

            order = ["suspected_opacity", "normal", "uncertain"]
            data = {CLASS_STYLE.get(k, (None, k))[1]: by.get(k, 0)
                    for k in order if k in by}
            for k, v in by.items():
                if k not in order:
                    data[k] = v
            st.bar_chart(pd.DataFrame({"analyses": data}))
        else:
            st.caption("Aucune analyse enregistrée pour l'instant.")

    with right:
        st.markdown("##### Dernières analyses")
        recent = s["scans"][:6]
        if not recent:
            st.caption("Lance une première analyse depuis l'onglet Analyse.")
        for sc in recent:
            pat = db.get_patient(sc["patient_id"])
            pname = pat["full_name"] if pat else "—"
            c1, c2 = st.columns([3, 2])
            c1.write(f"**{pname}**")
            c1.caption(str(sc.get("created_at", ""))[:16].replace("T", " "))
            c2.markdown(class_badge(sc.get("predicted_class")), unsafe_allow_html=True)

def render_patients(db, user):
    app_header("Dossiers patients")

    email_cfg = get_email_config()
    with st.expander("➕ Nouveau patient"):
        c1, c2 = st.columns(2)
        name = c1.text_input("Nom complet *")
        ref = c2.text_input("N° de dossier")
        c3, c4 = st.columns(2)
        email = c3.text_input("Email du patient",
                              help="Un email de confirmation de création de "
                                   "dossier lui sera envoyé (aucun résultat médical). "
                                   "Si un compte patient existe avec cet email, "
                                   "le dossier lui sera automatiquement rattaché.")
        sex = c4.selectbox("Sexe", ["", "F", "M", "other"])
        c5, c6 = st.columns(2)
        bdate = c5.date_input("Date de naissance", value=None,
                              min_value=date(1900, 1, 1), max_value=date.today())
        notes = st.text_area("Notes cliniques", height=80)
        if not email_cfg:
            st.caption("ℹ️ Envoi d'email non configuré : le dossier sera créé "
                       "sans notification. Voir README pour activer Resend/SMTP.")
        if st.button("Enregistrer le patient", type="primary"):
            email = email.strip()
            if not name.strip():
                st.error("Le nom est obligatoire.")
            elif email and not security.is_valid_email(email):
                st.error("L'adresse email du patient est invalide.")
            else:
                patient = db.create_patient({
                    "full_name": name.strip(),
                    "external_ref": ref.strip() or None,
                    "email": email or None,
                    "birth_date": bdate.isoformat() if bdate else None,
                    "sex": sex or None,
                    "notes": notes.strip() or None,
                    "doctor_id": user["id"] if user.get("role") == "doctor"
                                 else None,
                })
                db.log_audit("patient_created", "patient", patient.get("id"),
                             {"has_email": bool(email)})
                if email:
                    acc = db.get_user_by_email(email)
                    if acc and acc.get("role") == "patient":
                        db.link_patient_user(patient["id"], acc["id"])
                        db.log_audit("patient_linked", "patient",
                                     patient.get("id"), {"user": acc["id"]})
                        st.info("Dossier rattaché au compte patient existant.")
                st.success("Patient enregistré.")
                if email and email_cfg:
                    ok, msg = send_email(
                        email, "Création de votre dossier — TrueVision",
                        patient_welcome_html(name.strip()), email_cfg)
                    if ok:
                        st.success(f"Email de confirmation envoyé à {email}.")
                        db.log_audit("email_sent", "patient", patient.get("id"))
                    else:
                        st.warning(f"Dossier créé, mais email non envoyé : {msg}")
                elif email and not email_cfg:
                    st.info("Dossier créé. Configure Resend/SMTP pour l'envoi d'email.")
                st.rerun()

    search = st.text_input("Rechercher un patient", placeholder="nom ou n° de dossier")
    doc_filter = user["id"] if user.get("role") == "doctor" else None
    patients = db.list_patients(search, doctor_id=doc_filter)
    if doc_filter:
        st.caption(f"{len(patients)} patient(s) dans ta patientèle "
                   "(dossiers dont tu es le médecin traitant)")
    else:
        st.caption(f"{len(patients)} patient(s)")

    for p in patients:
        with st.container(border=True):
            c1, c2, c3 = st.columns([3, 2, 1])
            c1.markdown(f"**{p['full_name']}**")
            linked = " · 🔗 compte patient" if p.get("user_id") else ""
            c1.caption(f"Dossier {p.get('external_ref') or '—'} · "
                       f"{p.get('sex') or '—'} · né(e) {p.get('birth_date') or '—'}"
                       f"{linked}")
            scans = db.list_scans(p["id"])
            c2.caption(f"{len(scans)} analyse(s)")
            if scans:
                c2.markdown(class_badge(scans[0].get("predicted_class")),
                            unsafe_allow_html=True)
            if c3.button("Ouvrir", key=f"open_{p['id']}"):
                st.session_state["active_patient"] = p["id"]
                st.session_state["nav_goto"] = "Analyse"
                st.rerun()

def render_analyze(db, user):
    app_header("Analyse d'une radiographie")

    doc_filter = user["id"] if user.get("role") == "doctor" else None
    patients = db.list_patients(doctor_id=doc_filter)

    # Mode test : analyse libre, sans dossier patient. Le résultat s'affiche
    # (avec son JSON) mais n'est PAS enregistré. Seul mode possible s'il n'y a
    # aucun patient, sinon proposé en option pour une démonstration rapide.
    if not patients:
        st.info("Aucun dossier patient dans ta patientèle : tu peux quand même "
                "tester l'analyse ci-dessous. Le résultat ne sera pas enregistré. "
                "Crée un dossier dans l'onglet Patients pour rattacher et "
                "historiser un examen.", icon="🧪")
        test_mode = True
        pid = None
    else:
        test_mode = st.toggle(
            "🧪 Test rapide (sans enregistrer dans un dossier)",
            value=False, key="analyze_test_mode",
            help="Analyse une radiographie sans la rattacher à un patient. "
                 "Rien n'est enregistré — idéal pour une démonstration.")
        if test_mode:
            pid = None
        else:
            ids = [p["id"] for p in patients]
            labels = {p["id"]: f"{p['full_name']} · {p.get('external_ref') or '—'}"
                      for p in patients}
            default = st.session_state.get("active_patient")
            idx = ids.index(default) if default in ids else 0
            pid = st.selectbox("Patient", ids, index=idx,
                               format_func=lambda i: labels[i])

    models = available_models()
    if not models:
        st.warning("Aucun modèle disponible : l'inférence MedGemma nécessite "
                   "un GPU CUDA (voir notebooks/MedGemma_Radios_final.ipynb).")
        return
    model = st.selectbox("Modèle", models,
                         help="medgemma-baseline/improved : MedGemma 4B, prompt v1/v2. "
                              "finetuned : MedGemma entraîné (GPU requis).")
    uploaded = st.file_uploader("Radiographie thoracique frontale",
                                type=["png", "jpg", "jpeg"])

    col_img, col_res = st.columns([1, 1])
    if uploaded:
        image_bytes = uploaded.getvalue()
        col_img.image(image_bytes, caption=uploaded.name, width="stretch")

        if col_res.button("Analyser", type="primary", width="stretch"):
            with st.spinner("Analyse en cours…"):
                pred = analyze_image(image_bytes, uploaded.name, model)
            scan_id = None
            if test_mode or pid is None:
                # Test : rien n'est écrit en base, on trace juste l'événement.
                db.log_audit("scan_tested", None, None,
                             {"class": pred.get("predicted_class"), "model": model})
            else:
                scan = db.create_scan(
                    {
                        "patient_id": pid,
                        "predicted_class": pred.get("predicted_class"),
                        "confidence": pred.get("confidence"),
                        "image_quality": pred.get("image_quality"),
                        "model_name": pred.get("model_name"),
                        "result_json": json.dumps(pred, ensure_ascii=False),
                    },
                    image_bytes, uploaded.name,
                )
                db.log_audit("scan_created", "patient", pid,
                             {"class": pred.get("predicted_class"), "model": model})
                st.session_state["active_patient"] = pid
                scan_id = (scan or {}).get("id")
            # On mémorise le résultat pour qu'il survive aux reruns suivants.
            st.session_state["last_result"] = {
                "pid": pid, "test": test_mode, "pred": pred,
                "image": image_bytes, "scan_id": scan_id,
            }
            st.rerun()

    # Dernier résultat, ré-affiché à chaque run tant qu'il correspond au contexte
    # courant (même patient, ou même mode test).
    last = st.session_state.get("last_result")
    show_last = last and (
        (last.get("test") and test_mode)
        or (not last.get("test") and last.get("pid") == pid)
    )
    if show_last:
        col_res.markdown("**Dernier résultat**"
                         + (" · test (non enregistré)" if last.get("test") else ""))
        _render_result(col_res, last["pred"], last.get("image"),
                       key=f"live_{last.get('scan_id') or 'test'}")
        if col_res.button("Effacer ce résultat", key="clear_last",
                          width="stretch"):
            st.session_state.pop("last_result", None)
            st.rerun()

    if test_mode or pid is None:
        return

    st.divider()
    st.markdown("##### Historique du patient")
    for sc in db.list_scans(pid):
        with st.container(border=True):
            c1, c2, c3 = st.columns([2, 2, 1])
            c1.markdown(class_badge(sc.get("predicted_class")), unsafe_allow_html=True)
            c1.caption(str(sc.get("created_at", ""))[:16].replace("T", " "))
            conf = sc.get("confidence")
            c2.caption(f"confiance {int(float(conf)*100)}%" if conf is not None else "—")
            c2.caption(f"modèle : {sc.get('model_name') or '—'}")
            reviewed = sc.get("reviewed") in (1, True)
            if c3.button("✔ Revu" if reviewed else "Marquer revu",
                         key=f"rev_{sc['id']}", disabled=reviewed):
                db.mark_reviewed(sc["id"], True)
                st.rerun()
            with st.expander("🩻 Voir la radiographie"):
                _render_scan_image(db, sc)
            rj = sc.get("result_json")
            if rj:
                _json_block(rj, key=f"hist_{sc['id']}",
                            label="Analyse complète (JSON)")

def _render_scan_image(db, sc):
    raw = db.image_bytes(sc.get("image_path"))
    if not raw:
        st.caption("Image indisponible (non enregistrée ou supprimée).")
        return
    if sc.get("predicted_class") != "normal":
        from lib.vision import annotate_image

        shown, found = annotate_image(raw)
        st.image(shown, width="stretch")
        if found:
            st.caption("🔴 Zone douteuse entourée — localisation "
                       "automatique, purement indicative : "
                       "l'interprétation revient au médecin.")
        else:
            st.caption("Aucune zone ne se détache assez pour être "
                       "localisée automatiquement.")
    else:
        st.image(raw, width="stretch")

def _as_dict(value):
    """Normalise un result_json qui peut arriver en str (SQLite) ou en dict (Supabase)."""
    if isinstance(value, str):
        try:
            return json.loads(value)
        except Exception:
            return {"raw": value}
    return value or {}

def _json_block(pred, *, key, label="Sortie complète (JSON)", expanded=False):
    """Bloc JSON repliable, cliquable (arbre déroulant Streamlit) et téléchargeable.
    `key` doit être unique par analyse pour éviter les collisions de widgets."""
    data = _as_dict(pred)
    with st.expander(f"🧾 {label}", expanded=expanded):
        st.json(data)
        st.download_button(
            "⬇ Télécharger le JSON",
            data=json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8"),
            file_name=f"analyse_{key}.json",
            mime="application/json",
            key=f"dl_json_{key}",
            width="stretch",
        )

def _render_result(col, pred, image_bytes=None, *, key="live"):
    with col:
        st.markdown(class_badge(pred.get("predicted_class")), unsafe_allow_html=True)
        st.markdown("")
        confidence_bar(pred.get("confidence", 0))
        if image_bytes and pred.get("predicted_class") != "normal":
            from lib.vision import annotate_image

            shown, found = annotate_image(image_bytes)
            if found:
                st.image(shown, width="stretch")
                st.caption("🔴 Zone douteuse entourée — localisation "
                           "automatique, purement indicative.")
        st.write(f"**Qualité image :** {pred.get('image_quality', '—')}")
        obs = pred.get("visual_evidence") or []
        if obs:
            st.write("**Observations**")
            for e in obs:
                st.caption(f"• {e}")
        st.write("**Justification**")
        st.caption(pred.get("justification", "—"))
        _json_block(pred, key=key)
        st.warning(pred.get("warning", MEDICAL_DISCLAIMER), icon="⚠️")

def render_my_exams(db, user):
    app_header("Mes examens")
    record = db.get_patient_by_user(user["id"])
    if not record:
        st.info("Aucun dossier médical n'est encore rattaché à ton compte. "
                "Il sera créé ou rattaché par le service d'imagerie "
                "(vérifie que ton email de compte correspond à celui "
                "communiqué au service).", icon="📋")
        return

    st.markdown(f"**Dossier :** {record['full_name']} · "
                f"n° {record.get('external_ref') or '—'}")

    doctors = db.list_doctors()
    doc_ids = [d["id"] for d in doctors]
    doc_labels = {d["id"]: f"Dr {d.get('full_name') or d.get('email')}"
                  for d in doctors}
    current_doc = record.get("doctor_id")
    if not doctors:
        st.info("Aucun médecin n'est encore inscrit sur la plateforme.",
                icon="🩺")
    else:
        c1, c2 = st.columns([3, 1], vertical_alignment="bottom")
        options = [None] + doc_ids
        idx = options.index(current_doc) if current_doc in options else 0
        chosen = c1.selectbox(
            "Mon médecin traitant",
            options, index=idx,
            format_func=lambda i: "— Aucun —" if i is None else doc_labels[i],
            help="Ton médecin traitant a accès à ton dossier et à tes "
                 "examens sur la plateforme.")
        if c2.button("Enregistrer", width="stretch",
                     disabled=(chosen == current_doc)):
            db.set_patient_doctor(record["id"], chosen)
            db.log_audit("doctor_assigned", "patient", record["id"],
                         {"doctor": chosen})
            st.session_state["myexam_flash"] = (
                "Médecin traitant mis à jour."
                if chosen else "Médecin traitant retiré.")
            st.rerun()
        flash = st.session_state.pop("myexam_flash", None)
        if flash:
            st.success(flash)
        if current_doc and current_doc in doc_labels:
            st.caption(f"Médecin traitant actuel : "
                       f"**{doc_labels[current_doc]}**")

    st.divider()
    st.markdown("##### Analyser une radiographie")
    scan_flash = st.session_state.pop("myscan_flash", None)
    if scan_flash:
        st.success(scan_flash, icon="📤")
    if not record.get("doctor_id"):
        st.info("Choisis d'abord ton médecin traitant ci-dessus : l'examen "
                "lui sera transmis pour validation.", icon="🩺")
    else:
        doc_name = doc_labels.get(record["doctor_id"], "ton médecin")
        models = available_models()
        if not models:
            st.warning("Aucun modèle disponible : l'inférence MedGemma "
                       "nécessite un GPU CUDA.")
        else:
            model = st.selectbox(
                "Modèle d'analyse", models, key="pat_model",
                help="medgemma-baseline/improved : MedGemma 4B, prompt v1/v2. "
                     "finetuned : MedGemma entraîné (GPU requis).")
            uploaded = st.file_uploader(
                "Radiographie thoracique frontale",
                type=["png", "jpg", "jpeg"], key="pat_upload")
            if uploaded:
                image_bytes = uploaded.getvalue()
                st.image(image_bytes, caption=uploaded.name, width=320)
                if st.button(f"Analyser et envoyer à {doc_name}",
                             type="primary", width="stretch"):
                    with st.spinner("Analyse en cours…"):
                        pred = analyze_image(image_bytes, uploaded.name, model)
                    db.create_scan(
                        {
                            "patient_id": record["id"],
                            "predicted_class": pred.get("predicted_class"),
                            "confidence": pred.get("confidence"),
                            "image_quality": pred.get("image_quality"),
                            "model_name": pred.get("model_name"),
                            "result_json": json.dumps(pred, ensure_ascii=False),
                        },
                        image_bytes, uploaded.name,
                    )
                    db.log_audit("scan_submitted_by_patient", "patient",
                                 record["id"], {"model": model})
                    st.session_state["myscan_flash"] = (
                        f"Examen analysé et transmis à {doc_name}. Le résultat "
                        "s'affichera ici dès qu'il aura été validé.")
                    st.rerun()

    st.divider()
    st.markdown("##### Mes résultats validés")
    scans = db.list_scans(record["id"])
    validated = [s for s in scans if s.get("reviewed") in (1, True)]
    pending = len(scans) - len(validated)

    if pending:
        st.info(f"{pending} examen(s) en attente de validation par un "
                "médecin. Par déontologie, seuls les résultats validés "
                "sont affichés ici.", icon="⏳")
    if not validated:
        st.caption("Aucun résultat validé pour l'instant.")
        return

    for sc in validated:
        with st.container(border=True):
            c1, c2 = st.columns([2, 3])
            c1.markdown(class_badge(sc.get("predicted_class")),
                        unsafe_allow_html=True)
            c1.caption(str(sc.get("created_at", ""))[:16].replace("T", " "))
            c2.caption("✔ Validé par un médecin")
            c2.caption(f"Modèle : {sc.get('model_name') or '—'}")
            rj = sc.get("result_json")
            if rj:
                _json_block(rj, key=f"pat_{sc['id']}",
                            label="Détail de l'analyse (JSON)")
    st.warning("Ces informations ne remplacent pas une consultation. "
               "Rapproche-toi de ton médecin pour toute question.", icon="⚠️")

def render_profile(db, user):
    app_header("Mon profil")
    st.markdown(f"**{user.get('full_name') or '—'}** · {user['email']} · "
                f"rôle `{user['role']}`")

    st.markdown("##### Authentification à deux facteurs (TOTP)")
    if user.get("mfa_enabled"):
        n_codes = len(user.get("mfa_backup_codes") or [])
        st.success(f"MFA activé · {n_codes} code(s) de secours restant(s).",
                   icon="🔐")
        with st.expander("Désactiver le MFA"):
            pw = st.text_input("Confirme ton mot de passe", type="password",
                               key="mfa_off_pw")
            if st.button("Désactiver", type="secondary"):
                ok, msg = auth.disable_mfa(user, pw)
                (st.success if ok else st.error)(msg)
                if ok:
                    st.rerun()
    else:
        if user["role"] in ("doctor", "admin"):
            st.warning("Fortement recommandé pour les comptes professionnels.",
                       icon="🛡️")
        with st.expander("Activer le MFA", expanded=False):
            secret = auth.begin_mfa_enrollment(user)
            uri = security.totp_provisioning_uri(secret, user["email"])
            c1, c2 = st.columns([1, 2])
            c1.image(qr_png_bytes(uri), caption="Scanne avec Google "
                     "Authenticator, Aegis, 2FAS…")
            c2.code(secret, language=None)
            c2.caption("Ou saisis ce secret manuellement dans ton application.")
            code = c2.text_input("Code affiché par l'application", max_chars=6,
                                 key="mfa_enroll_code")
            if c2.button("Vérifier et activer", type="primary"):
                ok, codes, msg = auth.confirm_mfa_enrollment(user, code)
                if ok:
                    st.success(msg)
                    st.markdown("##### Codes de secours (affichés une seule fois)")
                    st.code("\n".join(codes), language=None)
                    st.caption("Chaque code n'est utilisable qu'une fois. "
                               "Range-les en lieu sûr.")
                else:
                    st.error(msg)

    st.markdown("##### Changer le mot de passe")
    with st.form("pw_change"):
        old_pw = st.text_input("Mot de passe actuel", type="password")
        new_pw = st.text_input("Nouveau mot de passe", type="password")
        new_pw2 = st.text_input("Confirme le nouveau mot de passe",
                                type="password")
        submitted = st.form_submit_button("Mettre à jour")
    if submitted:
        session, _ = db.sign_in(user["email"], old_pw)
        issues = security.password_issues(new_pw)
        if session is None:
            st.error("Mot de passe actuel incorrect.")
        elif new_pw != new_pw2:
            st.error("Les deux saisies ne correspondent pas.")
        elif issues:
            st.error("Nouveau mot de passe trop faible : il faut " +
                     ", ".join(issues) + ".")
        else:
            db.update_password(user["id"], new_pw)
            db.log_audit("password_changed", "user", user["id"])
            st.success("Mot de passe mis à jour.")

ROLES = ["patient", "doctor", "admin"]

def render_admin(db, user):
    app_header("Administration")
    if not require_admin(user):
        st.error("Accès réservé aux administrateurs.")
        return

    users = db.list_users()

    pending = [u for u in users
               if u.get("role") in ("doctor", "admin")
               and not u.get("approved", True)]
    st.markdown("##### Comptes professionnels en attente de validation")
    if not pending:
        st.caption("Aucun compte en attente.")
    for u in pending:
        c1, c2, c3 = st.columns([3, 1, 1])
        c1.write(f"**{u.get('full_name') or '—'}**")
        c1.caption(u.get("email", ""))
        if c2.button("✔ Valider", key=f"appr_{u['id']}", type="primary"):
            db.set_approved(u["id"], True)
            db.log_audit("account_approved", "user", u["id"])
            st.rerun()
        if c3.button("Refuser", key=f"rej_{u['id']}"):
            db.set_role(u["id"], "patient")
            db.set_approved(u["id"], True)
            db.log_audit("account_rejected", "user", u["id"])
            st.rerun()

    st.divider()
    st.markdown("##### Utilisateurs et rôles")
    admin_flash = st.session_state.pop("admin_flash", None)
    if admin_flash:
        st.success(admin_flash)
    for u in users:
        c1, c2, c3, c4 = st.columns([3, 2, 2, 1])
        c1.write(f"**{u.get('full_name') or '—'}**")
        c1.caption(u.get("email", ""))
        current = u.get("role", "doctor")
        idx = ROLES.index(current) if current in ROLES else 1
        new_role = c2.selectbox("Rôle", ROLES, index=idx,
                                key=f"role_{u['id']}", label_visibility="collapsed")
        mfa = "🔐 MFA" if u.get("mfa_enabled") else "—"
        c3.caption(f"{mfa} · {'validé' if u.get('approved', True) else 'en attente'}")
        if c4.button("MAJ", key=f"upd_{u['id']}"):
            if u["id"] == user["id"] and new_role != "admin":
                st.error("Impossible de retirer ton propre rôle admin.")
            else:
                db.set_role(u["id"], new_role)
                db.log_audit("role_changed", "user", u["id"], {"new_role": new_role})
                st.session_state["admin_flash"] = (
                    f"Rôle de {u.get('email')} → {new_role}")
                st.rerun()

def render_audit(db, user):
    app_header("Journal d'audit")
    if not require_admin(user):
        st.error("Accès réservé aux administrateurs.")
        return
    st.caption("Traçabilité des actions sensibles (connexions, MFA, dossiers, rôles).")
    rows = db.list_audit(200)
    if not rows:
        st.info("Aucun événement enregistré pour l'instant.")
        return
    import pandas as pd

    df = pd.DataFrame([{
        "Date": str(r.get("created_at", ""))[:19].replace("T", " "),
        "Action": r.get("action"),
        "Objet": r.get("entity") or "—",
        "Détail": json.dumps(r.get("meta"), ensure_ascii=False)
                  if r.get("meta") else "",
    } for r in rows])
    st.dataframe(df, width="stretch", hide_index=True)

def main():
    if st.session_state.get("mfa_pending"):
        render_mfa_step()
        return

    user = get_current_user()
    if not user:
        render_auth()
        return

    db = get_backend_db()
    with st.sidebar:
        st.markdown(f"**{user.get('full_name') or user.get('email')}**")
        st.caption(f"{user.get('role', 'doctor')} · "
                   f"{'Supabase' if get_backend()=='supabase' else 'démo locale'}"
                   f"{' · 🔐' if user.get('mfa_enabled') else ''}")
        if is_patient(user):
            options = ["Mes examens", "Mon profil"]
        else:
            options = ["Tableau de bord", "Patients", "Analyse", "Mon profil"]
            if require_admin(user):
                options += ["Administration", "Journal d'audit"]
        goto = st.session_state.pop("nav_goto", None)
        if goto in options:
            st.session_state["nav"] = goto
        if st.session_state.get("nav") not in options:
            st.session_state["nav"] = options[0]
        nav = st.radio("Navigation", options, key="nav")
        st.divider()
        if st.button("Se déconnecter", width="stretch"):
            do_sign_out()
            st.rerun()

    if nav == "Mes examens" and is_patient(user):
        render_my_exams(db, user)
    elif nav == "Tableau de bord" and require_doctor(user):
        render_dashboard(db, user)
    elif nav == "Patients" and require_doctor(user):
        render_patients(db, user)
    elif nav == "Analyse" and require_doctor(user):
        render_analyze(db, user)
    elif nav == "Mon profil":
        render_profile(db, user)
    elif nav == "Administration":
        render_admin(db, user)
    elif nav == "Journal d'audit":
        render_audit(db, user)
    else:
        st.error("Accès non autorisé pour ton rôle.")

    st.caption("— " + MEDICAL_DISCLAIMER)

if __name__ == "__main__":
    main()
