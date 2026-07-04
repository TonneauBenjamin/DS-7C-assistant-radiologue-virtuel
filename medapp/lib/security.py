from __future__ import annotations

import base64
import hashlib
import secrets as _secrets
import struct as _struct
import hmac
import os
import re
import time

_ALGO = "pbkdf2_sha256"
_ITERATIONS = 200_000

def hash_password(password: str, iterations: int = _ITERATIONS) -> str:
    salt = os.urandom(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, iterations)
    return "${}${}${}${}".format(
        _ALGO,
        iterations,
        base64.b64encode(salt).decode(),
        base64.b64encode(dk).decode(),
    ).lstrip("$")

def verify_password(password: str, stored: str) -> bool:
    try:
        algo, iters, salt_b64, dk_b64 = stored.split("$")
        if algo != _ALGO:
            return False
        salt = base64.b64decode(salt_b64)
        expected = base64.b64decode(dk_b64)
        dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, int(iters))
        return hmac.compare_digest(dk, expected)
    except Exception:
        return False

def password_issues(pw: str) -> list[str]:
    issues = []
    if len(pw) < 8:
        issues.append("au moins 8 caractères")
    if not re.search(r"[A-Z]", pw):
        issues.append("une majuscule")
    if not re.search(r"[a-z]", pw):
        issues.append("une minuscule")
    if not re.search(r"\d", pw):
        issues.append("un chiffre")
    return issues

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

def is_valid_email(email: str) -> bool:
    return bool(_EMAIL_RE.match((email or "").strip()))

MAX_ATTEMPTS = 5
LOCK_SECONDS = 300

def register_failed_attempt(store: dict, email: str) -> None:
    key = f"lockout::{email.lower()}"
    rec = store.get(key, {"count": 0, "until": 0})
    rec["count"] += 1
    if rec["count"] >= MAX_ATTEMPTS:
        rec["until"] = time.time() + LOCK_SECONDS
        rec["count"] = 0
    store[key] = rec

def clear_attempts(store: dict, email: str) -> None:
    store.pop(f"lockout::{email.lower()}", None)

def lockout_remaining(store: dict, email: str) -> int:
    rec = store.get(f"lockout::{email.lower()}")
    if not rec:
        return 0
    remaining = int(rec.get("until", 0) - time.time())
    return max(0, remaining)

def mask_email(email: str) -> str:
    if not email or "@" not in email:
        return "—"
    local, _, domain = email.partition("@")
    head = local[:2] if len(local) > 2 else local[:1]
    return f"{head}***@{domain}"

TOTP_DIGITS = 6
TOTP_PERIOD = 30

def generate_totp_secret() -> str:
    return base64.b32encode(_secrets.token_bytes(20)).decode()

def totp_code(secret_b32: str, timestamp: float | None = None) -> str:
    if timestamp is None:
        timestamp = time.time()
    counter = int(timestamp) // TOTP_PERIOD
    key = base64.b32decode(secret_b32.upper() + "=" * (-len(secret_b32) % 8))
    msg = _struct.pack(">Q", counter)
    digest = hmac.new(key, msg, hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    code = (_struct.unpack(">I", digest[offset:offset + 4])[0] & 0x7FFFFFFF)
    return str(code % (10 ** TOTP_DIGITS)).zfill(TOTP_DIGITS)

def verify_totp(secret_b32: str, code: str, window: int = 1) -> bool:
    code = (code or "").strip().replace(" ", "")
    if not code.isdigit() or len(code) != TOTP_DIGITS:
        return False
    now = time.time()
    for w in range(-window, window + 1):
        expected = totp_code(secret_b32, now + w * TOTP_PERIOD)
        if hmac.compare_digest(expected, code):
            return True
    return False

def totp_provisioning_uri(secret_b32: str, email: str,
                          issuer: str = "TrueVision") -> str:
    from urllib.parse import quote
    label = quote(f"{issuer}:{email}")
    return (f"otpauth://totp/{label}?secret={secret_b32}"
            f"&issuer={quote(issuer)}&digits={TOTP_DIGITS}&period={TOTP_PERIOD}")

BACKUP_CODE_COUNT = 8

def generate_backup_codes(n: int = BACKUP_CODE_COUNT) -> list[str]:
    alphabet = "23456789ABCDEFGHJKMNPQRSTUVWXYZ"
    out = []
    for _ in range(n):
        raw = "".join(_secrets.choice(alphabet) for _ in range(8))
        out.append(f"{raw[:4]}-{raw[4:]}")
    return out

def hash_backup_code(code: str) -> str:
    norm = (code or "").strip().upper().replace("-", "")
    return hashlib.sha256(norm.encode()).hexdigest()

def consume_backup_code(code: str, hashed_list: list[str]) -> list[str] | None:
    h = hash_backup_code(code)
    for stored in hashed_list:
        if hmac.compare_digest(stored, h):
            return [x for x in hashed_list if x != stored]
    return None

CAPTCHA_LENGTH = 5
CAPTCHA_TTL = 180

def new_captcha_text(length: int = CAPTCHA_LENGTH) -> str:
    alphabet = "23456789ABCDEFGHJKMNPQRSTUVWXYZ"
    return "".join(_secrets.choice(alphabet) for _ in range(length))

def store_captcha(store: dict, text: str, key: str = "captcha") -> None:
    store[f"{key}::hash"] = hashlib.sha256(text.upper().encode()).hexdigest()
    store[f"{key}::until"] = time.time() + CAPTCHA_TTL

def verify_captcha(store: dict, answer: str, key: str = "captcha") -> bool:
    h = store.get(f"{key}::hash")
    until = store.get(f"{key}::until", 0)
    store.pop(f"{key}::hash", None)
    store.pop(f"{key}::until", None)
    if not h or time.time() > until:
        return False
    given = hashlib.sha256((answer or "").strip().upper().encode()).hexdigest()
    return hmac.compare_digest(h, given)

RESET_CODE_TTL = 600
RESET_RESEND_COOLDOWN = 60

def new_reset_code() -> str:
    return str(_secrets.randbelow(10 ** 6)).zfill(6)

def store_reset_code(store: dict, email: str, code: str) -> None:
    key = f"pwreset::{email.lower()}"
    store[f"{key}::hash"] = hashlib.sha256(code.encode()).hexdigest()
    store[f"{key}::until"] = time.time() + RESET_CODE_TTL
    store[f"{key}::cooldown"] = time.time() + RESET_RESEND_COOLDOWN

def reset_cooldown_remaining(store: dict, email: str) -> int:
    remaining = int(store.get(f"pwreset::{email.lower()}::cooldown", 0) - time.time())
    return max(0, remaining)

def verify_reset_code(store: dict, email: str, code: str) -> bool:
    key = f"pwreset::{email.lower()}"
    h = store.get(f"{key}::hash")
    until = store.get(f"{key}::until", 0)
    store.pop(f"{key}::hash", None)
    store.pop(f"{key}::until", None)
    if not h or time.time() > until:
        return False
    given = hashlib.sha256((code or "").strip().encode()).hexdigest()
    return hmac.compare_digest(h, given)
