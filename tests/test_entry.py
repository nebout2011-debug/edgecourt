"""Écran d'entrée : vue par défaut au premier chargement, sans nav, même héros + vraie prévision que l'Accueil,
bouton « Entrer dans l'app » → interface complète (Accueil + nav), bandeau des 5 modèles."""
import re
from pathlib import Path

from streamlit.testing.v1 import AppTest
from streamlit.util import calc_hash

APP = str(Path(__file__).resolve().parents[1] / "src" / "edgecourt" / "ui" / "app.py")
MODELS = ["Baseline", "Élo 10", "Élo 20", "Élo 40", "Logit"]
SOON = "Les comptes arrivent bientôt — l'app est gratuite et ouverte pour l'instant"


def first_load() -> AppTest:
    return AppTest.from_file(APP, default_timeout=120).run()  # aucune page demandée = premier chargement


def md(at: AppTest) -> str:
    return "".join(m.value for m in at.markdown)


def has_nav(at: AppTest) -> bool:
    return any('id="ec-nav"' in h.proto.body for h in at.get("html"))


def test_entry_is_the_default_view_without_nav():
    at = first_load()
    assert not at.exception
    h = md(at)
    assert "ec-banner" in h  # bandeau fondateur en tête
    assert 'Ton prochain match, <span class="g">déjà analysé.</span>' in h
    assert "Gratuit et ouvert — sans inscription" in h and "App Store<small>Bientôt</small>" in h
    assert ("Accord des modèles" in h and "un vote, pas une probabilité" in h) or "Aucune prévision à venir" in h
    assert any(b.label == "Entrer dans l'app" for b in at.button)
    assert not has_nav(at)  # pas de barre des sports / menus
    assert not list(at.main.get("page_link"))  # pas de rangée de liens de pages
    assert '<footer class="ec-footer"' not in h and ">Publicité<" not in h
    assert '[data-testid="stSidebar"]' in h  # barre latérale masquée sur cet écran


def test_entry_strip_shows_the_five_models():
    h = md(first_load())
    assert "5 modèles, un appel EDGECOURT" in h and 'href="preuve"' in h and "À propos des modèles →" in h
    strip = h[h.index("5 modèles, un appel EDGECOURT"):]
    assert re.findall(r'<span class="ec-pill">([^<]+)</span>', strip)[:5] == MODELS


def test_entry_card_is_the_same_real_prediction_as_accueil():
    card = re.search(r'<div class="ec-feat">.*?</div></div>', md(first_load()), re.S)
    home = AppTest.from_file(APP, default_timeout=120)
    home._page_hash = calc_hash("accueil")
    home.run()
    assert card and card.group(0) in md(home)  # même carte, mêmes données réelles


def test_enter_button_opens_the_app_and_is_remembered():
    at = first_load()
    next(b for b in at.button if b.label == "Entrer dans l'app").click().run()
    assert not at.exception
    assert has_nav(at)  # interface complète
    assert "Questions fréquentes" in md(at)  # sur l'Accueil
    assert at.session_state["entered"] is True
    at.run()  # navigation dans la même session : pas de retour à l'écran d'entrée
    assert has_nav(at) and not any(b.label == "Entrer dans l'app" for b in at.button)


def test_account_buttons_on_entry():
    at = first_load()
    next(b for b in at.button if b.label == "Créer un compte").click().run()
    assert any(SOON in m.value for m in at.markdown)
