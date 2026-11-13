"""Cartes dépliantes de la barre : Sports (sport → ligues) et méga-menu La preuve. Seul ce qui existe est cliquable."""
import re
from pathlib import Path

from streamlit.testing.v1 import AppTest
from streamlit.util import calc_hash

APP = str(Path(__file__).resolve().parents[1] / "src" / "edgecourt" / "ui" / "app.py")
LEAGUES = {"Football": ["Premier League", "La Liga", "Serie A", "Bundesliga", "Ligue 1", "Championship", "Coupes nationales", "International"],
           "Basketball": ["NBA", "WNBA"], "Football Américain": ["NFL"], "Hockey": ["NHL"], "Baseball": ["MLB"]}
LIVE = {"Premier League": "soccer", "NBA": "nba", "NFL": "nfl"}  # les seules ligues avec des données moteur


def nav() -> tuple[AppTest, str]:
    at = AppTest.from_file(APP, default_timeout=120)
    at._page_hash = calc_hash("aujourdhui")
    at.run()
    el = next(h for h in at.get("html") if 'id="ec-nav"' in h.proto.body)
    return at, el.proto.body


def block(h: str, start: str, end: str) -> str:
    return h[h.index(start):h.index(end, h.index(start))]


def test_sports_card_lists_the_five_sports_with_their_leagues():
    at, h = nav()
    assert not at.exception
    card = block(h, 'id="ec-dd-sports"', "</ul></div>")
    sports = re.findall(r'class="ec-dd-sp"[^>]*>.*?</span>([^<]+)<span class="arr"', card)
    assert sports == list(LEAGUES)
    for sport, leagues in LEAGUES.items():
        ul = re.search(rf'<ul class="ec-dd-lg"[^>]*aria-label="Ligues — {sport}">(.*?)</ul>', card).group(1)
        assert re.findall(r"<li>(?:<a [^>]*>|<span [^>]*>)([^<]+)<", ul) == leagues
    for absent in ("Tennis", "MMA", "Golf", "NASCAR", "UFC"):
        assert absent not in h


def test_leagues_without_data_are_soon_and_not_links():
    _, h = nav()
    card = block(h, 'id="ec-dd-sports"', "</ul></div>")
    links = dict(re.findall(r'<a href="([^"]+)" target="_self">([^<]+)</a>', card))
    assert {v: k for k, v in links.items()} == {lg: f"aujourdhui?sport={sp}" for lg, sp in LIVE.items()}
    for leagues in LEAGUES.values():
        for lg in leagues:
            if lg not in LIVE:
                assert f'<span class="soon" aria-disabled="true">{lg}<small>Bientôt</small></span>' in card


def test_mega_menu_has_three_columns_and_only_real_pages_are_links():
    _, h = nav()
    mega = block(h, 'id="ec-dd-preuve"', "</nav>")
    assert re.findall(r'class="ec-dd-h">([^<]+)<', mega) == ["La preuve", "Comprendre", "Le site"]
    links = re.findall(r'<a href="([^"]+)" target="_self">([^<]+)</a>', mega)
    assert [t for _, t in links] == ["La preuve", "Classement des modèles", "Lexique", "Comment ça marche", "FAQ",
                                     "Accueil", "Aujourd'hui", "Ligues", "En direct", "La toile"]
    assert ("accueil#faq", "FAQ") in links
    assert ("lexique", "Lexique") in links
    for missing in ("Journal", "Équipe de la semaine"):  # pas de page dans l'app : « Bientôt », jamais un lien
        assert f'<span class="soon" aria-disabled="true">{missing}<small>Bientôt</small></span>' in mega
    for banned in ("Cotes", "Odds", "Picks", "Sportsbook", "Casino", "Calculat", "Parlay", "pari"):
        assert banned.lower() not in h.lower()


def test_cards_closed_by_default_and_escape_closes():
    """Le rendu par défaut est fermé (carte visible seulement via data-open) ; Échap ferme et rend le focus au bouton.
    Le comportement réel (survol, tap, Échap, clic ailleurs) est vérifié dans le navigateur."""
    at, h = nav()
    assert 'data-open=""' in h and h.count('aria-expanded="true"') == 0
    assert at.get("html")[0].proto.unsafe_allow_javascript
    assert "e.key === 'Escape') close(true)" in h and "if (back && b) b.focus()" in h
    css = "".join(m.value for m in at.markdown)
    assert '.ec-nav[data-open="sports"] #ec-dd-sports' in css and "visibility:hidden" in css
