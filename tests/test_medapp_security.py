import base64
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "medapp"))

from lib import security

def test_totp_rfc6238_vector():
    secret = base64.b32encode(b"12345678901234567890").decode()
    assert security.totp_code(secret, 59) == "287082"
    assert security.totp_code(secret, 1111111109) == "081804"
    assert security.totp_code(secret, 1234567890) == "005924"

def test_totp_roundtrip_and_window():
    secret = security.generate_totp_secret()
    code = security.totp_code(secret)
    assert security.verify_totp(secret, code)
    assert not security.verify_totp(secret, "abcdef")
    assert not security.verify_totp(secret, "12345")

def test_backup_codes_single_use():
    codes = security.generate_backup_codes()
    assert len(codes) == security.BACKUP_CODE_COUNT
    hashed = [security.hash_backup_code(c) for c in codes]
    rest = security.consume_backup_code(codes[0], hashed)
    assert rest is not None and len(rest) == len(hashed) - 1
    assert security.consume_backup_code(codes[0], rest) is None

def test_captcha_verify_and_expiry():
    store = {}
    text = security.new_captcha_text()
    security.store_captcha(store, text)
    assert security.verify_captcha(store, text.lower())
    assert not security.verify_captcha(store, text)
    security.store_captcha(store, text)
    store["captcha::until"] = 0
    assert not security.verify_captcha(store, text)

def test_captcha_image_and_qr_are_png():
    from lib.captcha import captcha_image_bytes, qr_png_bytes
    assert captcha_image_bytes("A7K2M")[:4] == b"\x89PNG"
    uri = security.totp_provisioning_uri("ABC234", "x@y.fr")
    assert uri.startswith("otpauth://totp/")
    assert qr_png_bytes(uri)[:4] == b"\x89PNG"

def test_password_hash_and_policy():
    h = security.hash_password("Abcdef12")
    assert security.verify_password("Abcdef12", h)
    assert not security.verify_password("autre", h)
    assert security.password_issues("abc") != []
    assert security.password_issues("Abcdef12") == []

def test_reset_code_flow():
    store = {}
    code = security.new_reset_code()
    assert len(code) == 6 and code.isdigit()
    security.store_reset_code(store, "User@X.fr", code)
    assert security.reset_cooldown_remaining(store, "user@x.fr") > 0
    assert security.verify_reset_code(store, "user@x.fr", code)
    assert not security.verify_reset_code(store, "user@x.fr", code)
    security.store_reset_code(store, "user@x.fr", code)
    store["pwreset::user@x.fr::until"] = 0
    assert not security.verify_reset_code(store, "user@x.fr", code)

def test_vision_locates_zone_and_annotates_png():
    from lib.vision import annotate_image, locate_suspicious_zone
    root = Path(__file__).resolve().parents[1]
    img = (root / "data" / "sample_images" / "CXR_SYN_002_suspected_opacity.png").read_bytes()
    box = locate_suspicious_zone(img)
    assert box is not None and box[0] < box[2] and box[1] < box[3]
    out, found = annotate_image(img)
    assert found and out[:4] == b"\x89PNG" and out != img
    # image illisible : pas d'annotation plutôt qu'un cercle arbitraire
    assert annotate_image(b"not-an-image") == (b"not-an-image", False)
