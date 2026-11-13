"""Page Lexique : « Comment ça marche », un accordéon par terme (définitions exactes), liens depuis la nav et La preuve."""
from pathlib import Path

from streamlit.testing.v1 import AppTest
from streamlit.util import calc_hash

APP = str(Path(__file__).resolve().parents[1] / "src" / "edgecourt" / "ui" / "app.py")
TERMS = ["Domicile / Nul / Extérieur", "Élo", "Élo 10 / 20 / 40", "Logit", "Baseline", "Log loss", "Brier", "Skill Brier",
         "Écart contre référence", "IC 95 %", "Découpage", "Calibration", "Distribution", "Forme", "Écart domicile–extérieur"]


def page(path: str) -> AppTest:
    at = AppTest.from_file(APP, default_timeout=120)
    at._page_hash = calc_hash(path)
    return at.run()


def md(at: AppTest) -> str:
    return "".join(m.value for m in at.markdown)


def test_lexique_has_how_it_works_and_one_accordion_per_term():
    at = page("lexique")
    assert not at.exception
    h = md(at)
    assert "Comment ça marche" in h and "avantage à domicile en probabilité" in h and 'href="preuve"' in h
    assert [e.label for e in at.expander] == TERMS
    defs = {e.label: "".join(m.value for m in e.markdown) for e in at.expander}
    assert "Exemple : 0,640 contre 0,696 = le modèle se trompe moins que la référence." in defs["Log loss"]
    assert "Exemple : [−0,076 ; −0,036] entièrement sous zéro" in defs["IC 95 %"]
    assert "Test = l&#x27;examen final sur des matchs jamais vus (874 pour la NFL)." in defs["Découpage"]
    assert defs["Brier"].endswith("Un autre score d&#x27;erreur — 0 = parfait.</p>")
    assert ">Publicité<" not in h  # aucune pub ajoutée
    words = " ".join([*TERMS, *defs.values()]).lower()  # texte visible des termes (pas les images en base64)
    for banned in ("cote", "pari ", "parlay", "bookmaker", "xg"):
        assert banned not in words


def test_lexique_reachable_from_nav_and_la_preuve():
    at = page("preuve")
    assert 'href="lexique"' in md(at)
    assert any(e.proto.label == "Lexique" for e in at.get("page_link"))
