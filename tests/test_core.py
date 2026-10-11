"""Tests unitaires : règlement, marchés, validation/import, cotes, journal, absence de fuite temporelle."""
from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pytest

from edgecourt import config
from edgecourt.data import connectors, odds as oddsmod, store as st, synthetic
from edgecourt.models.engine import walk_forward, winner_models
from edgecourt.models.markets import (dist_from_params, ev_per_unit, selection_probs, spread_probs, total_probs)
from edgecourt.paper.journal import Journal
from edgecourt.paper.settlement import profit_units, settle
from edgecourt.paper.simulate import summarize


@pytest.fixture()
def tmp_env(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "RAW", tmp_path / "raw")
    monkeypatch.setattr(config, "PROCESSED", tmp_path / "processed")
    monkeypatch.setattr(config, "ARTIFACTS", tmp_path / "artifacts")
    return tmp_path


# ------------------------------------------------------------------ règlement
def test_settlement_pushes_and_ties():
    assert settle("moneyline", "home", None, "tie_refund", 20, 20) == "push"   # nul NFL remboursé
    assert settle("moneyline", "home", None, "tie_loss", 20, 20) == "loss"
    assert settle("moneyline", "away", None, "standard", 10, 17) == "win"
    assert settle("1x2", "draw", None, "standard", 1, 1) == "win"
    assert settle("1x2", "home", None, "standard", 1, 1) == "loss"
    assert settle("total", "over", 2.0, "standard", 1, 1) == "push"             # ligne entière
    assert settle("total", "under", 2.5, "standard", 1, 1) == "win"
    assert settle("spread", "home", -3.0, "standard", 24, 21) == "push"
    assert settle("spread", "away", 3.5, "standard", 24, 21) == "win"
    assert profit_units("win", 2.5) == 1.5 and profit_units("loss", 2.5) == -1.0 and profit_units("push", 2.5) == 0.0


def test_ev_counts_refunds_as_zero():
    d = dist_from_params({"kind": "normal", "mu_m": 0, "sd_m": 10, "mu_t": 44, "sd_t": 13})
    pw, pp, pl = total_probs(d, 44.0)
    assert pp > 0 and abs(pw + pp + pl - 1) < 1e-9
    assert ev_per_unit(pw, pl, 2.0) == pytest.approx(pw * 1.0 - pl)


# ------------------------------------------------------------------ probabilités
@pytest.mark.parametrize("params", [
    {"kind": "normal", "mu_m": 3.0, "sd_m": 12.0, "mu_t": 220.0, "sd_t": 18.0},
    {"kind": "poisson", "lh": 1.6, "la": 1.1},
])
def test_distributions_sum_to_one(params):
    d = dist_from_params(params)
    assert d.mp.sum() == pytest.approx(1) and d.tp.sum() == pytest.approx(1)
    assert sum(d.one_x_two()) == pytest.approx(1)
    for line in (1.5, 2.0, 2.5):
        assert sum(total_probs(d, line)) == pytest.approx(1)
        assert sum(spread_probs(d, line)) == pytest.approx(1)
    with pytest.raises(ValueError):
        total_probs(d, 2.25)  # quart de point refusé


def test_spread_selection_symmetry():
    d = dist_from_params({"kind": "normal", "mu_m": 4.0, "sd_m": 12.0, "mu_t": 220.0, "sd_t": 18.0})
    w = (0.6, 0.0, 0.4)
    h = selection_probs("spread", "home", -4.0, d, w, "standard")
    a = selection_probs("spread", "away", 4.0, d, w, "standard")
    assert h[0] == pytest.approx(a[2]) and h[1] == pytest.approx(a[1]) and h[2] == pytest.approx(a[0])
    ml = selection_probs("moneyline", "home", None, d, (0.5, 0.02, 0.48), "tie_refund")
    assert ml == pytest.approx((0.5, 0.02, 0.48))


# ------------------------------------------------------------------ import
def _games(n=5):
    return pd.DataFrame({
        "game_id": [f"g{i}" for i in range(n)], "season": "2099", "game_date": pd.date_range("2099-10-01", periods=n),
        "home_team": [f"H{i}" for i in range(n)], "away_team": [f"A{i}" for i in range(n)],
        "home_score": [100 + i for i in range(n)], "away_score": [90] * n, "status": "final"})


def test_validation_rejects_bad_rows():
    g = _games(6)
    g.loc[0, "home_score"] = -3                      # score négatif
    g.loc[1, "home_score"] = np.nan                  # final sans score
    g.loc[2, "game_id"] = "g3"                       # doublon d'id
    g.loc[4, "away_team"] = g.loc[4, "home_team"]    # mêmes équipes
    good, bad = st.validate_games(g.assign(sport="nba", source="t"))
    reasons = set(bad["reason"])
    assert {"score négatif", "score incomplet", "équipes invalides"} <= reasons
    assert any("doublon" in r for r in reasons)
    assert len(good) == 6 - len(bad)


def test_import_is_idempotent_and_keeps_raw(tmp_env):
    s = st.Store("real")
    g = _games()
    p, digest = st.save_raw("t", "g.csv", g.to_csv(index=False).encode())
    r1 = s.import_games(g, "nba", "t", str(p), digest, "test")
    r2 = s.import_games(g, "nba", "t", str(p), digest, "test")
    assert (r1["inserted"], r2["inserted"], r2["updated"], r2["unchanged"]) == (5, 0, 0, 5)
    assert len(s.games("nba")) == 5 and p.exists()
    st.save_raw("t", "g.csv", b"autre")  # un second brut ne remplace jamais le premier
    assert p.exists()
    g2 = g.copy(); g2.loc[0, "home_score"] = 120    # un résultat corrigé = mise à jour, pas doublon
    r3 = s.import_games(g2, "nba", "t", str(p), digest, "test")
    assert r3["updated"] == 1 and len(s.games("nba")) == 5
    s.close()


def test_demo_and_real_are_physically_separate(tmp_env):
    games, _ = synthetic.make_games("nfl")
    d = st.Store("demo")
    d.import_games(games.head(50), "nfl", "synthetic", "x", "0" * 64, "demo")
    d.close()
    r = st.Store("real")
    assert r.games("nfl").empty and r.imports().empty
    assert config.db_path("demo") != config.db_path("real")
    assert all(t.startswith("DEMO") for t in games["home_team"])
    r.close()


def test_balldontlie_parsing_fixture():
    page = {"data": [
        {"id": 1, "date": "2024-10-22T00:00:00.000Z", "season": 2024, "status": "Final", "postseason": False,
         "home_team": {"full_name": "Boston Celtics"}, "visitor_team": {"full_name": "New York Knicks"},
         "home_team_score": 132, "visitor_team_score": 109},
        {"id": 2, "date": "2099-01-01", "season": 2098, "status": "7:00 PM ET", "postseason": False,
         "home_team": {"full_name": "A"}, "visitor_team": {"full_name": "B"}, "home_team_score": 0, "visitor_team_score": 0}]}
    df = connectors.parse_balldontlie([page])
    assert list(df["status"]) == ["final", "scheduled"] and pd.isna(df.loc[1, "home_score"])
    good, bad = st.validate_games(df.assign(sport="nba", source="balldontlie"))
    assert len(good) == 2 and bad.empty


def test_blocked_without_key(monkeypatch):
    monkeypatch.delenv("BALLDONTLIE_API_KEY", raising=False)
    monkeypatch.setattr(connectors, "_dotenv", lambda name: None)
    with pytest.raises(connectors.Blocked):
        connectors.fetch_balldontlie([2024])


# ------------------------------------------------------------------ cotes
def _odds_rows(game_id, when, o_home=1.9, o_away=1.95):
    return [
        dict(event_id=game_id, bookmaker="B", market="moneyline", selection="home", line=np.nan, odds_decimal=o_home, observed_at=when, settlement_rule="standard"),
        dict(event_id=game_id, bookmaker="B", market="moneyline", selection="away", line=np.nan, odds_decimal=o_away, observed_at=when, settlement_rule="standard"),
    ]


def test_odds_validation_and_future_refusal():
    g = _games(2)
    good_when, late = "2099-09-30T18:00:00Z", "2099-10-01T03:00:00Z"
    rows = _odds_rows("g0", good_when) + _odds_rows("g0", late, 2.5, 1.6)
    rows += [dict(event_id="g1", bookmaker="B", market="moneyline", selection="home", line=np.nan, odds_decimal=1.0, observed_at=good_when, settlement_rule="standard"),   # cote <= 1
             dict(event_id="zz", bookmaker="B", market="moneyline", selection="home", line=np.nan, odds_decimal=2.0, observed_at=good_when, settlement_rule="standard"),  # événement inconnu
             dict(event_id="g1", bookmaker="B", market="total", selection="over", line=np.nan, odds_decimal=1.9, observed_at=good_when, settlement_rule="standard")]       # ligne manquante
    good, bad = oddsmod.validate_odds(pd.DataFrame(rows), g, "nba", "t")
    assert len(bad) == 3 and len(good) == 4
    adm, refused = oddsmod.admissible(good, dict(zip(g["game_id"], g["game_date"])))
    assert refused == 2                                    # la cote tardive est refusée, jamais utilisée
    assert set(adm["observed_at"]) == {pd.Timestamp("2099-09-30T18:00:00")}
    assert adm.groupby("selection")["fair"].sum().sum() == pytest.approx(1.0)  # retrait de marge : somme = 1


def test_ambiguous_join_and_incomplete_group_excluded():
    g = _games(1)
    when = "2099-09-30T18:00:00Z"
    amb = _odds_rows("g0", when) + [dict(_odds_rows("g0", when)[0], odds_decimal=2.2)]    # même clé, cotes différentes
    good, bad = oddsmod.validate_odds(pd.DataFrame(amb), g, "nba", "t")
    assert (bad["reason"].str.contains("ambiguë")).sum() == 2 and len(good) == 1
    adm, _ = oddsmod.admissible(good, dict(zip(g["game_id"], g["game_date"])))
    assert adm.empty                                                                    # groupe incomplet : pas de référence


def test_spread_line_mismatch_has_no_market_reference():
    g = _games(1)
    when = "2099-09-30T18:00:00Z"
    rows = [dict(event_id="g0", bookmaker="B", market="spread", selection="home", line=-3.5, odds_decimal=1.9, observed_at=when, settlement_rule="standard"),
            dict(event_id="g0", bookmaker="B", market="spread", selection="away", line=3.5, odds_decimal=1.9, observed_at=when, settlement_rule="standard")]
    good, _ = oddsmod.validate_odds(pd.DataFrame(rows), g, "nba", "t")
    assert len(oddsmod.admissible(good, dict(zip(g["game_id"], g["game_date"])))[0]) == 2
    rows[1]["line"] = 4.5                                                               # lignes incompatibles
    good, _ = oddsmod.validate_odds(pd.DataFrame(rows), g, "nba", "t")
    assert oddsmod.admissible(good, dict(zip(g["game_id"], g["game_date"])))[0].empty


def test_no_odds_means_not_evaluable():
    assert summarize(pd.DataFrame())["statut"] == "rendement non évaluable"


# ------------------------------------------------------------------ journal
def test_journal_append_only_persistent_and_tamper_evident(tmp_env):
    j = Journal("demo")
    recs = [{"id": f"r{i}", "kind": "prediction", "mode": "backtest", "p": i} for i in range(3)]
    assert j.append_many(recs) == 3 and j.append_many(recs) == 0     # idempotent
    j2 = Journal("demo")                                             # persistance entre instances
    assert len(j2.read()) == 3 and j2.verify()
    j2.append_many([{"id": "r9", "kind": "result"}])
    assert len(Journal("demo").read()) == 4
    lines = j.path.read_text(encoding="utf-8").splitlines()
    rec = json.loads(lines[1]); rec["p"] = 999                       # altération détectée
    lines[1] = json.dumps(rec)
    j.path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    assert not Journal("demo").verify()


# ------------------------------------------------------------------ temporalité
@pytest.fixture(scope="module")
def nfl_small():
    g, _ = synthetic.make_games("nfl")
    return g[g["season"].isin(["DEMO 2001", "DEMO 2002"])].reset_index(drop=True)


PCOLS = lambda df: [c for c in df.columns if c.startswith(("w_", "dp_"))]  # noqa: E731


def test_probabilities_sum_to_one_for_every_model(nfl_small):
    te = nfl_small["game_date"].iloc[len(nfl_small) // 2]
    preds, _ = walk_forward(nfl_small, "nfl", te)
    for m in winner_models("nfl"):
        s = preds[[f"w_{m}_h", f"w_{m}_d", f"w_{m}_a"]]
        assert (s >= -1e-12).all().all() and np.allclose(s.sum(axis=1), 1.0)


def test_future_results_do_not_change_past_forecast(nfl_small):
    """Prévision passée invariante : on ajoute des résultats futurs (ou on les retire) sans changer les probabilités."""
    g = nfl_small
    te = g["game_date"].iloc[len(g) // 2]
    cut = g["game_date"].iloc[int(len(g) * 0.75)]
    full, _ = walk_forward(g, "nfl", te)
    part, _ = walk_forward(g[g["game_date"] <= cut], "nfl", te)
    a = full[full["game_date"] <= cut].reset_index(drop=True)
    pd.testing.assert_frame_equal(a[PCOLS(a)], part[PCOLS(part)].reset_index(drop=True), check_exact=False, rtol=1e-9)


def test_no_leak_from_own_score_or_same_day(nfl_small):
    g = nfl_small.copy()
    te = g["game_date"].iloc[len(g) // 2]
    base, _ = walk_forward(g, "nfl", te)
    idx = g.index[g["game_date"] > te][5]
    row = g.loc[idx]
    mod = g.copy()
    mod.loc[idx, ["home_score", "away_score"]] = [0, 70]                       # on trafique son propre score
    other = g.index[(g["game_date"] == row["game_date"]) & (g.index != idx)][0]
    mod.loc[other, ["home_score", "away_score"]] = [70, 0]                     # et celui d'un match du même jour
    alt, _ = walk_forward(mod, "nfl", te)
    mine = lambda df: df[df["game_id"] == row["game_id"]][PCOLS(df)].reset_index(drop=True)  # noqa: E731
    pd.testing.assert_frame_equal(mine(base), mine(alt))                       # inchangée
    later = base[base["game_date"] > row["game_date"]]
    later_alt = alt[alt["game_date"] > row["game_date"]]
    assert not np.allclose(later["w_elo20_h"], later_alt["w_elo20_h"])         # les matchs POSTÉRIEURS, eux, changent


def test_scheduled_games_get_forecast_without_updating_state(nfl_small):
    g = nfl_small.copy()
    g[["home_score", "away_score"]] = g[["home_score", "away_score"]].astype(float)
    last = g.index[-1]
    g.loc[last, ["home_score", "away_score", "status"]] = [np.nan, np.nan, "scheduled"]
    preds, _ = walk_forward(g, "nfl", g["game_date"].iloc[len(g) // 2])
    r = preds[preds["game_id"] == g.loc[last, "game_id"]].iloc[0]
    assert r["status"] == "scheduled" and np.isnan(r["home_score"]) and abs(r["w_elo20_h"] + r["w_elo20_d"] + r["w_elo20_a"] - 1) < 1e-9
