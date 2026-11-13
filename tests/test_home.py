"""Écran d'arrivée (Accueil) : page par défaut, aucune donnée inventée, comptes « bientôt », badges inertes."""
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

APP = str(Path(__file__).resolve().parents[1] / "src" / "edgecourt" / "ui" / "app.py")
SOON = "Les comptes arrivent bientôt — l'app est gratuite et ouverte pour l'instant"


def home() -> AppTest:
    return AppTest.from_file(APP, default_timeout=120).run()  # pas de page demandée : la page par défaut doit être l'Accueil


def page_html(at: AppTest) -> str:
    return "".join(m.value for m in at.markdown)


def test_home_is_default_and_shows_real_prediction_or_nothing():
    at = home()
    assert not at.exception
    h = page_html(at)
    assert "ec-banner" in at.markdown[1].value or "ec-banner" in at.markdown[0].value  # le bandeau fondateur reste en tête
    assert "Ton prochain match" in h
    assert ("Prochaine prévision" in h and "Accord des modèles" in h and "un vote, pas une probabilité" in h) \
        or "Aucune prévision à venir" in h
    assert "App Store" in h and "apps.apple.com" not in h and "play.google.com" not in h  # badges « Bientôt », sans lien
    for q in ("C'est un site de pari ?", "D'où viennent les prédictions ?", "C'est gratuit ?"):
        assert q in h


@pytest.mark.parametrize("label", ["Se connecter", "Créer un compte"])
def test_account_buttons_announce_accounts_are_coming(label):
    at = home()
    next(b for b in at.button if b.label == label).click().run()
    assert not at.exception
    assert any(SOON in m.value for m in at.markdown)
    assert any(b.label == "Entrer dans l'app" for b in at.button)
