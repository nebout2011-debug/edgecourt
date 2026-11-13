"""« Équipe de la semaine » (Ligues) : les 5 plus hauts Élo du moteur (K = ELO_MAIN) par ligue, forme V/N/D,
étiquette « Selon le modèle », message quand une ligue n'a pas d'Élo."""
import re
from pathlib import Path

import pandas as pd
import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest
from streamlit.util import calc_hash

from edgecourt import config
from edgecourt.data import store
from edgecourt.features.state import ELO_MAIN, SportState

ROOT = Path(__file__).resolve().parents[1]
APP = str(ROOT / "src" / "edgecourt" / "ui" / "app.py")
LEAGUES = {"nfl": "NFL", "nba": "NBA", "soccer": "Premier League"}
ROW = re.compile(r'class="rk">(\d)</span><span>.*?>([^<]+)</a></span><span class="elo">(\d+)</span><span class="fm">(.*?)</span></div>')


def ligues() -> AppTest:
    at = AppTest.from_file(APP, default_timeout=120)
    at._page_hash = calc_hash("ligues")
    return at.run()


def blocks(h: str) -> dict[str, str]:
    """Bloc HTML de chaque ligue (entre son en-tête et le suivant)."""
    parts = re.split(r'<div class="ec-totw-h">', h)[1:]
    return {next(sp for sp, name in LEAGUES.items() if p.startswith(name + "<")): p for p in parts}


def engine_games(sp: str) -> pd.DataFrame:
    s = store.Store("real")
    try:
        return s.games(sp)
    finally:
        s.close()


def replay(G: pd.DataFrame, sp: str, before=None) -> SportState:
    F = G[G["status"] == "final"].sort_values(["game_date", "game_id"])
    if before is not None:
        F = F[F["game_date"] < before]
    state = SportState(sp)
    for r in F.itertuples(index=False):
        state.update(r)
    return state


@pytest.mark.parametrize("sp", list(LEAGUES))
def test_replay_is_the_engines_elo(sp):
    """Le rejeu redonne exactement l'Élo d'avant-match que le moteur a enregistré (elo_h / elo_a) à sa dernière date."""
    P = pd.read_parquet(config.ARTIFACTS / "real" / f"predictions_{sp}.parquet")
    last = P[P["status"] == "final"]["game_date"].max()
    state = replay(engine_games(sp), sp, before=last)
    for r in P[P["game_date"] == last].itertuples():
        assert state._elo(ELO_MAIN, r.home_team, str(r.season)) == pytest.approx(r.elo_h)
        assert state._elo(ELO_MAIN, r.away_team, str(r.season)) == pytest.approx(r.elo_a)


def test_top5_are_the_highest_engine_elo_with_form():
    at = ligues()
    assert not at.exception
    h = "".join(m.value for m in at.markdown)
    assert "Équipe de la semaine" in h and "Selon le modèle" in h
    for sp, block in blocks(h).items():
        G = engine_games(sp)
        elo = replay(G, sp).elo[ELO_MAIN]
        expected = sorted(elo.items(), key=lambda kv: (-kv[1], kv[0]))[:5]
        rows = ROW.findall(block)
        assert [(t, int(e)) for _, t, e, _ in rows] == [(t, int(f"{v:.0f}")) for t, v in expected]
        for _, team, _, form in rows:  # forme : 5 derniers matchs terminés, recalculés ici
            F = G[(G["status"] == "final") & ((G["home_team"] == team) | (G["away_team"] == team))]
            F = F.sort_values(["game_date", "game_id"]).tail(5).iloc[::-1]
            want = ["V" if m > o else "N" if m == o else "D" for m, o in
                    ((r.home_score, r.away_score) if r.home_team == team else (r.away_score, r.home_score) for r in F.itertuples())]
            assert re.findall(r'class="ec-wdl ([VND])"', form) == want


@pytest.fixture
def empty_db(tmp_path, monkeypatch):
    """Base de matchs vide (aucune ligue n'a d'Élo) ; les artefacts restent les vrais."""
    st.cache_data.clear()
    monkeypatch.setattr(config, "PROCESSED", tmp_path)
    yield
    st.cache_data.clear()


def test_league_without_elo_shows_message(empty_db):
    at = ligues()
    assert not at.exception
    h = "".join(m.value for m in at.markdown)
    assert h.count("Pas encore d&#x27;Élo pour cette ligue") + h.count("Pas encore d'Élo pour cette ligue") == 3
    assert not ROW.findall(h)
