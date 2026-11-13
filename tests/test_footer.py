"""Pied de page : présent sur chaque page avec logo, devise, avertissement, liens (vers des pages existantes), copyright."""
import re
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest
from streamlit.util import calc_hash

APP = str(Path(__file__).resolve().parents[1] / "src" / "edgecourt" / "ui" / "app.py")
PAGES = ["accueil", "aujourdhui", "match", "preuve", "ligues", "direct", "toile", "joueur", "equipe", "simulation",
         "lexique", "journal", "admin"]
DISCLAIMER = ("Site de prédiction — pas un site de pari. Nos prédictions sont des conseils et des idées pour vous aider "
              "à juger — la décision finale vous appartient.")
LINKS = [("La preuve", "preuve"), ("Journal", "journal"), ("Lexique", "lexique"), ("FAQ", "accueil#faq"),
         ("Ligues", "ligues"), ("Aujourd'hui", "aujourdhui")]


@pytest.mark.parametrize("page", PAGES)
def test_footer_on_every_page(page):
    at = AppTest.from_file(APP, default_timeout=120)
    at._page_hash = calc_hash(page)
    at.run()
    assert not at.exception
    footer = at.markdown[-1].value  # dernier élément de la page
    assert footer.startswith('<footer class="ec-footer"')
    assert re.search(r'<img src="data:image/png;base64,[^"]+" alt="EDGECOURT">', footer)  # logo
    assert "La prédiction, prouvée en public." in footer and DISCLAIMER in footer
    assert re.findall(r'<a href="([^"]+)" target="_self">([^<]+)</a>', footer) == [(h, t) for t, h in LINKS]
    assert footer.rstrip().endswith('<div class="ec-footer-copy">© 2026 EDGECOURT</div></footer>')
    assert "Publicité" not in footer


def test_footer_links_point_to_existing_pages():
    paths = set(re.findall(r'url_path="([a-z]+)"', Path(APP).read_text(encoding="utf-8")))
    for _, href in LINKS:
        assert href.partition("#")[0] in paths
