"""Bibliothèques UI (shadcn-ui, facade) + tuiles Ligues (bento) + chiffres de La preuve (compteur)."""
import json
from pathlib import Path

from streamlit.testing.v1 import AppTest
from streamlit.util import calc_hash

ROOT = Path(__file__).resolve().parents[1]
APP = str(ROOT / "src" / "edgecourt" / "ui" / "app.py")
LIVE = {"NBA": "nba", "Premier League": "soccer", "NFL": "nfl"}
SOON = ["La Liga", "Serie A", "Bundesliga", "Ligue 1", "Championship", "WNBA", "NHL", "MLB",
        "FA Cup", "EFL Cup", "Coupe de France", "DFB-Pokal", "Coppa Italia", "Copa del Rey",
        "UEFA Nations League", "Éliminatoires Coupe du Monde — Europe", "Éliminatoires Coupe du Monde — Amérique du Sud"]


def page(path: str) -> AppTest:
    at = AppTest.from_file(APP, default_timeout=120)
    at._page_hash = calc_hash(path)
    return at.run()


def walk(node, out):
    for c in getattr(node, "children", {}).values():
        out.append(c)
        walk(c, out)
    return out


def shadcn(at: AppTest, kind: str) -> list[dict]:
    """Props des composants shadcn-ui rendus (AppTest ne les dessine pas : on lit ce qui leur est envoyé)."""
    els = [e for e in walk(at._tree, []) if getattr(e, "type", "") == "bidi_component"
           and e.proto.component_name == "streamlit-shadcn-ui.v2"]
    return [p["props"] for p in (json.loads(e.proto.json) for e in els) if p["kind"] == kind]


def md(at: AppTest) -> str:
    return "".join(m.value for m in at.markdown)


def test_both_libraries_import():
    import facade  # streamlit-facade
    import streamlit_shadcn_ui as ui
    assert callable(ui.metric_card) and callable(ui.card) and facade.__name__ == "facade"


def test_ligues_tiles_three_clickable_rest_soon():
    at = page("ligues")
    assert not at.exception
    h = md(at)
    assert "11 ligues · 6 coupes · 3 International" in h
    cards = shadcn(at, "card")
    assert [c["title"] for c in cards] == list(LIVE) + SOON
    links = sorted(h.split('class="ec-tile-link" href="')[1:])
    assert [x.split('"')[0] for x in links] == sorted(f"ligues?ligue={sp}" for sp in LIVE.values())
    for c in cards[3:]:
        assert c["content"] == "Bientôt — pas encore de données"  # aucun chiffre, aucun lien
    assert h.count('class="ec-tile-link" href') == 3 and h.count(">Publicité<") == 2  # pubs inchangées


def test_preuve_numbers_are_real_and_count_up():
    at = page("preuve")
    assert not at.exception
    r = json.loads((ROOT / "artifacts" / "real" / "report_nfl.json").read_text(encoding="utf-8"))
    metrics = {m["label"]: m["value"] for m in shadcn(at, "metric_card")}
    assert list(metrics)[:4] == ["Matchs de test", "Log loss du modèle", "Écart vs référence", "IC 95 %"]  # puis le bilan
    assert metrics["Matchs de test"] == str(r["effectifs"]["test"])  # vrai chiffre du moteur, jamais inventé
    js = next(e.proto.body for e in walk(at._tree, []) if getattr(e, "type", "") == "html" and "ec_tick_" in e.proto.body)
    assert all(k in js for k in ("requestAnimationFrame", '[data-slot="card-title"]', "prefers-reduced-motion", "el.textContent = p < 1"))
