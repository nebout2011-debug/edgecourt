"""Interface EDGECOURT (Streamlit, 127.0.0.1) — style « Terminal + Premium », 8 écrans.

Site de PRÉDICTION uniquement : aucun pari, aucun dépôt, aucun compte ni lien bookmaker.
Aucune note A/B, aucun badge « fiable » : des probabilités, des effectifs et des statuts de preuve.
Tout chiffre qui ne vient pas du moteur est étiqueté « Données d'exemple ».
"""
from __future__ import annotations

import base64
import hmac
import json
import math
import re
import sys
import tempfile
import threading
import time
import unicodedata
from functools import lru_cache
from html import escape
from pathlib import Path
from urllib.parse import urlencode

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
import streamlit.components.v1 as components
import streamlit_shadcn_ui as ui
import facade  # streamlit-facade : seulement l'accordéon du Lexique (son thème global n'est pas chargé)

# Streamlit Cloud lance `streamlit run src/edgecourt/ui/app.py` sans installer le paquet : on rend `src/` importable.
# En local (pip install -e .) c'est le même dossier, donc sans effet.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from edgecourt import config, pipeline  # noqa: E402
from edgecourt.ui import news
from edgecourt.data import connectors, store
from edgecourt.models.markets import dist_from_params

ASSETS = Path(__file__).resolve().parents[3] / "assets"
st.set_page_config(page_title="EDGECOURT", page_icon=str(ASSETS / "logo-app-icon.png"), layout="wide",
                   initial_sidebar_state="collapsed")  # barre latérale = seulement le lien Admin, repliée par défaut

DAYS = ["lun.", "mar.", "mer.", "jeu.", "ven.", "sam.", "dim."]
LONG_DAYS = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]
MONTHS = ["janv.", "févr.", "mars", "avr.", "mai", "juin", "juil.", "août", "sept.", "oct.", "nov.", "déc."]
LONG_MONTHS = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août", "septembre", "octobre", "novembre", "décembre"]
BANNER = ("⚠️ Attention: ceci n'est pas un site de pari. EDGECOURT est un site de prédiction — notre ambition: devenir le meilleur "
          "site de prédiction que le monde ait jamais connu. Nos prédictions sont des conseils et des idées pour vous aider à juger — "
          "la décision finale vous appartient.")
ACCENT, RED = "#0B6E4F", "#c8553d"
# Photos d'illustration de la maquette, seulement pour les ligues présentes dans le moteur (soccer = Premier League, cf. config).
LEAGUE_IMG = {"nba": ("nba.jpg", "Arène de basket NBA sous les lumières"),
              "soccer": ("premier-league.jpg", "Stade de Premier League la nuit, sous les projecteurs"),
              "laliga": ("la-liga.webp", "Stade de football espagnol affichant La Liga"),
              "seriea": ("serie-a.jpg", "L’Allianz Stadium de Turin, vu du ciel"),
              "bundesliga": ("bundesliga.webp", "Stade de Bundesliga la nuit"),
              "ligue1": ("ligue-1.webp", "Stade de Ligue 1 au coucher du soleil"),
              "championship": ("championship.jpg", "Elland Road, stade de football anglais vu du ciel")}
# Sports du moteur (sélecteur) et compétition réelle couverte par chacun (soccer = config.SOCCER_COMPETITION).
SPORT_NAME = {"soccer": "Football", "nba": "Basket", "nfl": "Football américain"}
COMP = {"soccer": ("Premier League", f"Angleterre · saison {config.SOCCER_COMPETITION[1].replace('/20', '/')}"),
        "nba": ("NBA", "Amérique du Nord"), "nfl": ("NFL", "États-Unis")}
TAGLINE = "La prédiction, prouvée en public."
# Barre des sports : les 5 sports du site. Hockey et baseball n'ont pas encore de données moteur → ligues « Bientôt ».
NAV_SPORTS = {"soccer": "Football", "nba": "Basketball", "nfl": "Football Américain", "nhl": "Hockey", "mlb": "Baseball"}
SPORT_LEAGUES = {"soccer": ["Premier League", "La Liga", "Serie A", "Bundesliga", "Ligue 1", "Championship",
                            "Coupes nationales", "International"],
                 "nba": ["NBA", "WNBA"], "nfl": ["NFL"], "nhl": ["NHL"], "mlb": ["MLB"]}
REGULAR = {"regular", "REG", "league"}  # matchs de saison régulière (le classement exclut les phases finales)
# Compétitions de la maquette sans données dans le moteur : affichées « Bientôt », sans match ni chiffre.
SOON_LEAGUES = [("laliga", "La Liga", "Espagne"), ("seriea", "Serie A", "Italie"), ("bundesliga", "Bundesliga", "Allemagne"),
                ("ligue1", "Ligue 1", "France"), ("championship", "Championship", "Angleterre · 2e division")]
SOON_CUPS = [("FA Cup", "Angleterre · coupe nationale"), ("EFL Cup", "Angleterre · coupe de la Ligue"),
             ("Coupe de France", "France · coupe nationale"), ("DFB-Pokal", "Allemagne · coupe nationale"),
             ("Coppa Italia", "Italie · coupe nationale"), ("Copa del Rey", "Espagne · coupe nationale")]
SOON_INTL = [("UEFA Nations League", "Sélections européennes"), ("Éliminatoires Coupe du Monde — Europe", "Sélections européennes"),
             ("Éliminatoires Coupe du Monde — Amérique du Sud", "Sélections sud-américaines")]
SOON_US = [("WNBA", "États-Unis · basket féminin"), ("NHL", "Amérique du Nord · hockey"), ("MLB", "Amérique du Nord · baseball")]
SOON = "Bientôt — pas encore de données"
PHOTO_CREDIT = ("Sources des photos : premierleague.com · apuestasfutbolparahoyes.com · sportsrender.com · fussball24wetten-de.com · "
                "soccerupdatesnow.com · Pexels (Elland Road) · wallpapers.com · wnba.com · massloadedvinyldirect.com · Reuters (MLB). "
                "Photos d’illustration uniquement.")

CSS = """
<style>
:root {--ink:#0d0f0e; --paper:#fbfbf8; --muted:#6b716e; --line:#e4e4de; --accent:#0B6E4F; --red:#c8553d;
       --mono: ui-monospace, "Cascadia Mono", "SF Mono", Menlo, Consolas, monospace;
       --display: "Segoe UI Variable Display", "Inter", "Helvetica Neue", system-ui, sans-serif;}
html, body, .stApp {background:var(--paper); color:var(--ink);}
header[data-testid="stHeader"] {display:none;}
.block-container {padding-top:0 !important; max-width:1240px;}
.ec-banner {background:#fff3cd; color:#4d3800; border-bottom:1px solid #f0d58a; padding:12px 18px; font-size:.92rem; line-height:1.45;}
[data-testid="stImage"] img {margin-top:18px; mix-blend-mode:multiply;}
.st-key-ec_admin {position:fixed; bottom:16px; opacity:.55;}
.st-key-ec_admin a {font-size:.75rem;}
[data-testid="stPageLink"] a {font-family:var(--mono); font-size:.8rem; text-transform:uppercase; letter-spacing:.06em; padding:2px 6px;}
.ec-kicker {font-family:var(--mono); font-size:.78rem; letter-spacing:.14em; text-transform:uppercase; color:var(--muted); margin-top:28px;}
.ec-h1 {font-family:var(--display); font-weight:750; font-size:clamp(2.4rem, 6vw, 4.6rem); line-height:1.02; letter-spacing:-.03em;
        margin:6px 0 10px;}
.ec-h2 {font-family:var(--display); font-weight:700; font-size:clamp(1.6rem, 3.4vw, 2.4rem); letter-spacing:-.02em; margin:44px 0 6px;}
.ec-lead {font-size:1.15rem; color:#3b413e; max-width:760px; line-height:1.55;}
.ec-note {color:var(--muted); font-size:.85rem;}
.ec-tag {display:inline-block; font-family:var(--mono); font-size:.72rem; letter-spacing:.08em; text-transform:uppercase;
         padding:3px 9px; border-radius:3px; background:#ecefed; color:#26332e; margin-right:6px;}
.ec-tag.fut {background:#d9f2e6; color:#0b4d36;} .ec-tag.bt {background:#e8eefc; color:#1b3a8a;}
.ec-tag.ex {background:#fff3cd; color:#5c4300; border:1px dashed #d9a400;}
.ec-demo {background:#fff4d6; color:#5c4300; border:1px dashed #d9a400; padding:10px 14px; border-radius:6px; font-weight:600; margin:14px 0;}
.ec-row {display:grid; grid-template-columns:120px 1fr 240px; gap:18px; align-items:center; padding:16px 0; border-bottom:1px solid var(--line);}
.ec-row .when {font-family:var(--mono); font-size:.8rem; color:var(--muted);}
.ec-row .teams {font-family:var(--display); font-size:1.25rem; font-weight:650;}
.ec-row .teams i {font-style:normal; color:var(--muted); font-weight:400; padding:0 8px;}
.ec-bar {display:flex; height:10px; border-radius:2px; overflow:hidden; background:#e9eeec; margin-bottom:6px;}
.ec-bar .h {background:var(--accent);} .ec-bar .d {background:#b8c4bf;} .ec-bar .a {background:var(--red);}
.ec-p {font-family:var(--mono); font-size:.82rem; color:#26332e; font-variant-numeric:tabular-nums;}
.ec-big {display:grid; grid-template-columns:repeat(auto-fit, minmax(180px, 1fr)); gap:18px; margin:26px 0;}
.ec-big div {border-top:2px solid var(--ink); padding-top:10px;}
.ec-big b {display:block; font-family:var(--mono); font-size:clamp(2.2rem, 5vw, 3.6rem); font-weight:700; letter-spacing:-.03em;
           font-variant-numeric:tabular-nums; line-height:1.05;}
.ec-big span {font-family:var(--mono); font-size:.75rem; letter-spacing:.12em; text-transform:uppercase; color:var(--muted);}
.ec-card {border:1px solid var(--line); background:#fff; border-radius:6px; padding:26px 26px 20px; margin:14px 0; overflow:hidden;}
.ec-card .league-img {display:block; width:calc(100% + 52px); max-width:none; height:170px; object-fit:cover !important; margin:-26px -26px 20px;}
.ec-group-img {display:block; width:100%; height:150px; object-fit:cover !important; border-radius:6px; margin:44px 0 -26px;}
a.ec-link, .ec-h1 a, .ec-row a {color:inherit; text-decoration:none;}
a.ec-link:hover, .ec-h1 a:hover, .ec-row a:hover {text-decoration:underline; text-decoration-color:var(--accent);}
a.ec-comp {display:flex; align-items:center; gap:16px; margin:36px 0 6px; padding:10px 12px; border-radius:6px; background:#fff;
           border:1px solid var(--line); color:inherit; text-decoration:none;}
a.ec-comp:hover {border-color:var(--accent);}
a.ec-comp img {width:96px; height:56px; object-fit:cover !important; border-radius:4px;}
a.ec-comp .noimg {width:96px; height:56px; border-radius:4px; background:#ecefed; display:flex; align-items:center; justify-content:center;
                  font-family:var(--mono); font-size:.8rem; letter-spacing:.1em; color:var(--muted);}
a.ec-comp b {display:block; font-family:var(--display); font-size:1.35rem;}
a.ec-comp small {font-family:var(--mono); font-size:.72rem; letter-spacing:.1em; text-transform:uppercase; color:var(--muted);}
a.ec-comp .go {margin-left:auto; font-family:var(--mono); color:var(--muted);}
.ec-row .go {font-family:var(--mono); font-size:.8rem; color:var(--accent); white-space:nowrap;}
.ec-row.with-go {grid-template-columns:120px 1fr 240px 70px;}
.ec-score {font-family:var(--mono); font-weight:700; padding:0 6px;}
.ec-grid {display:grid; grid-template-columns:repeat(auto-fill, minmax(230px, 1fr)); gap:14px; margin:14px 0;}
.ec-grid .ec-card {margin:0;} .ec-grid .ec-card h3 {font-size:1.3rem;}
.ec-grid .full {grid-column:1 / -1;}
table.ec-table {width:100%; border-collapse:collapse; font-variant-numeric:tabular-nums; font-size:.92rem;}
table.ec-table th {font-family:var(--mono); font-size:.72rem; letter-spacing:.08em; text-transform:uppercase; color:var(--muted);
                   text-align:right; padding:8px 6px; border-bottom:2px solid var(--ink);}
table.ec-table td {text-align:right; padding:8px 6px; border-bottom:1px solid var(--line); font-family:var(--mono);}
table.ec-table th:nth-child(2), table.ec-table td:nth-child(2) {text-align:left; font-family:var(--display);}
table.ec-table tr.hl td {background:#eef7f2; font-weight:700;}
table.ec-table a {color:inherit; text-decoration:none;} table.ec-table a:hover {text-decoration:underline;}
.ec-wdl {display:inline-block; width:22px; height:22px; line-height:22px; text-align:center; border-radius:3px; font-family:var(--mono);
         font-size:.75rem; font-weight:700; color:#fff; margin-right:8px;}
.ec-wdl.V {background:var(--accent);} .ec-wdl.N {background:#9aa59f;} .ec-wdl.D {background:var(--red);}
.ec-form {padding:8px 0; border-bottom:1px solid var(--line); font-size:.92rem;}
.ec-form .d {font-family:var(--mono); font-size:.78rem; color:var(--muted); margin-right:8px;}
.ec-chips {display:flex; flex-wrap:wrap; gap:8px; margin:10px 0;}
.ec-chips a {border:1px solid var(--line); background:#fff; border-radius:999px; padding:6px 14px; color:inherit; text-decoration:none; font-size:.9rem;}
.ec-chips a:hover {border-color:var(--accent);}
.ec-card h3 {font-family:var(--display); font-size:2rem; font-weight:750; letter-spacing:-.02em; margin:0 0 4px;}
.ec-ad {display:flex; align-items:center; justify-content:center; max-width:100%; margin:28px auto; border:2px dashed #b9bdbb;
        background:#f1f2f0; color:#8a8f8c; font-family:var(--mono); font-size:.78rem; letter-spacing:.14em; text-transform:uppercase;}
div[data-testid="stColumn"]:has(.ec-sticky) .ec-ad {margin-top:0;}
.ec-news-h {font-family:var(--display); font-weight:750; font-size:1.35rem; letter-spacing:-.01em; margin:8px 0 6px;}
.ec-news-list {list-style:none; margin:4px 0 0; padding:0;}
.ec-news-list li {border-bottom:1px solid var(--line);}
.ec-news-list a {display:block; padding:10px 2px; color:inherit; text-decoration:none;}
.ec-news-list a:hover .t, .ec-news-list a:focus-visible .t {text-decoration:underline;}
.ec-news-list .t {display:block; font-weight:600; font-size:.92rem; line-height:1.35;}
.ec-news-list .m {display:block; font-family:var(--mono); font-size:.7rem; color:var(--muted); margin-top:4px;}
.ec-hero {position:relative; background:#0d0f0e; color:#fff; border-radius:8px; padding:72px 56px 64px; margin:24px 0 18px;}
.ec-hero .h {font-family:var(--display); font-weight:750; font-size:clamp(2.3rem, 5.6vw, 4.4rem); line-height:1.03;
             letter-spacing:-.03em; max-width:860px; margin:0 0 18px; color:#fff;}
.ec-hero p {color:#b8bfbb; font-size:1.15rem; line-height:1.6; max-width:640px; margin:0 0 30px;}
.ec-hero-btn {display:inline-block; background:#00C853; color:#03200e !important; font-family:var(--mono); font-weight:700;
              letter-spacing:.06em; text-transform:uppercase; font-size:.85rem; padding:14px 26px; border-radius:4px; text-decoration:none !important;}
.ec-hero-btn:hover, .ec-hero-btn:focus-visible {background:#1ee36f; outline:2px solid #fff; outline-offset:3px;}
.ec-hero-logo {position:absolute; top:22px; right:26px; width:150px; filter:invert(1) hue-rotate(180deg); mix-blend-mode:screen; opacity:.9;}
.ec-strip {overflow:hidden; margin:0 0 8px; padding:6px 0;
           -webkit-mask-image:linear-gradient(90deg, transparent, #000 4%, #000 96%, transparent);
           mask-image:linear-gradient(90deg, transparent, #000 4%, #000 96%, transparent);}
.ec-strip-track {display:flex; width:max-content; animation:ec-marquee 38s linear infinite;}
.ec-strip:hover .ec-strip-track, .ec-strip:focus-within .ec-strip-track {animation-play-state:paused;}
.ec-strip-set {display:flex; gap:10px; padding-right:10px;}
@keyframes ec-marquee {from {transform:translateX(0);} to {transform:translateX(-50%);}}
.ec-pill {display:inline-flex; align-items:center; gap:8px; white-space:nowrap; border:1px solid #cfd3d0; background:#fff; color:var(--ink);
          border-radius:999px; padding:8px 16px; font-family:var(--mono); font-size:.8rem; letter-spacing:.06em; text-transform:uppercase;
          text-decoration:none !important;}
a.ec-pill:hover, a.ec-pill:focus-visible {border-color:#00C853; outline:none;}
.ec-pill.on {border-color:#00C853; background:#e6f9ee; box-shadow:inset 0 0 0 1px #00C853; font-weight:700;}
.ec-pill.soon {color:#9aa09d; background:#f1f2f0; border-style:dashed; cursor:not-allowed;}
.ec-pill.soon small {font-size:.62rem; letter-spacing:.1em; color:#7d8480; border:1px solid #c9ceca; border-radius:3px; padding:1px 5px;}
.ec-nav-logo {display:block; width:200px; max-width:100%; mix-blend-mode:multiply;}
.ec-tagline {margin:0; text-align:center; font-family:var(--display); font-weight:650; font-size:1.08rem; letter-spacing:-.01em; color:var(--ink);}
[class*="st-key-ec_bento"] {display:grid !important; grid-template-columns:repeat(3, minmax(0, 1fr)); grid-auto-flow:dense; gap:14px;}
[class*="st-key-ec_tile_"], [class*="st-key-ec_soon_"] {position:relative; gap:0 !important; border-radius:12px; overflow:hidden; background:#fff;}
[class*="st-key-ec_tile_"] {transition:transform .16s ease, box-shadow .16s ease; box-shadow:0 0 0 1px var(--line);}
[class*="st-key-ec_tile_"]:hover, [class*="st-key-ec_tile_"]:focus-within {transform:translateY(-2px); box-shadow:0 0 0 2px #00C853, 0 10px 24px rgba(13,15,14,.10);}
[class*="st-key-ec_tile_"] .league-img, [class*="st-key-ec_soon_"] .league-img {display:block; width:100%; height:120px; object-fit:cover !important; margin:0;}
[class*="st-key-ec_soon_"] {opacity:.55; filter:grayscale(1); cursor:not-allowed;}
[class*="st-key-ec_soon_"] * {pointer-events:none;}
a.ec-tile-link {position:absolute; inset:0; z-index:3; border-radius:12px;}
a.ec-tile-link:focus-visible {outline:3px solid #00C853; outline-offset:-3px;}
[class*="st-key-ec_tile_"] [data-testid="stElementContainer"]:has(a.ec-tile-link) {position:static; height:0; margin:0;}
@media (max-width: 900px) {[class*="st-key-ec_bento"], .st-key-ec_bento_live {grid-template-columns:repeat(2, minmax(0, 1fr));}}
@media (max-width: 560px) {[class*="st-key-ec_bento"], .st-key-ec_bento_live {grid-template-columns:1fr;}}
@media (prefers-reduced-motion: reduce) {[class*="st-key-ec_tile_"] {transition:none;}}
.ec-nav {position:relative; z-index:60;}
.ec-sportbar {display:flex; flex-wrap:wrap; align-items:stretch; gap:2px; background:#0d0f0e; border-radius:6px; padding:0 6px; margin:4px 0 2px;}
.ec-sportbar .ec-top {white-space:nowrap; padding:13px 14px 10px; border:0; border-bottom:3px solid transparent; background:none; cursor:pointer;
                      color:#e6e9e6; text-decoration:none; font-family:var(--mono); font-size:.8rem; letter-spacing:.08em; text-transform:uppercase;}
.ec-sportbar .ec-top:hover {color:#fff; border-bottom-color:#59605c;}
.ec-sportbar .ec-top:focus-visible, .ec-dd a:focus-visible, .ec-dd-sp:focus-visible {outline:2px solid #00C853; outline-offset:-2px;}
.ec-sportbar .ec-top.on, .ec-sportbar .ec-top.open, .ec-sportbar .ec-top[aria-expanded="true"] {color:#00C853; border-bottom-color:#00C853; font-weight:700;}
.ec-sportbar .ec-right {margin-left:auto;}
.ec-dd {position:absolute; top:calc(100% + 6px); left:0; z-index:70; background:#fff; color:var(--ink); border:1px solid var(--line); border-radius:8px;
        box-shadow:0 18px 40px rgba(13,15,14,.18); padding:10px; opacity:0; visibility:hidden; transform:translateY(-6px);
        transition:opacity .16s ease, transform .16s ease, visibility 0s linear .16s;}
.ec-nav[data-open="sports"] #ec-dd-sports, .ec-nav[data-open="preuve"] #ec-dd-preuve {opacity:1; visibility:visible; transform:none;
        transition:opacity .16s ease, transform .16s ease;}
.ec-dd ul {list-style:none; margin:0; padding:0;}
#ec-dd-sports {width:560px; min-height:300px;}
.ec-dd-sports {width:230px;}
.ec-dd-sp {display:flex; align-items:center; gap:10px; width:100%; padding:10px 12px; border:0; border-radius:6px; background:none; color:inherit;
           font-family:var(--display); font-size:.98rem; font-weight:600; text-align:left; cursor:pointer;}
.ec-dd-sp .arr {margin-left:auto; color:var(--muted); font-size:1.2rem; transition:transform .16s ease;}
.ec-dd-sp:hover, .ec-dd-sp[aria-expanded="true"] {background:#e6f9ee; box-shadow:inset 3px 0 0 #00C853;}
.ec-dd-sp[aria-expanded="true"] .arr {color:#0B6E4F;}
.ec-dd-lg {display:none; position:absolute; top:10px; left:252px; right:10px; padding-left:14px; border-left:1px solid var(--line);}
.ec-dd-sp[aria-expanded="true"] + .ec-dd-lg {display:block;}
.ec-dd a, .ec-dd .soon {display:flex; align-items:center; justify-content:space-between; gap:8px; padding:8px 10px; border-radius:6px;
                        color:inherit; text-decoration:none; font-size:.93rem;}
.ec-dd a:hover {background:#e6f9ee; color:#0B6E4F;}
.ec-dd .soon {color:#9aa09d; cursor:not-allowed;}
.ec-dd .soon small {font-family:var(--mono); font-size:.62rem; letter-spacing:.1em; text-transform:uppercase; color:#7d8480;
                    border:1px solid #c9ceca; border-radius:3px; padding:1px 5px;}
.ec-mega {left:auto; right:0; width:min(720px, 100%); display:grid; grid-template-columns:repeat(3, 1fr); gap:16px; padding:18px;}
.ec-dd-h {font-family:var(--mono); font-size:.72rem; letter-spacing:.14em; text-transform:uppercase; color:var(--muted); padding:0 10px 6px;
          border-bottom:1px solid var(--line); margin-bottom:6px;}
@media (max-width: 700px) {
  .ec-dd, #ec-dd-sports, .ec-mega {left:0; right:0; width:auto; min-height:0;}
  .ec-mega {grid-template-columns:1fr;} .ec-dd-sports {width:auto;}
  .ec-dd-lg {position:static; border:0; padding:0 0 6px 34px;}
  .ec-sportbar .ec-right {margin-left:0;}
}
@media (prefers-reduced-motion: reduce) {.ec-dd, .ec-nav[data-open] .ec-dd {transition:none;}}
.ec-sport-leagues {display:flex; flex-wrap:wrap; gap:8px; margin:6px 0 14px;}
a.ec-faq-link {font-family:var(--mono); font-size:.8rem; text-transform:uppercase; letter-spacing:.06em; padding:2px 6px; color:inherit; text-decoration:none;}
a.ec-faq-link:hover {text-decoration:underline; text-decoration-color:var(--accent);}
.ec-home {padding:56px 48px;}
.ec-home-grid {display:grid; grid-template-columns:1.15fr 1fr; gap:48px; align-items:start;}
.ec-home .h .g {color:#00C853;}
.ec-badges {display:flex; gap:12px; flex-wrap:wrap;}
.ec-badge {display:inline-flex; align-items:center; gap:10px; border:1px solid #3a403d; border-radius:8px; padding:10px 16px;
           color:#7d8480; font-weight:600; cursor:not-allowed;}
.ec-badge small {font-family:var(--mono); font-size:.62rem; letter-spacing:.1em; text-transform:uppercase; border:1px solid #3a403d;
                 border-radius:3px; padding:1px 5px;}
.ec-home .free {font-family:var(--mono); font-size:.78rem; letter-spacing:.06em; color:#8d948f; margin-top:14px;}
.ec-feat {background:#151917; border:1px solid #2a302d; border-radius:8px; padding:22px;}
.ec-feat .k, .ec-mini .k {font-family:var(--mono); font-size:.7rem; letter-spacing:.1em; text-transform:uppercase; color:#8d948f;}
.ec-feat .t {font-family:var(--display); font-size:1.7rem; font-weight:700; margin:6px 0 10px;}
.ec-feat .t i {font-style:normal; color:#6b716e;}
.ec-feat .pred {color:#d6dbd8;} .ec-feat .pred b {color:#fff;} .ec-feat .pred span {font-family:var(--mono); color:#00C853; font-weight:700;}
.ec-feat .agree {margin:16px 0 8px;} .ec-feat .agree .lab {font-size:.85rem; color:#b8bfbb;} .ec-feat .agree b {color:#fff;}
.ec-feat .bar {height:8px; background:#2a302d; border-radius:4px; overflow:hidden; margin-top:6px;}
.ec-feat .bar span {display:block; height:100%; background:#00C853;}
.ec-feat .votes {list-style:none; padding:0; margin:10px 0; font-size:.88rem;}
.ec-feat .votes li {display:flex; justify-content:space-between; padding:5px 0; border-bottom:1px solid #232825; color:#b8bfbb;}
.ec-feat .votes b {font-family:var(--mono); color:#8d948f;} .ec-feat .votes b.ok {color:#00C853;}
.ec-feat .note {font-size:.78rem; color:#8d948f; margin:8px 0 16px;}
.ec-minis {display:grid; grid-template-columns:1fr 1fr; gap:10px; margin-top:10px;}
a.ec-mini {display:flex; flex-direction:column; gap:4px; background:#151917; border:1px solid #2a302d; border-radius:8px; padding:12px 14px;
           color:#fff !important; text-decoration:none !important;}
a.ec-mini:hover, a.ec-mini:focus-visible {border-color:#00C853;}
.ec-mini .t {font-weight:700;} .ec-mini .p {font-family:var(--mono); font-size:.82rem; color:#00C853;}
.ec-models-head {display:flex; justify-content:space-between; align-items:baseline; gap:12px; flex-wrap:wrap; margin:26px 0 6px;}
.ec-models-head b {font-family:var(--display); font-size:1.3rem;}
.ec-def {margin:0; font-size:1rem; line-height:1.6; color:var(--ink);}
.ec-lex-intro {font-size:1.05rem; line-height:1.65; max-width:760px;}
.ec-lex-intro a.ec-link {text-decoration:underline; text-decoration-color:#00C853; text-underline-offset:3px; font-weight:600;}
[data-testid="stExpander"] summary:hover, [data-testid="stExpander"] summary:focus-visible {color:#0B6E4F;}
[data-testid="stExpander"] details[open] {box-shadow:inset 3px 0 0 #00C853;}
.ec-faq {margin:20px 0 40px; scroll-margin-top:20px;}
.ec-faq details {border-bottom:1px solid var(--line); padding:14px 0;}
.ec-faq summary {font-weight:650; font-size:1.05rem; cursor:pointer;}
.ec-faq details p {color:#3b413e; margin:10px 0 0;}
@media (max-width: 900px) {
  .ec-home {padding:56px 20px 32px;} .ec-home-grid {grid-template-columns:1fr; gap:28px;} .ec-tagline {text-align:left;}
}
@media (prefers-reduced-motion: reduce) {
  .ec-strip {overflow-x:auto; -webkit-mask-image:none; mask-image:none;}
  .ec-strip-track {animation:none;} .ec-strip-set[aria-hidden="true"] {display:none;}
}
@media (max-width: 900px) {
  .ec-hero {padding:64px 22px 40px;} .ec-hero-logo {width:110px; top:18px; right:18px;}
  div[data-testid="stElementContainer"]:has(.ec-sticky) {display:none;}
  .ec-row, .ec-row.with-go {grid-template-columns:1fr; gap:6px;}
}
</style>
"""
st.markdown(CSS, unsafe_allow_html=True)


# ---------------------------------------------------------------- chargement
def _mt(p: Path) -> float:
    return p.stat().st_mtime if p.exists() else 0.0


@st.cache_data(show_spinner=False)
def _parquet(path: str, mtime: float):
    return pd.read_parquet(path)


@st.cache_data(show_spinner=False)
def _json(path: str, mtime: float):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def preds(origin, sport):
    p = config.origin_dir(origin) / f"predictions_{sport}.parquet"
    return _parquet(str(p), _mt(p)) if p.exists() else None


def sim(origin, sport):
    p = config.origin_dir(origin) / f"simulation_{sport}.parquet"
    return _parquet(str(p), _mt(p)) if p.exists() else None


def report(origin, sport):
    p = config.origin_dir(origin) / f"report_{sport}.json"
    return _json(str(p), _mt(p)) if p.exists() else None


def upcoming(o: str, sp: str):
    """Dernière version « à venir » (modèle actualisé), séparée du backtest. Repli : lignes à venir du backtest."""
    d = config.origin_dir(o)
    files = sorted(d.glob(f"predictions_{sp}_upcoming_*.parquet"), key=lambda f: (f.name, f.stat().st_mtime))
    if files:
        rp = d / files[-1].name.replace("predictions_", "report_").replace(".parquet", ".json")
        return _parquet(str(files[-1]), _mt(files[-1])), (_json(str(rp), _mt(rp)) if rp.exists() else None)
    P = preds(o, sp)
    return (P[P["status"] != "final"].reset_index(drop=True) if P is not None else None), None


def up_label(UR) -> str:
    return f"version {UR['version']} · données jusqu'au {UR['date_limite_donnees']}" if UR else "modèle du backtest (non actualisé)"


def fr_date(d) -> str:
    d = pd.Timestamp(d)
    return f"{DAYS[d.weekday()]} {d.day} {MONTHS[d.month - 1]} {d.year}"


def pct(x) -> str:
    return "—" if pd.isna(x) else f"{100 * x:.1f} %"


def fr_num(x: float, fmt: str = ".3f") -> str:
    return format(x, fmt).replace(".", ",")


def html(s: str):
    st.markdown(s, unsafe_allow_html=True)


def hero(kicker: str, title: str, lead: str = ""):
    html(f'<div class="ec-kicker">{kicker}</div><div class="ec-h1">{title}</div>' + (f'<p class="ec-lead">{lead}</p>' if lead else ""))


def ad(w: int, h: int, cls: str = ""):
    html(f'<div class="ec-ad {cls}" style="width:{w}px;height:{h}px">Publicité</div>')


@lru_cache(maxsize=None)
def asset_uri(fn: str) -> str:
    """Fichier de assets/ en data URI (st.markdown ne sert pas les fichiers locaux)."""
    mime = {"webp": "webp", "png": "png"}.get(fn.rsplit(".", 1)[-1], "jpeg")
    return f"data:image/{mime};base64," + base64.b64encode((ASSETS / fn).read_bytes()).decode()


@lru_cache(maxsize=None)
def league_img(sp: str, cls: str) -> str:
    """Balise <img> inline pour une ligue qui a une photo dans la maquette ; chaîne vide sinon (ex. NFL)."""
    if sp not in LEAGUE_IMG:
        return ""
    fn, alt = LEAGUE_IMG[sp]
    return f'<img class="{cls}" src="{asset_uri(fn)}" alt="{alt}">'


# ---------------------------------------------------------------- héros + bandeau de ligues (Aujourd'hui)
STRIP_SOON = ["La Liga", "Serie A", "Bundesliga", "Ligue 1", "Championship", "WNBA", "NHL", "MLB"]  # maquette, sans données moteur


def hero_block() -> str:
    """Bloc sombre d'accueil : promesse « prédiction + preuve », sans aucun langage de pari."""
    return (f'<section class="ec-hero"><img class="ec-hero-logo" src="{asset_uri("logo-primary.png")}" alt="EDGECOURT">'
            '<div class="h" role="heading" aria-level="1">Des prédictions. Des preuves. Rien d\'autre.</div>'
            "<p>Chaque pronostic est publié avec son résultat. Aucun pari, aucune promesse — juste le modèle, et son bilan en public.</p>"
            f'<a class="ec-hero-btn" href="{escape(url("preuve"))}" target="_self">Voir La preuve</a></section>')


def league_strip(active: str) -> str:
    """Bandeau défilant : les 3 ligues du moteur (cliquables, filtrent Aujourd'hui), puis les ligues « Bientôt » (grisées, inertes).
    Le contenu est doublé pour une boucle continue ; la copie est cachée des lecteurs d'écran et du clavier."""
    def pills(copy: bool) -> str:
        hide = ' tabindex="-1"' if copy else ""
        cur = ' aria-current="true"'
        live = "".join(f'<a class="ec-pill{" on" if sp == active else ""}" href="{escape(url("", sport=sp))}" target="_self"{hide}'
                       f'{cur if sp == active and not copy else ""}>{COMP[sp][0]}</a>' for sp in ("nba", "soccer", "nfl"))
        soon = "".join(f'<span class="ec-pill soon" aria-disabled="true">{n}<small>Bientôt</small></span>' for n in STRIP_SOON)
        return f'<div class="ec-strip-set"{" aria-hidden=" + chr(34) + "true" + chr(34) if copy else ""}>{live}{soon}</div>'
    return f'<nav class="ec-strip" aria-label="Ligues"><div class="ec-strip-track">{pills(False)}{pills(True)}</div></nav>'


def nav_sport() -> str:
    """Sport ouvert dans la barre : hockey/baseball (sans données) ou, sinon, le sport moteur courant."""
    return st.session_state.get("nav_sport") or st.session_state.get("sport", "nfl")


SPORT_ICON = {"soccer": "⚽", "nba": "🏀", "nfl": "🏈", "nhl": "🏒", "mlb": "⚾"}
# Méga-menu « La preuve » : None = pas (encore) de page dans l'app → « Bientôt », non cliquable (aucune page inventée).
MEGA = [("La preuve", [("La preuve", "preuve"), ("Journal", None), ("Classement des modèles", "preuve"), ("Équipe de la semaine", None)]),
        ("Comprendre", [("Lexique", "lexique"), ("Comment ça marche", "lexique"), ("FAQ", "accueil#faq")]),
        ("Le site", [("Accueil", "accueil"), ("Aujourd'hui", "aujourdhui"), ("Ligues", "ligues"), ("En direct", "direct"),
                     ("La toile", "toile")])]
NAV_JS = """<script>(() => {
if (window.__ecNav) return; window.__ecNav = 1;  // écouteurs posés une fois sur le document : survivent aux réaffichages
const d = document, fine = matchMedia('(hover:hover) and (pointer:fine)'), nav = () => d.getElementById('ec-nav'); let t;
function sub(sp) { nav().querySelectorAll('.ec-dd-sp').forEach(b => b.setAttribute('aria-expanded', b.dataset.sp === sp)); }
function open(id, sp) {
  const n = nav(); if (!n) return; clearTimeout(t); n.dataset.open = id;
  n.querySelectorAll('button[data-dd]').forEach(b => b.setAttribute('aria-expanded', b.dataset.dd === id));
  n.querySelectorAll('a[data-dd]').forEach(a => a.classList.toggle('open', id === 'sports' && a.dataset.sp === sp));
  if (id === 'sports') sub(sp || n.dataset.sp);
}
function close(back) {
  const n = nav(); if (!n || !n.dataset.open) return;
  const b = n.querySelector('button[data-dd="' + n.dataset.open + '"]'); open(''); if (back && b) b.focus();
}
d.addEventListener('click', e => {
  const n = nav(); if (!n) return;
  const b = e.target.closest('#ec-nav button[data-dd]'); if (b) { n.dataset.open === b.dataset.dd ? close() : open(b.dataset.dd); return; }
  const s = e.target.closest('#ec-nav .ec-dd-sp'); if (s) { sub(s.getAttribute('aria-expanded') === 'true' ? '' : s.dataset.sp); return; }
  if (!e.target.closest('#ec-nav .ec-dd') || e.target.closest('a')) close();  // clic ailleurs ou choix d'un élément
});
d.addEventListener('keydown', e => { if (e.key === 'Escape') close(true); });
d.addEventListener('focusout', e => { const n = nav(); if (n && n.contains(e.target) && e.relatedTarget && !n.contains(e.relatedTarget)) close(); });
d.addEventListener('mouseover', e => {
  if (!fine.matches) return;
  const h = e.target.closest('#ec-nav [data-dd]'); if (h) { open(h.dataset.dd, h.dataset.sp); return; }
  if (e.target.closest('#ec-nav .ec-dd')) clearTimeout(t); else if (e.target.closest('#ec-nav .ec-sportbar')) close();
});
d.addEventListener('mouseout', e => { const n = nav(); if (fine.matches && n && n.contains(e.target) && !n.contains(e.relatedTarget)) t = setTimeout(close, 250); });
})();</script>"""


def soon_item(label: str) -> str:
    return f'<span class="soon" aria-disabled="true">{label}<small>Bientôt</small></span>'


def sport_bar(active: str | None) -> str:
    """Barre noire + cartes dépliantes « Sports » (sport → ligues) et « La preuve » (3 colonnes).
    Ligue ou page sans données = « Bientôt », jamais un lien. Survol (souris), tap, clavier ; Échap / clic ailleurs ferment."""
    live = {COMP[s][0]: s for s in config.SPORTS}
    sports = "".join(
        f'<li><button type="button" class="ec-dd-sp" data-sp="{k}" aria-expanded="false" aria-controls="ec-lg-{k}">'
        f'<span class="ic" aria-hidden="true">{SPORT_ICON[k]}</span>{n}<span class="arr" aria-hidden="true">›</span></button>'
        f'<ul class="ec-dd-lg" id="ec-lg-{k}" aria-label="Ligues — {n}">'
        + "".join(f'<li><a href="{escape(url("aujourdhui", sport=live[lg]))}" target="_self">{lg}</a></li>' if lg in live
                  else f"<li>{soon_item(lg)}</li>" for lg in SPORT_LEAGUES[k]) + "</ul></li>"
        for k, n in NAV_SPORTS.items())
    mega = "".join(
        f'<div><div class="ec-dd-h">{col}</div><ul>'
        + "".join(f'<li><a href="{escape(url(p.partition("#")[0]) + "".join(p.partition("#")[1:]))}" target="_self">{lab}</a></li>'
                  if p else f"<li>{soon_item(lab)}</li>" for lab, p in items) + "</ul></div>" for col, items in MEGA)
    cur = ' aria-current="page"'
    tops = "".join(f'<a class="ec-top{" on" if k == active else ""}" data-dd="sports" data-sp="{k}" '
                   f'href="{escape(url("aujourdhui", sport=k))}" target="_self"{cur if k == active else ""}>{n}</a>'
                   for k, n in NAV_SPORTS.items())
    sp = active if active in NAV_SPORTS else nav_sport()
    return (f'<div class="ec-nav" id="ec-nav" data-sp="{sp}" data-open=""><nav class="ec-sportbar" aria-label="Navigation principale">'
            f'<a class="ec-top{" on" if active == "accueil" else ""}" href="{escape(url("accueil"))}" target="_self"'
            f'{cur if active == "accueil" else ""}>Accueil</a>'
            '<button type="button" class="ec-top" data-dd="sports" aria-expanded="false" aria-controls="ec-dd-sports">Sports <span aria-hidden="true">▾</span></button>'
            f'<div class="ec-dd" id="ec-dd-sports" role="region" aria-label="Sports et ligues"><ul class="ec-dd-sports">{sports}</ul></div>'
            f"{tops}"
            '<button type="button" class="ec-top ec-right" data-dd="preuve" aria-expanded="false" aria-controls="ec-dd-preuve">La preuve <span aria-hidden="true">▾</span></button>'
            f'<div class="ec-dd ec-mega" id="ec-dd-preuve" role="region" aria-label="La preuve, comprendre, le site">{mega}</div>'
            f"</nav></div>{NAV_JS}")


def sport_leagues(ns: str) -> str:
    """Ligues du sport ouvert : celles du moteur en actif, les autres « Bientôt » (grisées, inertes)."""
    live = {COMP[s][0] for s in config.SPORTS}
    return f'<div class="ec-sport-leagues" role="group" aria-label="Ligues — {NAV_SPORTS[ns]}">' + "".join(
        f'<span class="ec-pill on">{n}</span>' if n in live
        else f'<span class="ec-pill soon" aria-disabled="true">{n}<small>Bientôt</small></span>' for n in SPORT_LEAGUES[ns]) + "</div>"


def big_html(items) -> str:
    return '<div class="ec-big">' + "".join(f"<div><b>{v}</b><span>{k}</span></div>" for k, v in items) + "</div>"


# Compteur (idée « Number Ticker ») : le texte final affiché par la carte shadcn reste le vrai chiffre du moteur ;
# le script ne fait que compter de 0 jusqu'à ce texte (900 ms), une seule fois par carte, rien si reduced-motion.
TICKER_JS = """<script>(() => {
const num = /[−+-]?\\d[\\d\\s\\u202f]*(?:,\\d+)?/g;
function tick(el) {
  const end = el.textContent; if (el.dataset.ecTicked || !num.test(end)) return; el.dataset.ecTicked = 1;
  const parts = end.match(num); let t0;
  const val = s => parseFloat(s.replace(/[\\s\\u202f]/g, '').replace('−', '-').replace(',', '.'));
  const fmt = (s, x) => { const d = (s.split(',')[1] || '').length, sign = /^[−+-]/.test(s) ? s[0] : '';  // signe d'origine
    let r = Math.abs(x).toFixed(d).replace('.', ','); if (/\\s|\\u202f/.test(s)) r = r.replace(/\\B(?=(\\d{3})+(?!\\d))/g, '\\u202f');
    return sign + r; };
  requestAnimationFrame(function step(now) {  // 1re image seulement quand l'onglet est visible : sinon le vrai chiffre reste
    t0 ??= now; const p = Math.min(1, (now - t0) / 900), e = 1 - Math.pow(1 - p, 3); let i = 0;
    el.textContent = p < 1 ? end.replace(num, s => fmt(s, val(parts[i++]) * e)) : end;
    if (p < 1) requestAnimationFrame(step);
  });
}
if (matchMedia('(prefers-reduced-motion: reduce)').matches) return;
let tries = 0; const scan = () => {
  document.querySelectorAll('[class*="st-key-ec_tick_"]').forEach(host => {
    const root = host.querySelector('*') && [...host.querySelectorAll('*')].map(n => n.shadowRoot).find(Boolean);
    const v = root && root.querySelector('[data-slot="card-title"]');
    if (v) tick(v);
  });
  if (++tries < 40) setTimeout(scan, 100);
}; scan();
})();</script>"""


def ticker_metrics(items, prefix: str):
    """Chiffres publics en cartes shadcn, avec compteur de 0 au vrai chiffre."""
    for col, (label, value) in zip(st.columns(len(items)), items):
        with col.container(key=f"ec_tick_{prefix}_{label_key(label)}"):
            ui.metric_card(label, str(value), key=f"m_{prefix}_{label_key(label)}")
    st.html(TICKER_JS, unsafe_allow_javascript=True)


def label_key(s: str) -> str:
    """Clé de widget ASCII (Streamlit remplace les accents par « - » dans les classes CSS)."""
    return re.sub(r"[^a-z0-9]+", "_", unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()).strip("_")


def pick_sport() -> str:
    """Sélecteur de ligue partagé entre écrans (valeur gardée hors widget)."""
    cur = st.session_state.get("sport", "nfl")
    v = st.segmented_control("Ligue", list(config.SPORTS), default=cur, format_func=config.SPORT_LABEL.get, label_visibility="collapsed")
    st.session_state["sport"] = v or cur
    return st.session_state["sport"]


def prob_cell(h, d, a) -> str:
    bar = (f'<div class="ec-bar"><span class="h" style="width:{h*100:.1f}%"></span><span class="d" style="width:{d*100:.1f}%"></span>'
           f'<span class="a" style="width:{a*100:.1f}%"></span></div>')
    txt = f"{pct(h)} · {pct(d)} · {pct(a)}" if d > 0.001 else f"{pct(h)} · {pct(a)}"
    return bar + f'<div class="ec-p">{txt}</div>'


def demo_strip(origin: str):
    if origin == "demo":
        html('<div class="ec-demo">Données d\'exemple — démonstration synthétique : équipes et scores fictifs, cotes « fixtures ». '
             "Sert à tester le parcours ; n'a aucune valeur sportive.</div>")


def headline(r):
    """(log loss modèle, log loss référence, IC) sur le test final, depuis le rapport."""
    ic = r["vainqueur"]["ic"] if r and "vainqueur" in r else None
    base = next((l["logloss"] for l in r["vainqueur"]["lignes"] if l["modele"] == "baseline" and l["periode"] == "test"), None) if ic else None
    return (base + ic["delta_logloss_vs_baseline"], base, ic) if base is not None else (None, None, None)


def wm_label(sport: str) -> str:
    return "1X2 (temps réglementaire)" if sport == "soccer" else "Vainqueur (prolongations incluses)"


# ---------------------------------------------------------------- liens (l'état voyage dans l'URL : pages partageables)
def url(path: str, **params) -> str:
    if st.session_state.get("mode") == "demo":
        params["mode"] = "demo"
    return path + ("?" + urlencode(params) if params else "")


def a(href: str, text: str, cls: str = "ec-link") -> str:
    return f'<a class="{cls}" href="{escape(href)}" target="_self">{text}</a>'


def team_a(sport: str, team: str) -> str:
    return a(url("equipe", sport=sport, team=team), escape(team))


def comp_header(sport: str, n: int | None = None) -> str:
    """En-tête cliquable d'une compétition (image + nom + pays) → page Ligues filtrée."""
    name, country = COMP[sport]
    img = league_img(sport, "") or f'<span class="noimg">{name}</span>'
    count = f" · {n} match{'s' if n > 1 else ''}" if n is not None else ""
    return (f'<a class="ec-comp" href="{escape(url("ligues", ligue=sport))}" target="_self">{img}'
            f'<span><b>{name}</b><small>{country}{count}</small></span><span class="go">Ligue →</span></a>')


# ---------------------------------------------------------------- résultats du moteur (table, forme)
@st.cache_data(show_spinner=False)
def _games(origin: str, sport: str, mtime: float) -> pd.DataFrame:
    s = store.Store(origin)
    try:
        return s.games(sport)
    finally:
        s.close()


def games(origin: str, sport: str) -> pd.DataFrame:
    return _games(origin, sport, _mt(config.db_path(origin)))


def standings(G: pd.DataFrame, sport: str) -> pd.DataFrame:
    """Classement d'une saison depuis les résultats terminés de saison régulière (3/1/0 au football, % de victoires sinon)."""
    G = G[(G["status"] == "final") & G["game_type"].isin(REGULAR)]
    if G.empty:
        return pd.DataFrame()
    t = pd.concat([pd.DataFrame({"Équipe": G[f"{s}_team"], "pour": G[f"{s}_score"], "contre": G[f"{o}_score"]})
                   for s, o in (("home", "away"), ("away", "home"))])
    t["V"], t["N"], t["D"] = t["pour"] > t["contre"], t["pour"] == t["contre"], t["pour"] < t["contre"]
    out = t.groupby("Équipe").agg(J=("pour", "size"), V=("V", "sum"), N=("N", "sum"), D=("D", "sum"),
                                  Pour=("pour", "sum"), Contre=("contre", "sum")).reset_index()
    out["Diff"] = out["Pour"] - out["Contre"]
    if sport == "soccer":
        out["Pts"] = 3 * out["V"] + out["N"]
        out = out.sort_values(["Pts", "Diff", "Pour"], ascending=False)
    else:
        out["% V"] = (out["V"] + 0.5 * out["N"]) / out["J"]
        out = out.sort_values(["% V", "Diff"], ascending=False)
        if not out["N"].any():
            out = out.drop(columns="N")
    out.insert(0, "#", range(1, len(out) + 1))
    return out.reset_index(drop=True)


def table_html(T: pd.DataFrame, sport: str, highlight=()) -> str:
    cols = list(T.columns)
    head = "".join(f"<th>{c}</th>" for c in cols)
    body = ""
    for r in T.itertuples(index=False):
        cells = []
        for c, v in zip(cols, r):
            v = team_a(sport, v) if c == "Équipe" else (f"{v:.3f}".replace(".", ",") if c == "% V" else f"{v:+d}" if c == "Diff" else v)
            cells.append(f"<td>{v}</td>")
        body += f'<tr class="{"hl" if r[1] in highlight else ""}">{"".join(cells)}</tr>'
    return (f'<div style="overflow-x:auto"><table class="ec-table"><thead><tr>{head}</tr></thead>'
            f'<tbody>{body}</tbody></table></div>')


def form_html(G: pd.DataFrame, sport: str, team: str, before, n: int = 5) -> str:
    """Les n derniers résultats terminés de l'équipe avant la date donnée."""
    F = G[(G["status"] == "final") & (G["game_date"] < before) & ((G["home_team"] == team) | (G["away_team"] == team))].tail(n)
    rows = []
    for r in F.iloc[::-1].itertuples():
        home = r.home_team == team
        mine, theirs = (r.home_score, r.away_score) if home else (r.away_score, r.home_score)
        res = "V" if mine > theirs else "N" if mine == theirs else "D"
        opp = r.away_team if home else r.home_team
        rows.append(f'<div class="ec-form"><span class="ec-wdl {res}">{res}</span><span class="d">{fr_date(r.game_date)}</span>'
                    f'{"vs" if home else "@"} {team_a(sport, opp)} <span class="ec-score">{int(r.home_score)}-{int(r.away_score)}</span></div>')
    return "".join(rows)


# ================================================================= écrans
def day_matches(origin: str, sp: str, today):
    """Matchs datés connus du moteur : prévisions à venir (≥ aujourd'hui) + backtests terminés (< aujourd'hui)."""
    U, UR = upcoming(origin, sp)
    P = preds(origin, sp)
    fut = U[U["game_date"] >= today].assign(kind="U") if (U is not None and origin == "real") else None
    past = P[(P["status"] == "final") & (P["game_date"] < today)].assign(kind="P") if P is not None else None
    parts = [x for x in (past, fut) if x is not None and len(x)]
    return (pd.concat(parts).sort_values(["game_date", "game_id"]) if parts else pd.DataFrame(columns=["game_date"])), UR


def match_row(sp: str, r) -> str:
    go = url("match", sport=sp, game=r.game_id)
    score = f'<span class="ec-score">{int(r.home_score)}-{int(r.away_score)}</span>' if r.kind == "P" else "<i>–</i>"
    when = fr_date(r.game_date) + ("<br>backtest" if r.kind == "P" else "")
    return (f'<div class="ec-row with-go"><div class="when">{a(go, when)}</div>'
            f'<div class="teams">{team_a(sp, r.home_team)}{score}{team_a(sp, r.away_team)}</div>'
            f'<div>{a(go, prob_cell(r.p_home_final, r.p_draw_final, r.p_away_final))}</div>'
            f'<div>{a(go, "Détail →", "go")}</div></div>')


def sport_dropdown() -> str:
    # Rappel avant le script : la barre des sports (dessinée avant la page) voit déjà le nouveau sport.
    st.session_state["sport_sel"] = st.session_state.setdefault("sport", "nfl")
    st.selectbox("Sport", ["soccer", "nba", "nfl"], key="sport_sel", format_func=NAV_SPORTS.get, label_visibility="collapsed",
                 on_change=lambda: st.session_state.__setitem__("sport", st.session_state["sport_sel"]))
    return st.session_state["sport"]


def date_strip(days, counts, selected):
    """Bande de dates : En direct (page dédiée) + jours autour d'aujourd'hui ; seuls les jours avec des matchs sont cliquables."""
    with st.container(horizontal=True, gap="small"):
        st.page_link(PAGES["live"], label="● En direct")
        for d in days:
            lab = "Aujourd'hui" if d == days[len(days) // 2] else f"{DAYS[d.weekday()]} {d.day} {MONTHS[d.month - 1]}"
            st.button(lab, key=f"day_{d.date()}", disabled=counts.get(d, 0) == 0, type="primary" if d == selected else "secondary",
                      on_click=lambda d=d: st.session_state.__setitem__("day", d),
                      help=f"{counts.get(d, 0)} match(s)" if counts.get(d, 0) else "Aucun match dans les données")


@st.cache_data(ttl=15 * 60, show_spinner=False)
def news_items() -> list[dict]:
    items = news.load()
    if not items:
        raise RuntimeError(news.UNAVAILABLE)  # une exception n'est pas mise en cache : on réessaie au prochain affichage
    return items


def news_sidebar():
    html('<div class="ec-news-h" role="heading" aria-level="2">News</div>')
    league = st.pills("Filtrer les actualités par ligue", [news.ALL, *news.LEAGUES], default=news.ALL,
                      key="news_league", label_visibility="collapsed")
    try:
        items = news.only(news_items(), league)
    except RuntimeError:
        items = []
    if not items:
        html(f'<p class="ec-note">{news.UNAVAILABLE}</p>')
        return
    components.html(news.featured_html(items[:5]), height=276)
    html(news.list_html(items[5:13]))


def page_today():
    origin = st.session_state["mode"]
    today = pd.Timestamp.today().normalize()
    html(hero_block())
    strip = st.empty()  # rempli quand le sport est connu (la pilule active suit le sélecteur)
    ad(728, 90)
    main, side = st.columns([3, 1], gap="large")
    with side:
        ad(300, 600, "ec-sticky")
        news_sidebar()
    with main:
        hero("Aujourd'hui", f"{LONG_DAYS[today.weekday()].capitalize()} {today.day} {LONG_MONTHS[today.month - 1]}",
             "Les prévisions du moteur, avant le coup d'envoi. Des probabilités, pas des certitudes.")
        ns = nav_sport()
        if ns not in config.SPORTS:  # hockey / baseball : pas de données moteur, donc ni match ni prévision
            strip.markdown(league_strip(""), unsafe_allow_html=True)
            html(f'<div class="ec-h2">{NAV_SPORTS[ns]}</div>' + sport_leagues(ns)
                 + '<p class="ec-note">Aucune donnée moteur pour ce sport pour l\'instant : aucun match ni aucune prévision affichés.</p>')
            return
        sp = sport_dropdown()
        html(sport_leagues(sp))
        strip.markdown(league_strip(sp), unsafe_allow_html=True)
        demo_strip(origin)
        M, UR = day_matches(origin, sp, today)
        days = [today + pd.Timedelta(days=k) for k in range(-3, 4)]
        counts = M["game_date"].value_counts().to_dict() if len(M) else {}
        has = [d for d in days if counts.get(d, 0)]
        sel = st.session_state.get("day")
        if sel not in has:
            sel = today if today in has else next((d for d in has if d >= today), has[-1] if has else None)
        date_strip(days, counts, sel)
        html(comp_header(sp, counts.get(sel, 0) if sel is not None else 0))
        if sel is None:
            last = M["game_date"].max() if len(M) else None
            html(f'<p class="ec-note">Aucun match {COMP[sp][0]} dans les données entre le {fr_date(days[0])} et le {fr_date(days[-1])}. '
                 + (f"Dernier match en base : {fr_date(last)}." if last is not None and pd.notna(last) else "")
                 + " Un historique n'est jamais affiché comme match à venir.</p>")
        else:
            D = M[M["game_date"] == sel]
            if (D["kind"] == "U").any():
                html(f'<span class="ec-tag fut">Prévision à venir</span><span class="ec-note">{up_label(UR)}</span>')
            if (D["kind"] == "P").any():
                html('<span class="ec-tag bt">Backtest</span><span class="ec-note">prévision reconstruite avec les seules données antérieures au match</span>')
            html("".join(match_row(sp, r) for r in D.itertuples()))
            html('<p class="ec-note">Barre : domicile · nul · extérieur. Cliquez un match pour le détail, une équipe pour sa fiche.</p>')
        if sp == "soccer":
            html(f'<p class="ec-note"><b>{SOON}</b> : ' + " · ".join(n for _, n, _ in SOON_LEAGUES)
                 + " · coupes nationales · International. " + a(url("ligues"), "Toutes les ligues →") + "</p>")
        ad(300, 250)


def page_match():
    origin = st.session_state["mode"]
    sport = pick_sport()
    P, R, S = preds(origin, sport), report(origin, sport), sim(origin, sport)
    U, UR = upcoming(origin, sport)
    demo_strip(origin)
    if P is None or R is None:
        hero("Détail d'un match", "Aucune prévision", "Pas de prévisions disponibles pour cette ligue.")
        return
    today = pd.Timestamp.today().normalize()
    nxt = U[U["game_date"] >= today].sort_values(["game_date", "game_id"]) if (U is not None and origin == "real") else P.iloc[0:0]
    opts = {f"{r.game_date.date()} · {r.home_team} – {r.away_team} [À VENIR]": ("U", i, r.game_id) for i, r in nxt.iterrows()}
    lab = P[P["status"] == "final"].sort_values("game_date", ascending=False).head(400)
    opts.update({f"{r.game_date.date()} · {r.home_team} – {r.away_team} [BACKTEST]": ("P", i, r.game_id) for i, r in lab.iterrows()})
    keys = list(opts)
    focus = st.session_state.pop("focus", None)
    hit = next((key for key in keys if focus and str(opts[key][2]) == str(focus)), None)
    if hit or st.session_state.get("match_sel") not in keys:
        st.session_state["match_sel"] = hit or (keys[0] if keys else None)
    if not keys:
        hero("Détail d'un match", "Aucun match", "Pas de matchs pour cette ligue.")
        return
    src, idx, _ = opts[st.selectbox("Match (le prochain match à venir est sélectionné par défaut)", keys, key="match_sel")]
    g = (U if src == "U" else P).loc[idx]
    hero(f"{COMP[sport][0]} · {fr_date(g['game_date'])}", f"{team_a(sport, g['home_team'])} – {team_a(sport, g['away_team'])}")
    if src == "U":
        html(f'<span class="ec-tag fut">Prévision à venir</span><span class="ec-note">{up_label(UR)}</span>')
    else:
        html(f'<span class="ec-tag bt">Backtest</span><span class="ec-note">modèle figé au {R["split"]["train_end"]}, '
             "prévision reconstruite avec les seules données antérieures au match</span>")
    items = [("Domicile", pct(g["p_home_final"]))] + ([("Nul", pct(g["p_draw_final"]))] if g["p_draw_final"] > 0.001 else []) \
        + [("Extérieur", pct(g["p_away_final"]))]
    html(big_html(items))
    st.caption(f"{wm_label(sport)} · modèle : {g['model_selected']}{' (calibré)' if g['calibrated'] else ' (non calibré)'} · "
               f"empreinte des données avant le match : {g['data_fp']}")
    if g["status"] == "final":
        st.success(f"Résultat : {int(g['home_score'])} - {int(g['away_score'])} (prévision rétrospective « backtest »)")
    # Onglets : seuls ceux qui ont du contenu (pas de compositions, chronologie ni stats en direct : aucune source).
    G = games(origin, sport)
    T = standings(G[G["season"].astype(str) == str(g["season"])], sport)
    forms = {t: form_html(G, sport, t, g["game_date"]) for t in (g["home_team"], g["away_team"])}
    names = ["Prévision"] + (["Table"] if len(T) else []) + (["Forme"] if any(forms.values()) else [])
    tabs = dict(zip(names, st.tabs(names)))
    if "Table" in tabs:
        with tabs["Table"]:
            last = G[(G["season"].astype(str) == str(g["season"])) & (G["status"] == "final")]["game_date"].max()
            st.caption(f"Classement {COMP[sport][0]} saison {g['season']}, calculé depuis les résultats de saison régulière du moteur "
                       f"(données jusqu'au {fr_date(last)}). " + ("3 pts victoire, 1 nul." if sport == "soccer" else
                                                                  "Classé au % de victoires (toutes conférences)."))
            html(table_html(T, sport, highlight=(g["home_team"], g["away_team"])))
    if "Forme" in tabs:
        with tabs["Forme"]:
            st.caption("5 derniers résultats terminés de chaque équipe avant ce match (V = victoire, N = nul, D = défaite).")
            for col, (t, h) in zip(st.columns(2), forms.items()):
                col.markdown(f"<b>{team_a(sport, t)}</b>" + (h or '<p class="ec-note">Aucun résultat antérieur en base.</p>'),
                             unsafe_allow_html=True)
    with tabs["Prévision"]:
        prediction_body(g, sport, P, R, S)


def prediction_body(g, sport, P, R, S):
    """Contenu prédictif existant : distributions, variables d'avant-match, comparaison des modèles, recherche cotes (démo)."""
    dp = g["dp_model"] if g["total_dist_selected"] == "model" else g["dp_base"]
    dist = dist_from_params(json.loads(dp))
    html('<div class="ec-h2">Distributions</div>')
    a1, a2 = st.columns(2)
    fig = go.Figure(go.Bar(x=dist.mk, y=dist.mp, marker_color=ACCENT))
    fig.update_layout(title="Écart (domicile − extérieur)", height=300, margin=dict(l=10, r=10, t=40, b=10), plot_bgcolor="#fff")
    a1.plotly_chart(fig, use_container_width=True)
    fig = go.Figure(go.Bar(x=dist.tk, y=dist.tp, marker_color=RED))
    fig.add_vline(x=R["total"]["ligne"], line_dash="dash")
    fig.update_layout(title=f"Total (ligne de référence {R['total']['ligne']})", height=300, margin=dict(l=10, r=10, t=40, b=10), plot_bgcolor="#fff")
    a2.plotly_chart(fig, use_container_width=True)
    html('<div class="ec-h2">Ce que le modèle savait avant le match</div>')
    st.dataframe(pd.DataFrame([{"Elo dom.": round(g["elo_h"]), "Elo ext.": round(g["elo_a"]), "Repos dom. (j)": g["rest_h"],
                                "Repos ext. (j)": g["rest_a"], "Forme dom.": round(g["form_h"], 2), "Forme ext.": round(g["form_a"], 2)}]),
                 hide_index=True)
    cand = [c[2:-2] for c in P.columns if c.startswith("w_") and c.endswith("_h")]
    html('<div class="ec-h2">Comparaison des modèles</div>')
    st.dataframe(pd.DataFrame([{"Modèle": c, "Dom.": pct(g[f"w_{c}_h"]), "Nul": pct(g[f"w_{c}_d"]), "Ext.": pct(g[f"w_{c}_a"])} for c in cand]),
                 hide_index=True)
    st.caption("Probabilités avant calibration.")
    if S is not None and len(S):
        gs = S[S["game_id"] == g["game_id"]]
        with st.expander("Recherche : comparaison aux cotes du marché (démonstration)"):
            if gs.empty:
                st.info("Rendement non évaluable : aucune cote valide jointe à ce match.")
            else:
                st.dataframe(gs[["bookmaker", "market", "selection", "line", "odds", "fair_prob", "p_win", "p_push", "p_loss", "ev", "decision",
                                 "raison_abstention", "outcome"]], hide_index=True)
                st.caption("Cotes « fixtures » de démonstration. L'écart estimé n'est pas une garantie.")


def render_validation(o: str, sport: str):
    r = report(o, sport)
    if r is None or "vainqueur" not in r:
        st.info((r or {}).get("detail", "Pas de rapport pour ce sport.") if r else "Pas de rapport : lancer l'évaluation.")
        return
    demo_strip(o)
    e = r["effectifs"]
    c = st.columns(4)
    c[0].metric("Prévisions test", e["test"]); c[1].metric("Validation", e["calibration"])
    c[2].metric("Découpage", f"{r['split']['train_end']} / {r['split']['calib_end']}")
    c[3].metric("Calibration", "oui" if r["calibration"].startswith("calibré") else "non")
    st.caption(f"Modèle sélectionné sur la validation (jamais sur le test) : **{r['modele_vainqueur_selectionne_sur_validation']}** — {r['calibration']}. "
               f"Total : **{r['modele_total_selectionne_sur_validation']}**. Ajustement : {r['ajustement']}")
    st.markdown(f"**{wm_label(sport)}** — Brier multi-classes et log loss ; comparables seulement dans un même marché.")
    st.dataframe(pd.DataFrame(r["vainqueur"]["lignes"]), use_container_width=True, hide_index=True)
    ic = r["vainqueur"]["ic"]
    if ic:
        st.write(f"Écart de log loss vs référence simple : {ic['delta_logloss_vs_baseline']:+.4f} (IC 95 % par blocs {ic['blocs']} : "
                 f"{ic['ic95_bas']:+.4f} ; {ic['ic95_haut']:+.4f}) → **{ic['statut']}**")
    cur = pd.DataFrame(r["vainqueur"]["courbe_calibration"])
    if len(cur):
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=[0, 1], y=[0, 1], mode="lines", line=dict(dash="dash", color="#999"), name="parfait"))
        ok = cur.dropna()
        fig.add_trace(go.Scatter(x=ok["p_moyenne"], y=ok["frequence_observee"], mode="markers+lines+text",
                                 text=[f"n={n}" for n in ok["n"]], textposition="top center", name="observé", marker_color=ACCENT))
        fig.update_layout(title="Calibration : P(domicile) prévue vs observée (effectifs par classe)", height=340, plot_bgcolor="#fff",
                          xaxis_title="probabilité prévue", yaxis_title="fréquence observée", margin=dict(l=10, r=10, t=40, b=10))
        st.plotly_chart(fig, use_container_width=True)
    st.markdown(f"**Total, ligne de référence {r['total']['ligne']}** (fixée sur l'entraînement)")
    st.dataframe(pd.DataFrame(r["total"]["lignes"]), use_container_width=True, hide_index=True)
    ic = r["total"]["ic"]
    if ic:
        st.write(f"Écart de log loss vs référence : {ic['delta_logloss_vs_baseline']:+.4f} (IC 95 % : {ic['ic95_bas']:+.4f} ; {ic['ic95_haut']:+.4f}) → **{ic['statut']}**")
    m = r["reference_marche"]
    st.markdown("**Référence marché** (mêmes événements, même bookmaker)")
    if "lignes" in m:
        st.dataframe(pd.DataFrame(m["lignes"]), use_container_width=True, hide_index=True)
        st.caption(m["limite"] + (" — cotes FIXTURES" if o == "demo" else ""))
    else:
        st.info(m["statut"])
    st.caption(r["avertissement"])
    cfg = config.origin_dir(o) / "configs_tried.jsonl"
    if cfg.exists():
        with st.expander("Toutes les configurations essayées (validation)"):
            rows = [json.loads(l) for l in cfg.read_text(encoding="utf-8").splitlines()]
            st.dataframe(pd.DataFrame([x for x in rows if x["sport"] == sport]), use_container_width=True, hide_index=True)


def page_proof():
    sport = pick_sport()
    r = report("real", sport)
    model, base, ic = headline(r)
    if model is None:
        hero("La preuve", config.SPORT_LABEL[sport], "Pas encore de rapport réel pour cette ligue.")
    else:
        hero("La preuve · données réelles · test final",
             f"{fr_num(model)} <span style='color:var(--muted);font-weight:400'>contre</span> {fr_num(base)}",
             f"Log loss du modèle contre une référence simple, sur {r['effectifs']['test']} matchs {config.SPORT_LABEL[sport]} "
             f"jamais vus pendant l'entraînement. Plus bas = meilleur. Statut : <b>{ic['statut']}</b>.")
        ticker_metrics([("Matchs de test", r["effectifs"]["test"]), ("Log loss du modèle", fr_num(model)),
                        ("Écart vs référence", fr_num(ic["delta_logloss_vs_baseline"], "+.3f")),
                        ("IC 95 %", f"[{fr_num(ic['ic95_bas'], '+.3f')} ; {fr_num(ic['ic95_haut'], '+.3f')}]")], sport)
        st.caption("Ne compare pas au marché (aucune cote réelle) : aucun avantage économique n'est démontré.")
    html(f'<p class="ec-note">Un mot vous échappe (log loss, IC 95 %, calibration…) ? {a(url("lexique"), "Voir le Lexique →")}</p>')
    html('<div class="ec-h2">Le détail</div>')
    st.markdown("Résultats **réels** et **démonstration synthétique** sont présentés séparément et ne sont jamais mélangés.")
    v1, v2 = st.tabs(["Données réelles", "Démonstration synthétique (fictive)"])
    with v1:
        render_validation("real", sport)
    with v2:
        render_validation("demo", sport)
    ad(468, 60)


def league_view(origin: str, sp: str):
    """Une ligue du moteur : en-tête, classement de la dernière saison en base, équipes (cliquables)."""
    name, country = COMP[sp]
    html(a(url("ligues"), "← Toutes les ligues"))
    hero(f"Ligue · {country}", name)
    html(league_img(sp, "ec-group-img"))
    demo_strip(origin)
    G = games(origin, sp)
    if G.empty:
        st.info("Aucun résultat en base pour cette ligue.")
        return
    F = G[(G["status"] == "final") & G["game_type"].isin(REGULAR)]
    season = F["season"].max() if len(F) else G["season"].max()
    S = G[G["season"] == season]
    T = standings(S, sp)
    teams = sorted(set(S["home_team"]) | set(S["away_team"]))
    html(big_html([("Saison", season), ("Équipes", len(teams)), ("Matchs terminés", int((S["status"] == "final").sum())),
                   ("À venir", int((S["status"] != "final").sum()))]))
    html('<div class="ec-h2">Table</div>')
    if len(T):
        st.caption(f"Calculée depuis les résultats de saison régulière du moteur, données jusqu'au "
                   f"{fr_date(S[S['status'] == 'final']['game_date'].max())}. "
                   + ("3 pts victoire, 1 nul." if sp == "soccer" else "Classée au % de victoires (toutes conférences)."))
        html(table_html(T, sp))
    else:
        html('<p class="ec-note">Aucun résultat de saison régulière terminé pour cette saison.</p>')
    html('<div class="ec-h2">Équipes</div>')
    html('<div class="ec-chips">' + "".join(team_a(sp, t) for t in teams) + "</div>")
    if league_img(sp, ""):
        html(f'<p class="ec-note">{PHOTO_CREDIT}</p>')


def page_leagues():
    origin = st.session_state["mode"]
    if st.session_state.get("ligue") in config.SPORTS:
        league_view(origin, st.session_state["ligue"])
        return
    soon_leagues = [(n, c, k) for k, n, c in SOON_LEAGUES] + [(n, c, None) for n, c in SOON_US]
    n_leagues = len(config.SPORTS) + len(soon_leagues)
    hero("Ligues", f"{n_leagues} ligues · {len(SOON_CUPS)} coupes · {len(SOON_INTL)} International",
         "Trois ligues avec les données du moteur ; les autres arrivent. Même méthode, mêmes métriques pour chaque ligue.")
    demo_strip(origin)
    today = pd.Timestamp.today().normalize()
    with st.container(key="ec_bento_live"):
        for sp in config.SPORTS:  # tuiles cliquables : uniquement les ligues avec des données moteur
            r, U = report(origin, sp), upcoming(origin, sp)[0]
            model, _, ic = headline(r)
            n_up = int((U["game_date"] >= today).sum()) if (U is not None and origin == "real") else 0
            name, country = COMP[sp]
            with st.container(key=f"ec_tile_{sp}"):
                html(league_img(sp, "league-img"))
                ui.card(title=name, description=f"{SPORT_NAME[sp]} · {country}", key=f"card_{sp}",
                        content=f"{r['effectifs']['matchs_finaux_evalues'] if r else '—'} matchs évalués · log loss "
                                f"{fr_num(model) if model else '—'} · {n_up} à venir",
                        footer=f"Statut : {ic['statut'] if ic else 'pas de rapport'} · Voir la ligue →")
                html(f'<a class="ec-tile-link" href="{escape(url("ligues", ligue=sp))}" target="_self" '
                     f'aria-label="{name} — voir la ligue"></a>')
    ad(728, 90)
    # Compétitions sans données moteur : tuiles grisées « Bientôt », non cliquables, aucun chiffre. Pub après la 3e tuile.
    html(f'<div class="ec-h2">{SOON}</div><p class="ec-note">Ces compétitions arriveront quand le moteur aura des données '
         "autorisées pour elles. Aucun match, aucun chiffre n'est affiché d'ici là.</p>")
    soon_tiles("leagues_a", soon_leagues[:3])
    ad(728, 90)
    soon_tiles("leagues_b", soon_leagues[3:])
    html('<div class="ec-h2">Coupes nationales</div>')
    soon_tiles("cups", SOON_CUPS)
    html('<div class="ec-h2">International</div>')
    soon_tiles("intl", SOON_INTL)
    html(f'<p class="ec-note">{PHOTO_CREDIT}</p>')


def soon_tiles(group: str, items):
    with st.container(key=f"ec_bento_soon_{group}"):
        for name, sub, *img in items:
            with st.container(key=f"ec_soon_{label_key(name)}"):
                if img and img[0]:
                    html(league_img(img[0], "league-img"))
                ui.card(title=name, description=sub, content="Bientôt — pas encore de données", key=f"soon_{label_key(name)}")


def page_live():
    hero("En direct", "Rien en direct pour l'instant.",
         "EDGECOURT publie des prévisions d'avant-match. Le suivi en direct n'est pas encore branché sur une source de données.")
    P = preds("demo", "nba")
    if P is not None and len(P):
        g = P.iloc[-1]
        html(f'<div class="ec-card"><span class="ec-tag ex">Données d\'exemple</span><span class="ec-tag">Aperçu du format</span>'
             f'<h3>{g["home_team"]} – {g["away_team"]}</h3><div class="ec-note">Équipes fictives (démonstration synthétique). '
             "Voici à quoi ressemblera une carte en direct : la prévision d'avant-match, puis son évolution.</div>"
             f'<div style="margin-top:14px">{prob_cell(g["p_home_final"], g["p_draw_final"], g["p_away_final"])}</div></div>')
    ad(728, 90)


def page_web():
    origin = st.session_state["mode"]
    sport = pick_sport()
    hero("La toile", "Qui a affronté qui.", "Chaque trait relie deux équipes qui se sont rencontrées sur la dernière saison en base ; "
         "la taille d'un point suit son Elo avant son dernier match.")
    demo_strip(origin)
    P = preds(origin, sport)
    F = P[P["status"] == "final"] if P is not None else None
    if F is None or F.empty:
        st.info("Pas de matchs terminés pour cette ligue.")
        ad(728, 90)
        return
    F = F[F["season"] == F["season"].max()]
    teams = sorted(set(F["home_team"]) | set(F["away_team"]))
    n = len(teams)
    pos = {t: (math.cos(2 * math.pi * k / n), math.sin(2 * math.pi * k / n)) for k, t in enumerate(teams)}
    xs, ys = [], []
    for h, a in F[["home_team", "away_team"]].drop_duplicates().itertuples(index=False):
        xs += [pos[h][0], pos[a][0], None]
        ys += [pos[h][1], pos[a][1], None]
    elo = {}
    for r in F.sort_values("game_date").itertuples():
        elo[r.home_team], elo[r.away_team] = r.elo_h, r.elo_a
    ev = pd.Series(elo).reindex(teams)
    size = 10 + 30 * (ev - ev.min()) / max(ev.max() - ev.min(), 1)
    fig = go.Figure([go.Scatter(x=xs, y=ys, mode="lines", line=dict(color="rgba(13,15,14,.12)", width=1), hoverinfo="skip"),
                     go.Scatter(x=[pos[t][0] for t in teams], y=[pos[t][1] for t in teams], mode="markers+text", text=teams,
                                textposition="top center", marker=dict(size=size, color=ACCENT),
                                hovertext=[f"{t} · Elo {ev[t]:.0f}" for t in teams], hoverinfo="text")])
    fig.update_layout(height=640, showlegend=False, plot_bgcolor="#fbfbf8", paper_bgcolor="#fbfbf8", margin=dict(l=10, r=10, t=10, b=10),
                      xaxis=dict(visible=False), yaxis=dict(visible=False, scaleanchor="x"))
    st.plotly_chart(fig, use_container_width=True)
    st.caption(f"Saison {F['season'].max()} · {n} équipes · {len(F)} matchs terminés.")
    ad(728, 90)


def page_player():
    hero("Fiche joueur", "Joueur Exemple", "Le moteur ne contient pas encore de données individuelles : cette fiche montre le format prévu.")
    html('<span class="ec-tag ex">Données d\'exemple</span><span class="ec-note">Chiffres fictifs, aucune prévision réelle.</span>')
    html(big_html([("Minutes / match", "31,4"), ("Points / match", "18,2"), ("Impact estimé", "+2,1")]))
    st.caption("Données d'exemple — à remplacer par une source joueurs autorisée avant toute publication.")


def page_team():
    origin = st.session_state["mode"]
    sport = pick_sport()
    demo_strip(origin)
    P = preds(origin, sport)
    if P is None:
        hero("Fiche équipe", "Aucune donnée", "Pas de prévisions pour cette ligue.")
        return
    teams = sorted(set(P["home_team"]) | set(P["away_team"]))
    focus = st.session_state.pop("team_focus", None)
    if focus in teams or st.session_state.get("team_sel") not in teams:
        st.session_state["team_sel"] = focus if focus in teams else teams[0]
    team = st.selectbox("Équipe", teams, key="team_sel")
    F = P[((P["home_team"] == team) | (P["away_team"] == team)) & (P["status"] == "final")].sort_values("game_date")
    hero(f"Fiche équipe · {config.SPORT_LABEL[sport]}", team)
    if F.empty:
        st.info("Aucun match terminé en base pour cette équipe.")
        return
    home = F["home_team"] == team
    elo = F["elo_h"].where(home, F["elo_a"])
    wins = int(((F["home_score"] > F["away_score"]) & home).sum() + ((F["away_score"] > F["home_score"]) & ~home).sum())
    html(big_html([("Elo (avant dernier match)", f"{elo.iloc[-1]:.0f}"), ("Matchs en base", len(F)), ("Victoires", wins)]))
    fig = go.Figure(go.Scatter(x=F["game_date"], y=elo, mode="lines", line_color=ACCENT))
    fig.update_layout(title="Elo avant chaque match", height=300, margin=dict(l=10, r=10, t=40, b=10), plot_bgcolor="#fff")
    st.plotly_chart(fig, use_container_width=True)
    html('<div class="ec-h2">Derniers matchs</div>')
    rec = F.tail(10).iloc[::-1]
    rh = rec["home_team"] == team
    st.dataframe(pd.DataFrame({
        "Date": rec["game_date"].dt.date, "Match": rec["home_team"] + " – " + rec["away_team"],
        "Score": rec["home_score"].astype(int).astype(str) + " - " + rec["away_score"].astype(int).astype(str),
        f"P({team}) prévue": rec["p_home_final"].where(rh, rec["p_away_final"]).map(pct), "Période": rec["segment"]}),
        use_container_width=True, hide_index=True)


# ---------------------------------------------------------------- outils (comportement existant conservé)
def page_simulation():
    origin = st.session_state["mode"]
    sport = pick_sport()
    R, S = report(origin, sport), sim(origin, sport)
    hero("Outils · simulation de recherche", "Simulation", "Test des règles de règlement à mise fixe d'une unité, sans recommandation. "
         "Ce n'est ni un conseil de mise ni une gestion de bankroll.")
    demo_strip(origin)
    if R is None or "simulation" not in R:
        st.info("Rendement non évaluable : pas de rapport.")
        return
    seg = st.radio("Période", ["test", "calibration"], horizontal=True, format_func=lambda s: "test final" if s == "test" else "validation")
    sm = R["simulation"][seg]
    if R["simulation"].get("note"):
        st.warning(R["simulation"]["note"])
    if sm.get("statut") == "rendement non évaluable":
        st.info(f"Rendement non évaluable — {sm.get('raison', '')}")
    else:
        c = st.columns(5)
        c[0].metric("Paris simulés", sm["paris"]); c[1].metric("Profit (unités)", f"{sm['profit_unites']:+.2f}")
        c[2].metric("ROI fictif net", f"{100 * sm['roi_net']:+.1f} %"); c[3].metric("Drawdown max (u)", f"{sm['drawdown_max_unites']:.1f}")
        c[4].metric("G / P / R", f"{sm['gagnes']} / {sm['perdus']} / {sm['rembourses']}")
        st.write(f"Statut : **{sm['statut']}** · IC 95 % du profit moyen par pari : [{sm['roi_ic95'][0]:+.3f} ; {sm['roi_ic95'][1]:+.3f}] "
                 f"· frais supposés par unité : {sm['frais_par_unite']}")
        cv = pd.DataFrame(sm["courbe_cumulee"])
        fig = go.Figure(go.Scatter(x=cv["date"], y=cv["cumul"], mode="lines", line_color=ACCENT))
        fig.update_layout(title="Profit cumulé (unités)", height=320, margin=dict(l=10, r=10, t=40, b=10), plot_bgcolor="#fff")
        st.plotly_chart(fig, use_container_width=True)
        st.caption(sm["avertissement"])
    if S is not None and len(S):
        with st.expander("Détail des cotes évaluées"):
            st.dataframe(S[S["segment"] == seg].tail(500), use_container_width=True, hide_index=True)
    cts = R.get("cotes", {})
    st.caption(f"Cotes importées : {cts.get('importees', 0)} · admissibles : {cts.get('admissibles', 0)} · "
               f"refusées (postérieures à la prévision) : {cts.get('refusees_posterieures_au_cutoff', 0)}")


def page_data():
    origin = st.session_state["mode"]
    hero("Outils", "Données", "Connecteurs, imports, licences.")
    s_ = store.Store(origin)
    try:
        imp, rej = s_.imports(), s_.rejects()
        st.subheader("Connecteurs")
        st.dataframe(connectors.status_table(s_), use_container_width=True, hide_index=True)
        stp = config.origin_dir("real") / "connector_status.json"
        if origin == "real" and stp.exists():
            st.json(json.loads(stp.read_text(encoding="utf-8")), expanded=False)
        st.subheader("Imports et fraîcheur")
        if imp.empty:
            st.info("Aucun import. Exécuter `.\\scripts\\fetch.ps1` ou importer un CSV ci-dessous.")
        else:
            st.dataframe(imp[["sport", "source", "retrieved_at", "rows_read", "accepted", "inserted", "updated", "unchanged", "rejected",
                              "min_date", "max_date", "coverage", "sha256"]], use_container_width=True, hide_index=True)
        if len(rej):
            with st.expander(f"Lignes rejetées ({len(rej)})"):
                st.dataframe(rej, hide_index=True)
    finally:
        s_.close()
    st.subheader("Sources, licences et attribution")
    st.markdown(
        "- **nflverse-data** (NFL) : dépôt sous licence CC-BY-4.0 → attribution « nflverse » obligatoire.\n"
        "- **StatsBomb Open Data** (soccer, Premier League 2015/2016) : usage de recherche locale ; pas de redistribution ni d'exploitation "
        "commerciale ; toute publication doit créditer StatsBomb avec son logo.\n"
        "- **BALLDONTLIE** (NBA) : endpoint Games annoncé gratuit avec une clé gratuite (5 requêtes/min). Les autres endpoints sont payants.\n"
        "- Détails, dates de vérification et limites : `docs/DATA_SOURCES.md`.")
    st.subheader("Import CSV")
    if origin == "demo":
        st.info("Les imports sont désactivés en mode démonstration : la base synthétique est isolée de la base réelle.")
        return
    i1, i2 = st.columns(2)
    for col, kind, fn, sample in ((i1, "matchs", pipeline.import_games_csv, "games_example.csv"),
                                  (i2, "cotes", pipeline.import_odds_csv, "odds_example.csv")):
        with col:
            st.markdown(f"**{kind.capitalize()}** (colonnes : voir `samples/{sample}`)")
            spx = st.selectbox("Sport du fichier", list(config.SPORTS), key=f"sp_{kind}", format_func=config.SPORT_LABEL.get)
            upx = st.file_uploader(f"CSV de {kind} (données dont vous avez les droits)", type="csv", key=f"u_{kind}")
            if upx and st.button(f"Importer les {kind}"):
                with tempfile.TemporaryDirectory() as td:
                    pth = Path(td) / upx.name
                    pth.write_bytes(upx.getvalue())
                    try:
                        st.json(fn("real", spx, str(pth)))
                        st.cache_data.clear()
                    except Exception as ex:
                        st.error(f"Import refusé : {ex}")
    if st.button("Recalculer l'évaluation (réel)"):
        with st.spinner("Évaluation en cours…"):
            pipeline.run_all("real")
        st.cache_data.clear()
        st.success("Évaluation terminée.")


def admin_password() -> str:
    """Mot de passe admin lu dans st.secrets (jamais dans le code) ; chaîne vide si absent."""
    try:
        return str(st.secrets.get("ADMIN_PASSWORD", "") or "")
    except Exception:  # pas de secrets.toml du tout
        return ""


LOCK_AFTER, LOCK_SECONDS = 5, 15 * 60
LOCKED_MSG = "Trop de tentatives — réessayez dans 15 minutes"


FORGET_SECONDS = 24 * 3600  # un visiteur inactif depuis 24 h (et non bloqué) est oublié : la table reste bornée


@st.cache_resource
def admin_attempts() -> dict:
    """Compteurs par visiteur, partagés par tout le serveur (un rechargement ne les remet pas à zéro)."""
    return {"by": {}, "lock": threading.Lock()}


def trusted_proxies() -> int:
    """Nombre de proxys de confiance devant l'app (secret ADMIN_TRUSTED_PROXIES, 0 par défaut)."""
    try:
        return max(0, int(st.secrets.get("ADMIN_TRUSTED_PROXIES", 0) or 0))
    except Exception:
        return 0


def visitor_key() -> str:
    """Identité du visiteur pour la limite d'essais : son adresse IP.

    Par défaut, l'IP de la connexion réseau (non falsifiable par un en-tête). Derrière un hébergeur / reverse proxy,
    toutes les connexions viennent du proxy : indiquer ADMIN_TRUSTED_PROXIES = n pour lire l'IP que le n-ième proxy
    a ajoutée en fin de X-Forwarded-For (les entrées plus à gauche, écrites par le client, sont ignorées).
    """
    hops = trusted_proxies()
    if hops:
        chain = [p.strip() for p in (st.context.headers.get("X-Forwarded-For") or "").split(",") if p.strip()]
        if len(chain) >= hops:
            return chain[-hops]
    return st.context.ip_address or "local"  # None = accès par localhost


# Lexique : définitions fournies telles quelles (aucune inventée). Les exemples chiffrés sont les vrais chiffres NFL.
LEXIQUE = [
    ("Domicile / Nul / Extérieur", "les 3 résultats possibles. Exemple : 60 % domicile = le modèle dit que l'équipe à domicile gagne 6 fois sur 10."),
    ("Élo", "le score de force d'une équipe, comme un classement. Il monte après une victoire, il baisse après une défaite."),
    ("Élo 10 / 20 / 40", "la même idée, avec 3 vitesses de changement — 10 lent, 40 rapide. On compare les 3 pour voir laquelle prédit le mieux."),
    ("Logit", "le modèle principal — le calcul qui transforme l'Élo + l'avantage à domicile en pourcentage."),
    ("Baseline", "la prédiction la plus bête possible (par exemple « l'équipe à domicile gagne toujours ») — c'est la référence à battre."),
    ("Log loss", "le score d'erreur du modèle — plus il est bas, mieux c'est. Exemple : 0,640 contre 0,696 = le modèle se trompe moins que la référence."),
    ("Brier", "un autre score d'erreur — 0 = parfait."),
    ("Skill Brier", "de combien le modèle est meilleur que la référence, en %."),
    ("Écart contre référence", "le modèle moins la baseline. Exemple : −0,056 = meilleur de 0,056."),
    ("IC 95 %", "l'intervalle de confiance — la zone où la vraie valeur se trouve probablement, à 95 % sûr. "
                "Exemple : [−0,076 ; −0,036] entièrement sous zéro = l'amélioration est réelle, pas de la chance."),
    ("Découpage", "comment on a séparé les matchs — Entraînement = apprendre, Validation = régler, "
                  "Test = l'examen final sur des matchs jamais vus (874 pour la NFL)."),
    ("Calibration", "est-ce que le pourcentage dit la vérité — 60 % annoncé doit gagner environ 60 fois sur 100. « Oui » = bon."),
    ("Distribution", "le graphique de tous les résultats possibles et lesquels sont les plus probables."),
    ("Forme", "les résultats récents d'une équipe."),
    ("Écart domicile–extérieur", "la différence attendue entre les deux équipes."),
]


def page_lexique():
    """Transparence : comment le modèle fonctionne, puis chaque terme de La preuve en accordéon (streamlit-facade)."""
    hero("Lexique", "Les mots de la preuve, en clair.", "Chaque terme affiché sur le site, expliqué en une ligne.")
    html('<div class="ec-h2">Comment ça marche</div>'
         "<p class=\"ec-lex-intro\">Le modèle transforme l'Élo des deux équipes et l'avantage à domicile en probabilité : domicile, nul ou extérieur. "
         f'Ensuite, {a(url("preuve"), "La preuve")} montre s\'il avait raison, sur des matchs qu\'il n\'avait jamais vus.</p>')
    html('<div class="ec-h2">Les termes</div>')
    for term, definition in LEXIQUE:
        with facade.Accordion(term):
            html(f'<p class="ec-def">{escape(definition[0].upper() + definition[1:])}</p>')


def page_admin():
    """Back-office : la page Données, derrière un mot de passe (5 essais faux → blocage 15 min, par visiteur)."""
    expected = admin_password()
    if not expected:
        st.info("Accès admin non configuré")
        return
    if not st.session_state.get("admin_ok"):
        att, who = admin_attempts(), visitor_key()
        now = time.monotonic()
        with att["lock"]:
            for k in [k for k, v in att["by"].items() if v["until"] < now and now - v["last"] > FORGET_SECONDS]:
                del att["by"][k]
            rec = att["by"].get(who)
        if rec and now < rec["until"]:
            st.error(LOCKED_MSG)
            return
        with st.form("admin_login"):
            pw = st.text_input("Mot de passe admin", type="password")
            if st.form_submit_button("Entrer"):
                with att["lock"]:
                    now = time.monotonic()
                    rec = att["by"].setdefault(who, {"fails": 0, "until": 0.0, "last": now})
                    rec["last"] = now
                    if now < rec["until"]:   # bloqué entre-temps (même visiteur, autre onglet)
                        ok = False
                    elif hmac.compare_digest(pw.encode(), expected.encode()):
                        del att["by"][who]
                        ok = True
                    else:
                        rec["fails"], ok = rec["fails"] + 1, False
                        if rec["fails"] >= LOCK_AFTER:
                            rec["fails"], rec["until"] = 0, now + LOCK_SECONDS
                    blocked = not ok and now < rec["until"]
                if ok:
                    st.session_state["admin_ok"] = True
                    st.rerun()
                if blocked:
                    st.rerun()   # affiche le message de blocage à la place du formulaire
                st.error("Mot de passe incorrect.")
        return
    page_data()


# ================================================================= Accueil (écran d'arrivée)
MODEL_LABEL = {"baseline": "Baseline", "elo10": "Élo 10", "elo20": "Élo 20", "elo40": "Élo 40", "logit": "Logit", "poisson": "Poisson"}
STRIP_MODELS = ["Baseline", "Élo 10", "Élo 20", "Élo 40", "Logit"]
ACCOUNTS_MSG = "Les comptes arrivent bientôt — l'app est gratuite et ouverte pour l'instant"
FAQ = [("C'est un site de pari ?", "Non. EDGECOURT est un site de prédiction : nos prédictions sont des conseils, "
                                    "la décision finale vous appartient."),
       ("D'où viennent les prédictions ?", "D'un modèle qui analyse les résultats passés (Élo + logit). Chaque résultat est publié."),
       ("C'est gratuit ?", "Oui, l'app est gratuite et ouverte.")]


def next_predictions(n: int = 3) -> list:
    """Les n prochaines prévisions réelles du moteur, toutes ligues confondues (jamais de démo, jamais d'invention)."""
    today = pd.Timestamp.today().normalize()
    rows = []
    for sp in config.SPORTS:
        U, _ = upcoming("real", sp)
        if U is not None and len(U):
            rows += [(sp, r) for _, r in U[U["game_date"] >= today].iterrows()]
    return sorted(rows, key=lambda x: (x[1]["game_date"], str(x[1]["game_id"])))[:n]


FINAL = ("p_home_final", "p_draw_final", "p_away_final")


def pick(r, cols) -> tuple[str, float]:
    """Issue la plus probable (équipe ou « Match nul ») parmi les colonnes (domicile, nul, extérieur)."""
    probs = {r["home_team"]: r[cols[0]], "Match nul": r[cols[1]], r["away_team"]: r[cols[2]]}
    best = max(probs, key=probs.get)
    return best, float(probs[best])


def model_votes(r) -> list[tuple[str, str]]:
    """Vote de chaque modèle du moteur (son issue la plus probable, avant calibration)."""
    models = [c[2:-2] for c in r.index if c.startswith("w_") and c.endswith("_h")]
    return [(MODEL_LABEL.get(m, m), pick(r, (f"w_{m}_h", f"w_{m}_d", f"w_{m}_a"))[0]) for m in models]


def featured_card(sp: str, r) -> str:
    winner, p = pick(r, FINAL)
    votes = model_votes(r)
    agree = sum(v == winner for _, v in votes)
    vote_rows = "".join(f'<li><span>{m}</span><b class="{"ok" if v == winner else ""}">{escape(v)}</b></li>' for m, v in votes)
    return (f'<div class="ec-feat"><div class="k">Prochaine prévision · {COMP[sp][0]} · {fr_date(r["game_date"])}</div>'
            f'<div class="t">{escape(r["home_team"])} <i>–</i> {escape(r["away_team"])}</div>'
            f'<div class="pred">Prédiction du modèle : <b>{escape(winner)}</b> <span>{pct(p)}</span></div>'
            f'<div class="agree"><div class="lab">Accord des modèles <b>{agree}/{len(votes)}</b></div>'
            f'<div class="bar"><span style="width:{100 * agree / max(len(votes), 1):.0f}%"></span></div></div>'
            f'<ul class="votes">{vote_rows}</ul>'
            '<p class="note">L\'accord des modèles est un vote, pas une probabilité.</p>'
            f'{a(url("match", sport=sp, game=r["game_id"]), "Voir cette prédiction", "ec-hero-btn")}</div>')


def mini_card(sp: str, r) -> str:
    winner, p = pick(r, FINAL)
    body =(f'<span class="k">{COMP[sp][0]} · {fr_date(r["game_date"])}</span>'
            f'<span class="t">{escape(r["home_team"])} – {escape(r["away_team"])}</span>'
            f'<span class="p">{escape(winner)} · {pct(p)}</span>')
    return a(url("match", sport=sp, game=r["game_id"]), body, "ec-mini")


@st.dialog("Comptes")
def accounts_dialog():
    st.write(ACCOUNTS_MSG)
    if st.button("Entrer dans l'app", type="primary"):
        st.switch_page(PAGES["today"])


def page_home():
    """Écran d'arrivée : promesse, prochaine prévision réelle avec le vote des 5 modèles, modèles, FAQ."""
    nxt = next_predictions()
    side = (featured_card(*nxt[0]) + '<div class="ec-minis">' + "".join(mini_card(*x) for x in nxt[1:]) + "</div>"
            if nxt else '<div class="ec-feat"><div class="t">Aucune prévision à venir</div>'
                        '<p class="note">Les prochaines prévisions apparaîtront ici dès que le moteur en publiera.</p></div>')
    badges = "".join(f'<span class="ec-badge" aria-disabled="true">{s}<small>Bientôt</small></span>' for s in ("App Store", "Google Play"))
    html('<section class="ec-hero ec-home"><div class="ec-home-grid"><div>'
         '<div class="h" role="heading" aria-level="1">Ton prochain match, <span class="g">déjà analysé.</span></div>'
         "<p>Des prédictions IA pour le foot, la NBA et la NFL. Des heures d'analyse, lues en quelques secondes — "
         "et chaque résultat noté en public.</p>"
         f'<div class="ec-badges">{badges}</div><p class="free">Gratuit · sans inscription pour l\'instant</p></div>'
         f"<div>{side}</div></div></section>")
    pills = "".join(f'<span class="ec-pill">{m}</span>' for m in STRIP_MODELS)
    html('<div class="ec-models-head"><b>5 modèles, une seule prédiction</b>' + a(url("preuve"), "À propos des modèles →") + "</div>"
         '<div class="ec-strip" aria-label="Modèles du moteur"><div class="ec-strip-track">'
         f'<div class="ec-strip-set">{pills * 2}</div><div class="ec-strip-set" aria-hidden="true">{pills * 2}</div></div></div>')
    html('<section id="faq" class="ec-faq"><div class="ec-h2">Questions fréquentes</div>'
         + "".join(f"<details><summary>{q}</summary><p>{r}</p></details>" for q, r in FAQ) + "</section>")


# ================================================================= cadre commun
PAGES = {
    "home": st.Page(page_home, title="Accueil", url_path="accueil", default=True),
    "today": st.Page(page_today, title="Aujourd'hui", url_path="aujourdhui"),
    "match": st.Page(page_match, title="Détail d'un match", url_path="match"),
    "proof": st.Page(page_proof, title="La preuve", url_path="preuve"),
    "leagues": st.Page(page_leagues, title="Ligues", url_path="ligues"),
    "live": st.Page(page_live, title="En direct", url_path="direct"),
    "web": st.Page(page_web, title="La toile", url_path="toile"),
    "player": st.Page(page_player, title="Fiche joueur", url_path="joueur"),
    "team": st.Page(page_team, title="Fiche équipe", url_path="equipe"),
    "sim": st.Page(page_simulation, title="Simulation", url_path="simulation"),
    "lexique": st.Page(page_lexique, title="Lexique", url_path="lexique"),
    "admin": st.Page(page_admin, title="Admin", url_path="admin"),
}
nav = st.navigation(list(PAGES.values()), position="hidden")
with st.sidebar.container(key="ec_admin"):
    st.page_link(PAGES["admin"], label="Admin")

# Liens internes (<a href>) = nouvelle session : on reprend l'état depuis l'URL une seule fois, avant les widgets.
if "_from_url" not in st.session_state:
    st.session_state["_from_url"] = True
    qp = st.query_params
    if qp.get("mode") in ("real", "demo"):
        st.session_state["mode"] = qp["mode"]
    if qp.get("sport") in config.SPORTS:
        st.session_state["sport"] = qp["sport"]
    if qp.get("sport") in NAV_SPORTS:
        st.session_state["nav_sport"] = None if qp["sport"] in config.SPORTS else qp["sport"]
    if qp.get("game"):
        st.session_state["focus"] = qp["game"]
    if qp.get("team"):
        st.session_state["team_focus"] = qp["team"]
st.session_state["ligue"] = st.query_params.get("ligue")

html(f'<div class="ec-banner">{BANNER}</div>')
# Barre du haut (toutes les pages) : logo · devise · comptes, puis la barre des sports, puis les liens de pages.
n1, n2, n3 = st.columns([2, 4, 3], vertical_alignment="center")
n1.markdown(f'<a href="{escape(url("accueil"))}" target="_self"><img class="ec-nav-logo" src="{asset_uri("logo-primary.png")}" '
            'alt="EDGECOURT — Accueil"></a>', unsafe_allow_html=True)
n2.markdown(f'<p class="ec-tagline">{TAGLINE}</p>', unsafe_allow_html=True)
with n3.container(horizontal=True, gap="small", horizontal_alignment="right"):
    if st.button("Se connecter"):
        accounts_dialog()
    if st.button("Créer un compte", type="primary"):
        accounts_dialog()
st.html(sport_bar("accueil" if nav is PAGES["home"] else nav_sport() if nav is PAGES["today"] else None),
        unsafe_allow_javascript=True)  # JS interne (ouverture/fermeture des menus), aucun contenu externe
l1, l2 = st.columns([5, 2], vertical_alignment="center")
with l1.container(horizontal=True, gap="small"):
    st.page_link(PAGES["today"], label="Prédictions")
    st.page_link(PAGES["proof"], label="La preuve")
    st.page_link(PAGES["proof"], label="Modèles")
    st.page_link(PAGES["proof"], label="Méthodologie")
    html(f'<a class="ec-faq-link" href="{escape(url("accueil"))}#faq" target="_self">FAQ</a>')
    st.page_link(PAGES["lexique"], label="Lexique")
    for k in ("match", "leagues", "live", "web", "player", "team", "sim"):
        st.page_link(PAGES[k])
if nav is not PAGES["home"]:  # l'Accueil ne montre que des prévisions réelles
    with l2:
        st.radio("Données", ["real", "demo"], key="mode", horizontal=True, label_visibility="collapsed",
                 format_func=lambda m: "Données réelles" if m == "real" else "Démonstration synthétique")
st.divider()
nav.run()
