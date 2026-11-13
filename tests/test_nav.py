"""Barre du haut : logo · devise · comptes, barre des 5 sports (rien d'autre), ligues sans données en « Bientôt »."""
import re
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest
from streamlit.util import calc_hash

APP = str(Path(__file__).resolve().parents[1] / "src" / "edgecourt" / "ui" / "app.py")
TAGLINE = "La prédiction, prouvée en public."
SOON = "Les comptes arrivent bientôt — l'app est gratuite et ouverte pour l'instant"


def run(page: str = "aujourdhui", **query) -> AppTest:
    at = AppTest.from_file(APP, default_timeout=120)
    at.query_params.update(query)
    at._page_hash = calc_hash(page)
    return at.run()


def html(at: AppTest) -> str:
    return "".join(m.value for m in at.markdown)


def nav_html(at: AppTest) -> str:
    return next(h.proto.body for h in at.get("html") if 'id="ec-nav"' in h.proto.body)


def sport_bar(at: AppTest) -> str:
    """Les entrées de la barre noire elle-même (hors cartes dépliantes)."""
    return "".join(re.findall(r'<a class="ec-top[^>]*>[^<]+</a>', nav_html(at)))


@pytest.mark.parametrize("page", ["accueil", "aujourdhui", "preuve"])
def test_bar_on_every_page_with_tagline_and_only_the_five_sports(page):
    at = run(page)
    assert not at.exception
    bar = sport_bar(at)
    assert re.findall(r">([^<]+)</a>", bar) == ["Accueil", "Football", "Basketball", "Football Américain", "Hockey", "Baseball"]
    h = html(at) + nav_html(at)
    assert TAGLINE in h and "Football is Mathematics" not in h
    for absent in ("Tennis", "MMA", "Rugby", "Cricket", "Favoris", "Programme TV"):
        assert absent not in bar
    assert {"Se connecter", "Créer un compte"} <= {b.label for b in at.button}


def test_active_sport_and_leagues_without_data_are_soon():
    at = run(sport="soccer")
    assert 'aria-current="page">Football<' in sport_bar(at)
    h = html(at)
    assert '<span class="ec-pill on">Premier League</span>' in h  # ligue du moteur
    for league in ("La Liga", "Serie A", "Bundesliga", "Ligue 1", "Championship", "Coupes nationales", "International"):
        assert f"{league}<small>Bientôt</small>" in h


def test_sport_without_engine_data_shows_no_match():
    at = run(sport="nhl")
    assert not at.exception
    assert 'aria-current="page">Hockey<' in sport_bar(at)
    h = html(at)
    assert "NHL<small>Bientôt</small>" in h and 'class="ec-row' not in h and "Aucune donnée moteur" in h


def test_home_highlights_accueil():
    assert 'aria-current="page">Accueil<' in sport_bar(run("accueil"))


@pytest.mark.parametrize("label", ["Se connecter", "Créer un compte"])
def test_account_buttons_behave_as_on_home(label):
    at = run()
    next(b for b in at.button if b.label == label).click().run()
    assert not at.exception
    assert any(SOON in m.value for m in at.markdown)
    assert any(b.label == "Entrer dans l'app" for b in at.button)
