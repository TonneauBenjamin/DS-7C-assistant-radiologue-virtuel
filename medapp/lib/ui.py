from __future__ import annotations

import base64
from functools import lru_cache
from pathlib import Path

import streamlit as st

ASSETS = Path(__file__).resolve().parent.parent / "assets"

@lru_cache(maxsize=2)
def _logo_data_uri() -> str:
    try:
        raw = (ASSETS / "logo.png").read_bytes()
        return "data:image/png;base64," + base64.b64encode(raw).decode()
    except Exception:
        return ""

ACCENT = "#0f766e"
INK = "#16323f"
MUTED = "#5b7282"
BORDER = "#dbe4ec"
SURFACE = "#ffffff"

CLASS_STYLE = {
    "suspected_opacity": ("#b3261e", "Opacité suspecte"),
    "normal": ("#1a7f4b", "Normal"),
    "uncertain": ("#9a6700", "Incertain"),
}

ECG_SVG = (
    '<svg class="ecg" viewBox="0 0 560 26" preserveAspectRatio="none" '
    'xmlns="http://www.w3.org/2000/svg"><path d="M0 13 H210 l8 -5 8 5 10 0 '
    '6 -11 8 22 6 -11 12 0 8 -4 8 4 H560" fill="none" stroke="#0f766e" '
    'stroke-width="2" stroke-linejoin="round" stroke-linecap="round" '
    'opacity=".85"/></svg>'
)

def inject_css() -> None:
    st.markdown(
        """
        <style>
        @import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@400;500;600;700&family=IBM+Plex+Mono:wght@400;500&display=swap');

        html, body, [class*="css"] { font-family: 'IBM Plex Sans', sans-serif; }

        /* Signature : tracé ECG sous l'en-tête */
        .ecg { display:block; width:100%; height:22px; margin:.3rem 0 1rem; }

        .pneumo-brand { display:flex; align-items:baseline; gap:.7rem; }
        .pneumo-brand h1 {
            font-size:1.55rem; font-weight:700; letter-spacing:-.01em;
            margin:0; color:#16323f;
        }
        .pneumo-brand .tag {
            font-family:'IBM Plex Mono',monospace; font-size:.7rem;
            color:#0f766e; border:1px solid #0f766e55; background:#0f766e0d;
            padding:.12rem .55rem; border-radius:999px; text-transform:uppercase;
            letter-spacing:.08em;
        }
        .pneumo-sub { color:#5b7282; font-size:.92rem; margin:.15rem 0 0; }

        /* Carte d'authentification centrée */
        .auth-card {
            background:#ffffff; border:1px solid #dbe4ec; border-radius:14px;
            padding:1.6rem 1.7rem 1.2rem; box-shadow:0 1px 2px rgba(22,50,63,.04),
            0 8px 24px rgba(22,50,63,.06);
        }
        .auth-brand { text-align:center; margin-bottom:.2rem; }
        .auth-brand .logo { font-size:2rem; line-height:1; }
        .auth-brand .logo-img { width:220px; max-width:70%; display:block;
                                margin:0 auto .4rem auto; }
        .auth-brand h1 { font-size:1.35rem; font-weight:700; color:#16323f;
            margin:.35rem 0 0; letter-spacing:-.01em; }
        .auth-brand p { color:#5b7282; font-size:.86rem; margin:.2rem 0 0; }

        /* Badge de classe */
        .cls-badge {
            display:inline-block; font-family:'IBM Plex Mono',monospace;
            font-weight:500; font-size:.85rem; padding:.28rem .7rem;
            border-radius:6px; border:1px solid;
        }
        /* Cartes de métriques */
        .metric-card {
            background:#ffffff; border:1px solid #dbe4ec; border-radius:12px;
            padding:1rem 1.1rem; box-shadow:0 1px 2px rgba(22,50,63,.04);
        }
        .metric-card .v { font-size:1.9rem; font-weight:700; line-height:1; }
        .metric-card .l { color:#5b7282; font-size:.76rem; text-transform:uppercase;
            letter-spacing:.06em; margin-top:.35rem; }

        div[data-testid="stMetricValue"] { font-family:'IBM Plex Mono',monospace; }
        section[data-testid="stSidebar"] {
            border-right:1px solid #dbe4ec; background:#ffffff;
        }
        /* Boutons primaires bien pleins */
        button[kind="primary"] { border-radius:8px; }
        </style>
        """,
        unsafe_allow_html=True,
    )

def app_header(subtitle: str | None = None) -> None:
    from .config import APP_TITLE, APP_SUBTITLE

    st.markdown(
        f'<div class="pneumo-brand"><h1>{APP_TITLE.split("—")[0].strip()}'
        f'</h1><span class="tag">radiologie</span></div>'
        f'<p class="pneumo-sub">{subtitle or APP_SUBTITLE}</p>' + ECG_SVG,
        unsafe_allow_html=True,
    )

def auth_brand(subtitle: str) -> None:
    uri = _logo_data_uri()
    logo = (f'<img src="{uri}" alt="TrueVision" class="logo-img"/>'
            if uri else '<div class="logo">👁️</div>')
    st.markdown(
        f'<div class="auth-brand">{logo}'
        f'<p>{subtitle}</p></div>' + ECG_SVG,
        unsafe_allow_html=True,
    )

def class_badge(cls: str) -> str:
    color, label = CLASS_STYLE.get(cls, ("#5b7282", cls or "—"))
    return (
        f'<span class="cls-badge" style="color:{color};border-color:{color}55;'
        f'background:{color}0f">{label}</span>'
    )

def metric_card(value, label, color=INK) -> str:
    if str(color).lower() in ("#e2e8f0", "#fff", "#ffffff"):
        color = INK
    return (
        f'<div class="metric-card"><div class="v" style="color:{color}">{value}</div>'
        f'<div class="l">{label}</div></div>'
    )

def confidence_bar(conf: float) -> None:
    pct = int(round(float(conf) * 100))
    st.markdown(
        f"""<div style="background:#e6edf3;border-radius:6px;height:10px;overflow:hidden">
        <div style="width:{pct}%;height:100%;background:linear-gradient(90deg,#0f766e,#14b8a6)"></div>
        </div><div style="font-family:'IBM Plex Mono',monospace;font-size:.8rem;
        color:#5b7282;margin-top:.25rem">confiance {pct}%</div>""",
        unsafe_allow_html=True,
    )
