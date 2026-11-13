"""Colonne News d'Aujourd'hui : flux injoignable → message, articles avec source + heure, filtre par ligue."""
import urllib.error
from pathlib import Path

import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest
from streamlit.util import calc_hash

from edgecourt.ui import news

APP = str(Path(__file__).resolve().parents[1] / "src" / "edgecourt" / "ui" / "app.py")
NOW = 1_794_571_200  # 2026-11-13 12:00 UTC
RSS = b"""<?xml version="1.0"?><rss version="2.0" xmlns:media="http://search.yahoo.com/mrss/"><channel><title>t</title>
<item><title>Arsenal <b>win</b> again</title><link>https://www.bbc.co.uk/sport/football/1</link>
  <pubDate>Fri, 13 Nov 2026 10:00:00 GMT</pubDate><media:thumbnail url="https://ichef.bbci.co.uk/a.jpg" width="240" height="135"/></item>
<item><title>Best bets for the weekend</title><link>https://www.bbc.co.uk/sport/football/2</link><pubDate>Fri, 13 Nov 2026 10:00:00 GMT</pubDate></item>
<item><title>Story without a date</title><link>https://www.bbc.co.uk/sport/football/3</link></item>
<item><title>Bad link</title><link>javascript:alert(1)</link><pubDate>Fri, 13 Nov 2026 10:00:00 GMT</pubDate></item>
</channel></rss>"""


def test_parse_keeps_source_time_and_feed_image_only():
    items = news.parse(RSS, "BBC Sport", "Premier League")
    assert len(items) == 1  # pari, sans date et lien non https : écartés, jamais complétés
    i = items[0]
    assert (i["source"], i["league"], i["image"]) == ("BBC Sport", "Premier League", "https://ichef.bbci.co.uk/a.jpg")
    assert news.meta(i, NOW) == "BBC Sport · Premier League · il y a 2 h"
    assert news.ago(NOW - 90, NOW) == "il y a 1 min" and news.ago(NOW - 3 * 86400, NOW) == "il y a 3 j"


def test_html_escapes_feed_text():
    i = {"title": "<script>x</script>", "link": "https://a.b/c", "source": "ESPN", "league": "NBA", "ts": NOW, "image": None}
    for h in (news.list_html([i], NOW), news.featured_html([i], NOW)):
        assert "<script>x" not in h and "&lt;script&gt;" in h and 'target="_blank"' in h


def fake(league: str, n: int) -> list[dict]:
    return [{"title": f"{league} story {k}", "link": f"https://www.espn.com/{league}/{k}", "source": "ESPN",
             "league": league, "ts": NOW - k * 600, "image": None} for k in range(n)]


@pytest.fixture(autouse=True)
def fresh_cache():
    st.cache_data.clear()  # le flux est mis en cache 15 min : chaque test part d'un cache vide
    yield
    st.cache_data.clear()


def today() -> AppTest:
    at = AppTest.from_file(APP, default_timeout=120)
    at._page_hash = calc_hash("aujourdhui")
    return at.run()


def page(at: AppTest) -> str:
    return "".join(m.value for m in at.markdown) + "".join(f.proto.srcdoc for f in at.get("iframe"))


def test_unreachable_feeds_show_fallback(monkeypatch):
    def down(url, timeout=6):
        raise urllib.error.URLError("hors ligne")
    monkeypatch.setattr(news, "fetch", down)
    at = today()
    assert not at.exception
    assert news.UNAVAILABLE in page(at) and '<ul class="ec-news-list">' not in page(at) and not at.get("iframe")


def test_items_carry_source_and_time_and_filter_works(monkeypatch):
    monkeypatch.setattr(news, "load", lambda: fake("NBA", 7) + fake("NFL", 7))
    at = today()
    assert not at.exception
    h = page(at)
    assert "NBA story 0" in h and "NFL story 0" in h and "ESPN · NBA · il y a" in h
    at.pills[0].set_value("NFL").run()
    h = page(at)
    assert "NFL story 6" in h and "NBA story" not in h and news.UNAVAILABLE not in h
    at.pills[0].set_value("Ligue 1").run()
    assert news.UNAVAILABLE in page(at)  # aucune actualité pour cette ligue : rien d'inventé
