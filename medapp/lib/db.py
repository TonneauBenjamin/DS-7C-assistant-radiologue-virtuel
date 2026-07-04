from __future__ import annotations

import hashlib
import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Any

import streamlit as st

from .config import (
    get_backend,
    supabase_credentials,
    LOCAL_DB_PATH,
    LOCAL_IMAGE_DIR,
    LOCAL_DATA_DIR,
)

def _now() -> str:
    return datetime.now(timezone.utc).isoformat()

class SupabaseDB:
    def __init__(self) -> None:
        from supabase import create_client

        from .config import supabase_service_key

        url, key = supabase_credentials()
        self.client = create_client(url, key)
        self.admin = None
        service_key = supabase_service_key()
        if service_key:
            try:
                self.admin = create_client(url, service_key)
            except Exception:
                self.admin = None

    def sign_up(self, email, password, full_name, role="doctor",
                doctor_id=None):
        if role not in ("doctor", "patient"):
            role = "doctor"
        meta = {"full_name": full_name, "requested_role": role}
        if role == "patient" and doctor_id:
            meta["requested_doctor"] = str(doctor_id)
        ok_msg = ("Compte patient créé. Tu peux te connecter." if role == "patient"
                  else "Compte professionnel créé. Il sera activé après "
                       "validation par un administrateur.")
        if self.admin is not None:
            try:
                self.admin.auth.admin.create_user({
                    "email": email,
                    "password": password,
                    "email_confirm": True,
                    "user_metadata": meta,
                })
                return True, ok_msg
            except Exception as e:
                err = str(e)
                if "already" in err.lower() or "registered" in err.lower():
                    return False, "Cet email est déjà utilisé."
                return False, f"Échec de l'inscription : {err}"
        try:
            res = self.client.auth.sign_up(
                {"email": email, "password": password, "options": {"data": meta}}
            )
            if getattr(res, "session", None) is None:
                return True, (ok_msg + " ⚠️ Confirme d'abord ton adresse via "
                              "l'email envoyé par Supabase (ou demande à un "
                              "admin de confirmer ton compte).")
            return True, ok_msg
        except Exception as e:
            return False, f"Échec de l'inscription : {e}"

    def sign_in(self, email, password):
        try:
            res = self.client.auth.sign_in_with_password(
                {"email": email, "password": password}
            )
            return res.session, "Connecté."
        except Exception as e:
            err = str(e)
            if "not confirmed" in err.lower():
                return None, ("Adresse email non confirmée. Clique le lien "
                              "reçu par email, ou demande à un administrateur "
                              "de confirmer ton compte.")
            return None, "Email ou mot de passe incorrect."

    def sign_out(self):
        try:
            self.client.auth.sign_out()
        except Exception:
            pass

    def current_user(self):
        try:
            user = self.client.auth.get_user()
            if not user or not user.user:
                return None
            uid = user.user.id
            prof = (
                self.client.table("profiles").select("*").eq("id", uid).single().execute()
            )
            p = prof.data or {}
            return {
                "id": uid,
                "email": user.user.email,
                "full_name": p.get("full_name", ""),
                "role": p.get("role", "doctor"),
                "approved": bool(p.get("approved", True)),
                "mfa_enabled": bool(p.get("mfa_enabled", False)),
                "mfa_secret": p.get("mfa_secret"),
                "mfa_backup_codes": p.get("mfa_backup_codes") or [],
            }
        except Exception:
            return None

    def get_user(self, user_id):
        try:
            p = (self.client.table("profiles").select("*")
                 .eq("id", user_id).single().execute()).data or {}
            return {**p, "approved": bool(p.get("approved", True)),
                    "mfa_enabled": bool(p.get("mfa_enabled", False)),
                    "mfa_backup_codes": p.get("mfa_backup_codes") or []}
        except Exception:
            return None

    def get_user_by_email(self, email):
        email = (email or "").strip()
        try:
            rows = (self.client.table("profiles").select("id")
                    .eq("email", email).limit(1).execute()).data or []
            if rows:
                return self.get_user(rows[0]["id"])
        except Exception:
            pass
        if self.admin is not None:
            try:
                page = self.admin.auth.admin.list_users()
                users = getattr(page, "users", page) or []
                for u in users:
                    if (getattr(u, "email", "") or "").lower() == email.lower():
                        got = self.get_user(u.id)
                        if got:
                            return {**got, "email": u.email}
                        return {"id": u.id, "email": u.email, "full_name": "",
                                "role": "doctor", "approved": True,
                                "mfa_enabled": False, "mfa_secret": None,
                                "mfa_backup_codes": []}
            except Exception:
                pass
        return None

    def list_users(self):
        res = self.client.table("profiles").select("*").order("created_at").execute()
        return res.data or []

    def set_role(self, user_id, role):
        self.client.table("profiles").update({"role": role}).eq("id", user_id).execute()

    def set_mfa(self, user_id, secret, enabled, backup_codes):
        self.client.table("profiles").update({
            "mfa_secret": secret, "mfa_enabled": bool(enabled),
            "mfa_backup_codes": backup_codes or [],
        }).eq("id", user_id).execute()

    def update_password(self, user_id, new_password):
        self.client.auth.update_user({"password": new_password})

    def set_password_by_email(self, email, new_password) -> bool:
        if self.admin is None:
            return False
        uid = None
        try:
            rows = (self.admin.table("profiles").select("id")
                    .eq("email", email).limit(1).execute()).data or []
            if rows:
                uid = rows[0]["id"]
        except Exception:
            uid = None
        if uid is None:
            try:
                page = self.admin.auth.admin.list_users()
                users = getattr(page, "users", page) or []
                for u in users:
                    if (getattr(u, "email", "") or "").lower() == email.lower():
                        uid = u.id
                        break
            except Exception:
                return False
        if uid is None:
            return False
        try:
            self.admin.auth.admin.update_user_by_id(
                uid, {"password": new_password})
            return True
        except Exception:
            return False

    def set_approved(self, user_id, value=True):
        self.client.table("profiles").update(
            {"approved": bool(value)}).eq("id", user_id).execute()

    def get_patient_by_user(self, user_id):
        try:
            res = (self.client.table("patients").select("*")
                   .eq("user_id", user_id).limit(1).execute())
            rows = res.data or []
            return rows[0] if rows else None
        except Exception:
            return None

    def link_patient_user(self, patient_id, user_id):
        self.client.table("patients").update(
            {"user_id": user_id}).eq("id", patient_id).execute()

    def list_doctors(self):
        for cli in (self.client, self.admin):
            if cli is None:
                continue
            try:
                rows = (cli.table("profiles")
                        .select("id,full_name,email,role,approved")
                        .in_("role", ["doctor", "admin"])
                        .eq("approved", True).order("full_name")
                        .execute()).data or []
                if rows:
                    return rows
            except Exception:
                continue
        return []

    def set_patient_doctor(self, patient_id, doctor_id):
        self.client.table("patients").update(
            {"doctor_id": doctor_id}).eq("id", patient_id).execute()

    def log_audit(self, action, entity=None, entity_id=None, meta=None):
        try:
            self.client.table("audit_log").insert({
                "actor_id": self._uid(), "action": action, "entity": entity,
                "entity_id": str(entity_id) if entity_id else None,
                "meta": meta,
            }).execute()
        except Exception:
            pass

    def list_audit(self, limit=100):
        try:
            return self.client.table("audit_log").select("*").order(
                "created_at", desc=True).limit(limit).execute().data or []
        except Exception:
            return []

    def list_patients(self, search="", doctor_id=None):
        q = self.client.table("patients").select("*").order("created_at", desc=True)
        if doctor_id:
            q = q.eq("doctor_id", doctor_id)
        res = q.execute()
        rows = res.data or []
        if search:
            s = search.lower()
            rows = [
                r
                for r in rows
                if s in (r.get("full_name") or "").lower()
                or s in (r.get("external_ref") or "").lower()
            ]
        return rows

    def create_patient(self, data):
        data = {**data, "created_by": self._uid()}
        res = self.client.table("patients").insert(data).execute()
        return (res.data or [{}])[0]

    def get_patient(self, pid):
        res = self.client.table("patients").select("*").eq("id", pid).single().execute()
        return res.data

    def list_scans(self, patient_id=None):
        q = self.client.table("scans").select("*").order("created_at", desc=True)
        if patient_id:
            q = q.eq("patient_id", patient_id)
        return q.execute().data or []

    def create_scan(self, data, image_bytes, filename):
        path = None
        if image_bytes:
            path = f"{uuid.uuid4().hex}_{filename}"
            self.client.storage.from_("radios").upload(
                path, image_bytes, {"content-type": "image/*"}
            )
        data = {**data, "image_path": path, "uploaded_by": self._uid()}
        if isinstance(data.get("result_json"), str):
            import json as _json
            try:
                data["result_json"] = _json.loads(data["result_json"])
            except Exception:
                pass
        res = self.client.table("scans").insert(data).execute()
        return (res.data or [{}])[0]

    def image_url(self, image_path):
        if not image_path:
            return None
        try:
            r = self.client.storage.from_("radios").create_signed_url(image_path, 3600)
            return r.get("signedURL") or r.get("signedUrl")
        except Exception:
            return None

    def image_bytes(self, image_path):
        if not image_path:
            return None
        try:
            return self.client.storage.from_("radios").download(image_path)
        except Exception:
            return None

    def mark_reviewed(self, scan_id, value=True):
        self.client.table("scans").update({"reviewed": value}).eq("id", scan_id).execute()

    def stats(self, doctor_id=None):
        patients = self.list_patients(doctor_id=doctor_id)
        scans = self.list_scans()
        if doctor_id:
            pids = {p["id"] for p in patients}
            scans = [s for s in scans if s.get("patient_id") in pids]
        return _compute_stats(scans, len(patients))

    def _uid(self):
        u = self.current_user()
        return u["id"] if u else None

class LocalDB:

    def __init__(self) -> None:
        LOCAL_DATA_DIR.mkdir(parents=True, exist_ok=True)
        LOCAL_IMAGE_DIR.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(LOCAL_DB_PATH), check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self):
        c = self.conn.cursor()
        c.executescript(
            """
            create table if not exists users(
                id text primary key, email text unique, pw_hash text,
                full_name text, role text default 'doctor', created_at text);
            create table if not exists patients(
                id text primary key, external_ref text, full_name text,
                email text, birth_date text, sex text, notes text,
                created_by text, created_at text);
            create table if not exists scans(
                id text primary key, patient_id text, image_path text,
                predicted_class text, confidence real, image_quality text,
                model_name text, result_json text, reviewed integer default 0,
                uploaded_by text, created_at text);
            create table if not exists audit_log(
                id text primary key, actor_id text, action text, entity text,
                entity_id text, meta text, created_at text);
            """
        )
        pcols = [r[1] for r in c.execute("PRAGMA table_info(patients)").fetchall()]
        if "email" not in pcols:
            c.execute("alter table patients add column email text")
        if "user_id" not in pcols:
            c.execute("alter table patients add column user_id text")
        if "doctor_id" not in pcols:
            c.execute("alter table patients add column doctor_id text")
        ucols = [r[1] for r in c.execute("PRAGMA table_info(users)").fetchall()]
        for col, ddl in (
            ("mfa_secret", "alter table users add column mfa_secret text"),
            ("mfa_enabled", "alter table users add column mfa_enabled integer default 0"),
            ("mfa_backup_codes", "alter table users add column mfa_backup_codes text"),
            ("approved", "alter table users add column approved integer default 1"),
        ):
            if col not in ucols:
                c.execute(ddl)
        if not c.execute("select 1 from users where email='admin@demo.local'").fetchone():
            c.execute(
                "insert into users(id,email,pw_hash,full_name,role,created_at,"
                "mfa_enabled,approved) values(?,?,?,?,?,?,0,1)",
                (uuid.uuid4().hex, "admin@demo.local", _hash("admin"),
                 "Administrateur démo", "admin", _now()),
            )
        self.conn.commit()

    def sign_up(self, email, password, full_name, role="doctor",
                doctor_id=None):
        if role not in ("doctor", "patient"):
            role = "doctor"
        c = self.conn.cursor()
        if c.execute("select 1 from users where email=?", (email,)).fetchone():
            return False, "Cet email est déjà utilisé."
        uid = uuid.uuid4().hex
        approved = 1 if role == "patient" else 0
        c.execute(
            "insert into users(id,email,pw_hash,full_name,role,created_at,"
            "mfa_enabled,approved) values(?,?,?,?,?,?,0,?)",
            (uid, email, _hash(password), full_name, role, _now(), approved),
        )
        if role == "patient":
            c.execute(
                "insert into patients(id,full_name,email,user_id,doctor_id,"
                "created_at) values(?,?,?,?,?,?)",
                (uuid.uuid4().hex, full_name, email, uid, doctor_id, _now()))
            msg = "Compte patient créé. Tu peux te connecter."
        else:
            msg = ("Compte professionnel créé. Il sera activé après "
                   "validation par un administrateur.")
        self.conn.commit()
        return True, msg

    def sign_in(self, email, password):
        row = self.conn.execute(
            "select * from users where email=?", (email,)
        ).fetchone()
        if not row or not _verify(password, row["pw_hash"]):
            return None, "Email ou mot de passe incorrect."
        if not row["approved"]:
            return None, ("Compte en attente de validation par un "
                          "administrateur.")
        return {"user_id": row["id"]}, "Connecté."

    def sign_out(self):
        pass

    def _user_dict(self, row):
        import json as _json
        codes = row["mfa_backup_codes"]
        return {
            "id": row["id"], "email": row["email"],
            "full_name": row["full_name"], "role": row["role"],
            "approved": bool(row["approved"]),
            "mfa_enabled": bool(row["mfa_enabled"]),
            "mfa_secret": row["mfa_secret"],
            "mfa_backup_codes": _json.loads(codes) if codes else [],
        }

    def current_user(self):
        uid = st.session_state.get("local_user_id")
        if not uid:
            return None
        row = self.conn.execute("select * from users where id=?", (uid,)).fetchone()
        return self._user_dict(row) if row else None

    def get_user(self, user_id):
        row = self.conn.execute("select * from users where id=?",
                                (user_id,)).fetchone()
        return self._user_dict(row) if row else None

    def get_user_by_email(self, email):
        row = self.conn.execute("select * from users where email=?",
                                (email,)).fetchone()
        return self._user_dict(row) if row else None

    def set_mfa(self, user_id, secret, enabled, backup_codes):
        import json as _json
        self.conn.execute(
            "update users set mfa_secret=?, mfa_enabled=?, mfa_backup_codes=? "
            "where id=?",
            (secret, 1 if enabled else 0,
             _json.dumps(backup_codes or []), user_id))
        self.conn.commit()

    def update_password(self, user_id, new_password):
        self.conn.execute("update users set pw_hash=? where id=?",
                          (_hash(new_password), user_id))
        self.conn.commit()

    def set_password_by_email(self, email, new_password) -> bool:
        row = self.conn.execute("select id from users where email=?",
                                (email,)).fetchone()
        if not row:
            return False
        self.update_password(row["id"], new_password)
        return True

    def set_approved(self, user_id, value=True):
        self.conn.execute("update users set approved=? where id=?",
                          (1 if value else 0, user_id))
        self.conn.commit()

    def get_patient_by_user(self, user_id):
        row = self.conn.execute("select * from patients where user_id=?",
                                (user_id,)).fetchone()
        return dict(row) if row else None

    def link_patient_user(self, patient_id, user_id):
        self.conn.execute("update patients set user_id=? where id=?",
                          (user_id, patient_id))
        self.conn.commit()

    def list_users(self):
        return [dict(r) for r in self.conn.execute(
            "select * from users order by created_at").fetchall()]

    def set_role(self, user_id, role):
        self.conn.execute("update users set role=? where id=?", (role, user_id))
        self.conn.commit()

    def log_audit(self, action, entity=None, entity_id=None, meta=None):
        self.conn.execute(
            "insert into audit_log values(?,?,?,?,?,?,?)",
            (uuid.uuid4().hex, self._uid(), action, entity,
             str(entity_id) if entity_id else None,
             __import__("json").dumps(meta) if meta else None, _now()))
        self.conn.commit()

    def list_audit(self, limit=100):
        return [dict(r) for r in self.conn.execute(
            "select * from audit_log order by created_at desc limit ?",
            (limit,)).fetchall()]

    def list_patients(self, search="", doctor_id=None):
        rows = [dict(r) for r in self.conn.execute(
            "select * from patients order by created_at desc").fetchall()]
        if doctor_id:
            rows = [r for r in rows if r.get("doctor_id") == doctor_id]
        if search:
            s = search.lower()
            rows = [r for r in rows if s in (r["full_name"] or "").lower()
                    or s in (r.get("external_ref") or "").lower()]
        return rows

    def list_doctors(self):
        rows = self.conn.execute(
            "select * from users where role in ('doctor','admin') "
            "and approved=1 order by full_name").fetchall()
        return [self._user_dict(r) for r in rows]

    def set_patient_doctor(self, patient_id, doctor_id):
        self.conn.execute("update patients set doctor_id=? where id=?",
                          (doctor_id, patient_id))
        self.conn.commit()

    def create_patient(self, data):
        pid = uuid.uuid4().hex
        rec = {"id": pid, "external_ref": data.get("external_ref"),
               "full_name": data["full_name"], "email": data.get("email"),
               "birth_date": data.get("birth_date"),
               "sex": data.get("sex"), "notes": data.get("notes"),
               "doctor_id": data.get("doctor_id"),
               "user_id": data.get("user_id"),
               "created_by": self._uid(), "created_at": _now()}
        self.conn.execute(
            "insert into patients(id,external_ref,full_name,email,birth_date,"
            "sex,notes,doctor_id,user_id,created_by,created_at) "
            "values(:id,:external_ref,:full_name,:email,:birth_date,"
            ":sex,:notes,:doctor_id,:user_id,:created_by,:created_at)", rec)
        self.conn.commit()
        return rec

    def get_patient(self, pid):
        row = self.conn.execute("select * from patients where id=?", (pid,)).fetchone()
        return dict(row) if row else None

    def list_scans(self, patient_id=None):
        if patient_id:
            rows = self.conn.execute(
                "select * from scans where patient_id=? order by created_at desc",
                (patient_id,)).fetchall()
        else:
            rows = self.conn.execute(
                "select * from scans order by created_at desc").fetchall()
        return [dict(r) for r in rows]

    def create_scan(self, data, image_bytes, filename):
        sid = uuid.uuid4().hex
        path = None
        if image_bytes:
            path = str(LOCAL_IMAGE_DIR / f"{sid}_{filename}")
            with open(path, "wb") as f:
                f.write(image_bytes)
        rec = {"id": sid, "patient_id": data["patient_id"], "image_path": path,
               "predicted_class": data.get("predicted_class"),
               "confidence": data.get("confidence"),
               "image_quality": data.get("image_quality"),
               "model_name": data.get("model_name"),
               "result_json": data.get("result_json"), "reviewed": 0,
               "uploaded_by": self._uid(), "created_at": _now()}
        self.conn.execute(
            "insert into scans values(:id,:patient_id,:image_path,:predicted_class,"
            ":confidence,:image_quality,:model_name,:result_json,:reviewed,"
            ":uploaded_by,:created_at)", rec)
        self.conn.commit()
        return rec

    def image_url(self, image_path):
        return image_path

    def image_bytes(self, image_path):
        if not image_path:
            return None
        try:
            from pathlib import Path as _P
            return _P(image_path).read_bytes()
        except Exception:
            return None

    def mark_reviewed(self, scan_id, value=True):
        self.conn.execute("update scans set reviewed=? where id=?",
                          (1 if value else 0, scan_id))
        self.conn.commit()

    def stats(self, doctor_id=None):
        scans = self.list_scans()
        if doctor_id:
            pids = {p["id"] for p in self.list_patients(doctor_id=doctor_id)}
            scans = [s for s in scans if s.get("patient_id") in pids]
            return _compute_stats(scans, len(pids))
        n_pat = self.conn.execute("select count(*) c from patients").fetchone()["c"]
        return _compute_stats(scans, n_pat)

    def _uid(self):
        return st.session_state.get("local_user_id")

def _hash(pw: str) -> str:
    from .security import hash_password
    return hash_password(pw)

def _verify(pw: str, stored: str) -> bool:
    from .security import verify_password
    if stored and "$" not in stored and len(stored) == 64:
        return hashlib.sha256(pw.encode()).hexdigest() == stored
    return verify_password(pw, stored)

def _compute_stats(scans: list[dict], n_patients: int) -> dict[str, Any]:
    n = len(scans)
    by_class: dict[str, int] = {}
    confs, reviewed = [], 0
    for s in scans:
        by_class[s.get("predicted_class") or "?"] = (
            by_class.get(s.get("predicted_class") or "?", 0) + 1
        )
        if s.get("confidence") is not None:
            try:
                confs.append(float(s["confidence"]))
            except (TypeError, ValueError):
                pass
        if s.get("reviewed") in (1, True):
            reviewed += 1
    return {
        "n_patients": n_patients,
        "n_scans": n,
        "n_suspected": by_class.get("suspected_opacity", 0),
        "n_normal": by_class.get("normal", 0),
        "n_uncertain": by_class.get("uncertain", 0),
        "by_class": by_class,
        "avg_confidence": round(sum(confs) / len(confs), 3) if confs else 0.0,
        "reviewed_rate": round(reviewed / n, 3) if n else 0.0,
        "scans": scans,
    }

@st.cache_resource(show_spinner=False)
def _make_local_db():
    return LocalDB()

def get_backend_db():
    if get_backend() == "local":
        return _make_local_db()
    if "sb_db" not in st.session_state:
        st.session_state["sb_db"] = SupabaseDB()
    return st.session_state["sb_db"]
