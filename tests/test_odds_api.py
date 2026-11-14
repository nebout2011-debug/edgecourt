"""Adaptateur de cotes (The Odds API) : marge retirée, cache fichier, aucun appel au chargement d'une page,
instantanés horodatés (prévision / clôture) journalisés, EV seulement avec probabilité + cote, signaux, rapport marché."""
import json
import math
import shutil
from pathlib import Path

import pandas as pd
import pytest
import requests
import streamlit as st
from streamlit.testing.v1 import AppTest
from streamlit.util import calc_hash

from edgecourt import config
from edgecourt.data import odds_api
from edgecourt.paper.journal import Journal

ROOT = Path(__file__).resolve().parents[1]
APP = str(ROOT / "src" / "edgecourt" / "ui" / "app.py")
NOW = pd.Timestamp("2026-11-14 12:00", tz="UTC")


def event(home, away, start, books):
    return {"id": f"ev-{home}-{away}", "commence_time": start, "home_team": home, "away_team": away,
            "bookmakers": [{"key": f"b{i}", "markets": [{"key": "h2h", "outcomes": [{"name": home, "price": h}, {"name": away, "price": a}]}]}
                           for i, (h, a) in enumerate(books)]}


@pytest.fixture
def arts(tmp_path, monkeypatch):
    """Copie des vrais artefacts (prévisions réelles) dans un dossier temporaire : aucun fichier du dépôt n'est modifié."""
    shutil.copytree(ROOT / "artifacts" / "real", tmp_path / "real", ignore=shutil.ignore_patterns("odds_*", "journal.jsonl"))
    monkeypatch.setattr(config, "ARTIFACTS", tmp_path)
    st.cache_data.clear()
    yield tmp_path
    st.cache_data.clear()


def next_nfl(today):
    U = odds_api.upcoming_predictions("nfl", today=today)
    return U.sort_values(["game_date", "game_id"]).iloc[0]


def test_implied_removes_the_margin():
    imp = odds_api.implied({"home": 1.80, "away": 2.10})
    assert sum(imp.values()) == pytest.approx(1.0)
    assert imp["home"] == pytest.approx((1 / 1.8) / (1 / 1.8 + 1 / 2.1))
    assert sum(odds_api.implied({"home": 2.5, "draw": 3.2, "away": 3.0}).values()) == pytest.approx(1.0)


def test_consensus_is_the_median_over_books():
    odds, n = odds_api.consensus(event("A", "B", "2026-11-15T18:00:00Z", [(1.8, 2.0), (1.9, 2.1), (2.0, 1.9)]))
    assert n == 3 and odds == {"home": 1.9, "away": 2.0}


def test_ev_formula():
    assert odds_api.ev(0.55, 2.0) == pytest.approx(0.10)


def test_refresh_caches_snapshots_and_journal(arts):
    g = next_nfl(NOW.tz_convert(None).normalize())
    home, away = odds_api.api_name("nfl", g["home_team"]), odds_api.api_name("nfl", g["away_team"])
    start = (pd.Timestamp(g["game_date"]) + pd.Timedelta(hours=18)).tz_localize("UTC").isoformat()
    calls = []

    def fake(sp, key):
        calls.append(sp)
        return [event(home, away, start, [(1.8, 2.1), (1.85, 2.05)])], {"remaining": 499, "used": 1}

    rep = odds_api.refresh("k", now=NOW, fetcher=fake)
    assert calls == ["nfl"]  # NBA / Premier League : aucune prévision à venir, donc aucun crédit dépensé
    assert "pas d'appel" in rep["nba"] and "1 associés" in rep["nfl"]
    S = odds_api.load_snapshots()
    assert len(S) == 1 and S.loc[0, "game_id"] == str(g["game_id"]) and S.loc[0, "p_home"] == pytest.approx(g["p_home_final"])
    assert S.loc[0, "implied_home"] + S.loc[0, "implied_away"] == pytest.approx(1.0)
    rec = [r for r in Journal("real").read() if r["kind"] == "prediction_odds"]
    assert len(rec) == 1 and rec[0]["odds_home"] == pytest.approx(1.825) and rec[0]["fetched_at"] == NOW.isoformat()
    odds_api.refresh("k", now=NOW + pd.Timedelta(hours=1), fetcher=fake)  # dans l'intervalle minimal : pas d'appel
    assert calls == ["nfl"]
    odds_api.refresh("k", now=NOW + pd.Timedelta(hours=odds_api.MIN_HOURS), fetcher=fake)
    assert calls == ["nfl", "nfl"] and len(odds_api.load_snapshots()) == 2
    assert json.loads(odds_api.meta_path().read_text())["credits"]["remaining"] == 499


def test_refresh_stops_under_credit_floor(arts):
    odds_api.meta_path().write_text(json.dumps({"credits": {"remaining": odds_api.FLOOR - 1}}))
    rep = odds_api.refresh("k", now=NOW, fetcher=lambda *a: pytest.fail("aucun appel attendu"))
    assert "crédits" in rep["nfl"]


def test_network_error_never_leaks_the_key(monkeypatch):
    def boom(url, params=None, timeout=None):
        raise requests.ConnectionError(f"{url}?apiKey={params['apiKey']}")
    monkeypatch.setattr(odds_api.requests, "get", boom)
    with pytest.raises(odds_api.OddsError) as ex:
        odds_api.fetch("nfl", "SECRET-KEY-123")
    assert "SECRET-KEY-123" not in str(ex.value) and ex.value.__cause__ is None


def snaps(rows):
    S = pd.DataFrame(rows)
    for c in ("fetched_at", "commence_time"):
        S[c] = pd.to_datetime(S[c], utc=True)
    return S


def row(gid, fetched, odds_h, odds_a, p_h, start="2026-11-15T18:00:00Z"):
    imp = odds_api.implied({"home": odds_h, "away": odds_a})
    return {"sport": "nfl", "game_id": gid, "home_team": "H", "away_team": "A", "game_date": "2026-11-15", "commence_time": start,
            "fetched_at": fetched, "n_books": 2, "odds_home": odds_h, "odds_draw": None, "odds_away": odds_a,
            "implied_home": imp["home"], "implied_draw": None, "implied_away": imp["away"], "p_home": p_h, "p_draw": 0.0, "p_away": 1 - p_h}


def test_prediction_and_closing_snapshots_and_market_report():
    S = snaps([row("g1", "2026-11-14T12:00:00Z", 2.0, 1.9, 0.6), row("g1", "2026-11-15T17:00:00Z", 1.8, 2.1, 0.6),
               row("g1", "2026-11-15T19:00:00Z", 1.1, 8.0, 0.6)])  # après le coup d'envoi : ignoré
    now = pd.Timestamp("2026-11-16", tz="UTC")
    assert odds_api.at_prediction(S).loc[0, "odds_home"] == 2.0
    assert odds_api.closing(S, now).loc[0, "odds_home"] == 1.8
    rep = odds_api.market_report(S, pd.DataFrame([{"sport": "nfl", "game_id": "g1", "home_score": 24, "away_score": 17}]), now)
    m = odds_api.implied({"home": 2.0, "away": 1.9})["home"]
    assert rep["nfl"]["logloss_modele"] == pytest.approx(-math.log(0.6))
    assert rep["nfl"]["logloss_marche"] == pytest.approx(-math.log(m))
    assert rep["nfl"]["clv_moyen"] == pytest.approx(2.0 / 1.8 - 1)


def test_signals_rank_by_model_market_gap():
    S = snaps([row("g1", "2026-11-14T12:00:00Z", 1.9, 1.9, 0.52), row("g2", "2026-11-14T12:00:00Z", 1.9, 1.9, 0.70)])
    D = odds_api.signals(S, now=pd.Timestamp("2026-11-14T13:00:00Z"))
    assert list(D["game_id"]) == ["g2", "g1"] and D.loc[0, "gap"] == pytest.approx(0.20)


def today_page() -> AppTest:
    at = AppTest.from_file(APP, default_timeout=120)
    at._page_hash = calc_hash("aujourdhui")
    return at.run()


@pytest.mark.parametrize("page", ["entree", "accueil", "aujourdhui", "match", "preuve", "journal"])
def test_page_load_never_calls_the_api(page, monkeypatch):
    monkeypatch.setattr(requests, "get", lambda *a, **k: pytest.fail("appel réseau au chargement d'une page"))
    monkeypatch.setattr(odds_api, "fetch", lambda *a, **k: pytest.fail("appel à l'API de cotes au chargement d'une page"))
    at = AppTest.from_file(APP, default_timeout=120)
    at._page_hash = calc_hash(page)
    at.run()
    assert not at.exception


def test_ev_only_with_probability_and_odds(arts):
    today = pd.Timestamp.today().normalize()
    g = next_nfl(today)
    h = "".join(m.value for m in today_page().markdown)
    assert "EV =" not in h and "Aucune cote relevée" in h  # pas de cote : ni EV ni signal
    start = (pd.Timestamp(g["game_date"]) + pd.Timedelta(days=1)).tz_localize("UTC")
    fetched = pd.Timestamp.now(tz="UTC").floor("min")
    r = row(str(g["game_id"]), fetched.isoformat(), 1.7, 2.2, float(g["p_home_final"]), start.isoformat())
    r.update(home_team=g["home_team"], away_team=g["away_team"], game_date=str(pd.Timestamp(g["game_date"]).date()),
             p_draw=float(g["p_draw_final"]), p_away=float(g["p_away_final"]))
    odds_api.snapshots_path().write_text(json.dumps(r) + "\n", encoding="utf-8")
    st.cache_data.clear()
    at = today_page()
    assert not at.exception
    h = "".join(m.value for m in at.markdown)
    k = "home" if g["p_home_final"] >= g["p_away_final"] else "away"
    p, o = g[f"p_{k}_final"], r[f"odds_{k}"]
    assert f"EV = {p:.3f} × {o:.2f} − 1".replace(".", ",") in h  # la formule montre la probabilité et la cote
    assert f"{100 * p:.1f} %" in h and "pas un conseil de pari" in h
    assert any("Signaux" in m.value for m in at.markdown) and len(at.dataframe) >= 1
