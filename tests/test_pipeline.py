"""Parcours complet : import -> validation -> entraînement -> évaluation -> cotes fixtures -> simulation -> journal."""
from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pytest

from edgecourt import config, pipeline
from edgecourt.data import odds as oddsmod, store as st, synthetic
from edgecourt.paper.journal import Journal


@pytest.fixture()
def tmp_env(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "RAW", tmp_path / "raw")
    monkeypatch.setattr(config, "PROCESSED", tmp_path / "processed")
    monkeypatch.setattr(config, "ARTIFACTS", tmp_path / "artifacts")
    return tmp_path


def _load_demo(sport: str, with_odds: bool = True, scheduled_tail: int = 0):
    games, truth = synthetic.make_games(sport)
    if scheduled_tail:
        games = games.astype({"home_score": float, "away_score": float})
        games.loc[games.index[-scheduled_tail:], ["home_score", "away_score"]] = np.nan
        games.loc[games.index[-scheduled_tail:], "status"] = "scheduled"
    s = st.Store("demo")
    s.import_games(games, sport, "synthetic", "synthetic", "0" * 64, "DÉMONSTRATION SYNTHÉTIQUE")
    if with_odds:
        good, _ = oddsmod.validate_odds(synthetic.make_fixture_odds(sport, games, truth), s.games(sport), sport, "synthetic")
        s.import_odds(good, "fx", is_fixture=True)
    s.close()


def test_full_course_soccer_demo(tmp_env):
    _load_demo("soccer")
    rep = pipeline.run_sport("demo", "soccer")
    assert rep["etiquette"].startswith("DÉMONSTRATION SYNTHÉTIQUE")
    assert rep["cotes"]["fixtures"] and rep["cotes"]["refusees_posterieures_au_cutoff"] > 0   # cotes tardives refusées
    assert rep["journal"]["chaine_valide"] and rep["journal"]["ecrit"] > 0
    assert "Cotes FIXTURES" in rep["simulation"]["note"]
    # pas de fuite de sélection : le modèle est choisi sur la validation, le test n'est que rapporté
    assert rep["modele_vainqueur_selectionne_sur_validation"] in {"baseline", "elo10", "elo20", "elo40", "poisson"}
    p = pd.read_parquet(config.origin_dir("demo") / "predictions_soccer.parquet")
    assert np.allclose(p[["p_home_final", "p_draw_final", "p_away_final"]].sum(axis=1), 1.0)
    sim = pd.read_parquet(config.origin_dir("demo") / "simulation_soccer.parquet")
    assert {"win", "loss", "push"} <= set(sim["outcome"].dropna())                          # remboursements inclus (ligne 2.0)
    bets = sim[sim["decision"] == "simuler"]
    assert (bets.groupby(["game_id", "bookmaker", "market"]).size() >= 1).all()
    assert sim.loc[sim["decision"] == "abstention", "raison_abstention"].str.len().gt(0).all()
    # profit cohérent avec les règlements
    chk = np.where(bets["outcome"] == "win", bets["odds"] - 1, np.where(bets["outcome"] == "loss", -1.0, 0.0))
    assert np.allclose(bets["profit"], chk)
    # rejouer le parcours n'ajoute rien (journal persistant et idempotent)
    assert pipeline.run_sport("demo", "soccer")["journal"]["ecrit"] == 0
    recs = Journal("demo").read()
    kinds = {r["kind"] for r in recs}
    assert {"config", "prediction", "result", "settlement"} <= kinds
    assert {r["mode"] for r in recs if r["kind"] == "prediction"} == {"backtest"}
    pred = next(r for r in recs if r["kind"] == "prediction" and r["cote_admissible"])
    for k in ("game_id", "sport", "market", "line", "created_at", "cutoff", "config_hash", "data_fp", "probabilities",
              "cote_admissible", "decision", "raison_abstention"):
        assert k in pred
    # séparation démo / réel
    assert st.Store("real").games("soccer").empty
    assert not list((config.ARTIFACTS / "real").glob("*")) if (config.ARTIFACTS / "real").exists() else True


def test_prospective_forecasts_are_marked_and_never_use_results(tmp_env):
    _load_demo("nfl", with_odds=False, scheduled_tail=8)
    rep = pipeline.run_sport("demo", "nfl")
    assert rep["effectifs"]["a_venir"] == 8
    assert "rendement non évaluable" in rep["reference_marche"]["statut"]
    assert rep["simulation"]["test"]["statut"] == "rendement non évaluable"                 # sans cotes : pas d'EV/ROI
    recs = Journal("demo").read()
    pro = [r for r in recs if r["kind"] == "prediction" and r["mode"] == "prospective"]
    assert len(pro) == 16 and all(r["decision"] == "abstention" and "aucune cote" in r["raison_abstention"] for r in pro)
    scheduled_ids = {r["game_id"] for r in pro}
    assert not any(r["kind"] == "result" and r["game_id"] in scheduled_ids for r in recs)   # aucun résultat inventé


def test_insufficient_or_blocked_source_does_not_stop_others(tmp_env):
    rep = pipeline.run_sport("real", "nba")                                                  # aucune donnée (clé absente)
    assert rep["statut"] == "données insuffisantes"
    _load_demo("nfl", with_odds=False)
    assert "vainqueur" in pipeline.run_sport("demo", "nfl")


def test_refit_creates_new_version_without_touching_backtest(tmp_env):
    _load_demo("nfl", with_odds=False, scheduled_tail=8)
    pipeline.run_sport("demo", "nfl")
    d = config.origin_dir("demo")
    before = {f: (d / f).read_bytes() for f in ("report_nfl.json", "predictions_nfl.parquet", "split_nfl.json", "journal.jsonl")}
    rep = pipeline.refit_upcoming("demo", "nfl")
    # backtest et journal existants : octets identiques (le journal n'est qu'étendu)
    for f in ("report_nfl.json", "predictions_nfl.parquet", "split_nfl.json"):
        assert (d / f).read_bytes() == before[f]
    assert (d / "journal.jsonl").read_bytes().startswith(before["journal.jsonl"])
    # chronologie : entraînement < calibration <= date limite = dernier résultat terminé connu
    s = Store_games("demo")
    cutoff = s[s["status"] == "final"]["game_date"].max()
    assert rep["date_limite_donnees"] == str(cutoff.date()) and rep["split"]["calib_end"] == str(cutoff.date())
    assert pd.Timestamp(rep["split"]["train_end"]) < cutoff
    assert rep["version"].startswith("refit-") and rep["a_venir"] == 8
    up = pd.read_parquet(d / next(f.name for f in d.glob("predictions_nfl_upcoming_*.parquet")))
    assert len(up) == 8 and (up["status"] == "scheduled").all() and up["home_score"].isna().all()
    new = [r for r in Journal("demo").read() if r.get("version") == rep["version"]]
    assert len(new) == 16 and {r["mode"] for r in new} == {"prospective"}
    old_ids = {r["id"] for r in map(json.loads, before["journal.jsonl"].decode().splitlines())}
    assert not ({r["id"] for r in new} & old_ids)                                       # nouvelle version identifiable
    assert pipeline.refit_upcoming("demo", "nfl")["journal"]["ecrit"] == 0              # idempotent


def Store_games(origin):
    s = st.Store(origin)
    try:
        return s.games("nfl")
    finally:
        s.close()
