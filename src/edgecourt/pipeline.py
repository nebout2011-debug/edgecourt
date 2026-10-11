"""Orchestration : données -> découpage -> prévisions -> évaluation -> cotes -> simulation -> journal."""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from . import config
from .data import connectors, odds as oddsmod, store as st, synthetic
from .evaluation.backtest import evaluate, make_split
from .models.engine import walk_forward
from .models.markets import dist_from_params, selection_probs
from .paper.journal import Journal, config_hash, make_id
from .paper.simulate import simulate, summarize

DEFAULT_SOURCE = {"nfl": "nflverse", "soccer": "statsbomb", "nba": "balldontlie"}
MIN_FINALS = 60


def _status_path(origin: str):
    return config.origin_dir(origin) / "connector_status.json"


def _set_status(origin: str, key: str, value: dict) -> None:
    p = _status_path(origin)
    cur = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
    cur[key] = value
    p.write_text(json.dumps(cur, indent=2, ensure_ascii=False), encoding="utf-8")


def fetch_real(sports: list[str]) -> dict:
    out = {}
    s = st.Store("real")
    try:
        for sport in sports:
            try:
                if sport == "nfl":
                    df, path, digest, cov = connectors.fetch_nfl()
                elif sport == "soccer":
                    df, path, digest, cov = connectors.fetch_statsbomb()
                else:
                    df, path, digest, cov = connectors.fetch_balldontlie(list(config.NBA_SEASONS))
                res = s.import_games(df, sport, DEFAULT_SOURCE[sport], str(path), digest, cov)
                out[sport] = {"statut": "ok", **res, "couverture": cov}
            except connectors.Blocked as e:
                out[sport] = {"statut": "bloqué", "besoin_utilisateur": str(e)}
            except Exception as e:  # réseau, format... : statut explicite, le reste continue
                out[sport] = {"statut": "erreur", "detail": f"{type(e).__name__}: {e}"}
            _set_status("real", sport, {**out[sport], "at": st.now_utc().isoformat(timespec="seconds")})
    finally:
        s.close()
    return out


def import_games_csv(origin: str, sport: str, path: str) -> dict:
    df, raw, digest, cov = connectors.read_games_csv(path, sport)
    s = st.Store(origin)
    try:
        return s.import_games(df, sport, "csv", str(raw), digest, cov)
    finally:
        s.close()


def import_odds_csv(origin: str, sport: str, path: str, source: str | None = None, fixture: bool = False) -> dict:
    s = st.Store(origin)
    try:
        games = s.games(sport)
        src = source or (games["source"].iloc[0] if len(games) else DEFAULT_SOURCE[sport])
        raw = pd.read_csv(path, encoding="utf-8-sig")
        good, bad = oddsmod.validate_odds(raw, games, sport, src)
        raw_path, digest = st.save_raw("odds", Path(path).name, Path(path).read_bytes())
        n = s.import_odds(good, f"odds-{digest[:10]}", is_fixture=fixture)
        return {"lues": len(raw), "valides": len(good), "inserees": n, "rejetees": len(bad),
                "motifs": bad["reason"].value_counts().to_dict() if len(bad) else {}}
    finally:
        s.close()


def build_demo() -> dict:
    """Génère les trois jeux synthétiques + cotes fixtures dans la base « demo » (jamais « real »)."""
    s = st.Store("demo")
    res = {}
    try:
        for sport in config.SPORTS:
            games, truth = synthetic.make_games(sport)
            digest = st.sha256_bytes(games.to_csv(index=False).encode())
            res[sport] = s.import_games(games, sport, "synthetic", "synthetic:seed11", digest,
                                        "DÉMONSTRATION SYNTHÉTIQUE - aucune valeur sportive")
            fx = synthetic.make_fixture_odds(sport, games, truth)
            g = s.games(sport)
            good, bad = oddsmod.validate_odds(fx, g, sport, "synthetic")
            res[sport]["cotes_fixtures"] = s.import_odds(good, f"fixture-{sport}", is_fixture=True)
    finally:
        s.close()
    return res


def _entries(sport: str, origin: str, ann: pd.DataFrame, sim: pd.DataFrame, cfg: dict, cfg_h: str, ref_line: float,
             version: str | None = None):
    recs = [{"kind": "config", "id": make_id("config", cfg_h), "config_hash": cfg_h, "config": cfg}]
    now = st.now_utc().isoformat(timespec="seconds")
    wm = "1x2" if sport == "soccer" else "moneyline"
    simg = {}
    if len(sim):
        for (gid, mk, ln), grp in sim.assign(_ln=sim["line"].abs().fillna(-1.0)).groupby(["game_id", "market", "_ln"]):
            simg[(gid, mk, ln)] = grp
    seen = set()
    ann_by = {r["game_id"]: r for r in ann.to_dict("records")}
    for r in ann.itertuples(index=False):
        mode = "prospective" if r.status != "final" else "backtest"
        cutoff = oddsmod.cutoff_for(r.game_date).isoformat()
        base = {"kind": "prediction", "mode": mode, "origine": origin, "sport": sport, "game_id": r.game_id,
                "event": f"{r.home_team} - {r.away_team}", "game_date": str(r.game_date.date()), "created_at": now,
                "cutoff": cutoff, "config_hash": cfg_h, "data_fp": r.data_fp,
                "demo": origin == "demo", **({"version": version} if version else {})}
        d = dist_from_params(json.loads(r.dp_model if r.total_dist_selected == "model" else r.dp_base))
        winner = (r.p_home_final, r.p_draw_final, r.p_away_final)
        pt = selection_probs("total", "over", ref_line, d, winner, "standard")
        specs = [(wm, None, {"home": winner[0], "draw": winner[1], "away": winner[2]}),
                 ("total", ref_line, {"over": pt[0], "push": pt[1], "under": pt[2]})]
        for market, line, probs in specs:
            key = (r.game_id, market, -1.0 if line is None else abs(line))
            grp = simg.get(key)
            seen.add(key)
            cote, decision, reason, fp = None, "abstention", "aucune cote valide à l'instant de la prévision", "none"
            if grp is not None:
                top = grp.loc[grp["ev"].idxmax()]
                cote = {k: (str(top[k]) if k == "observed_at" else top[k]) for k in ("bookmaker", "selection", "odds", "observed_at", "ev")}
                decision = "simuler" if (grp["decision"] == "simuler").any() else "abstention"
                reason = "" if decision == "simuler" else str(top["raison_abstention"])
                fp = make_id(*grp[["bookmaker", "selection", "odds", "observed_at"]].astype(str).sum(axis=1))
            recs.append({**base, "id": make_id(sport, r.game_id, market, line, cfg_h, mode, r.data_fp, fp),
                         "market": market, "line": line, "probabilities": probs, "cote_admissible": cote,
                         "decision": decision, "raison_abstention": reason})
        if r.status == "final":
            recs.append({"kind": "result", "id": make_id("result", sport, r.game_id, r.home_score, r.away_score),
                         "origine": origin, "sport": sport, "game_id": r.game_id, "home_score": int(r.home_score),
                         "away_score": int(r.away_score), "demo": origin == "demo"})
    for (gid, mk, ln), grp in simg.items():
        if (gid, mk, ln) in seen:
            continue
        g = ann_by[gid]
        mode = "prospective" if g["status"] != "final" else "backtest"
        fp = make_id(*grp[["bookmaker", "selection", "odds", "observed_at"]].astype(str).sum(axis=1))
        recs.append({"kind": "prediction", "mode": mode, "origine": origin, "sport": sport, "game_id": gid,
                     "event": f"{g['home_team']} - {g['away_team']}", "game_date": str(g["game_date"].date()),
                     "created_at": now, "cutoff": oddsmod.cutoff_for(g["game_date"]).isoformat(),
                     "config_hash": cfg_h, "data_fp": g["data_fp"], "demo": origin == "demo", "market": mk,
                     "line": None if ln < 0 else float(ln),
                     "probabilities": {f"{r.selection}@{r.line}": {"gain": r.p_win, "remb": r.p_push, "perte": r.p_loss} for r in grp.itertuples()},
                     "cote_admissible": {"bookmaker": grp.iloc[0]["bookmaker"]},
                     "decision": "simuler" if (grp["decision"] == "simuler").any() else "abstention",
                     "raison_abstention": "" if (grp["decision"] == "simuler").any() else "EV sous le seuil",
                     "id": make_id(sport, gid, mk, ln, cfg_h, mode, g["data_fp"], fp)})
    if len(sim):
        for r in sim[(sim["decision"] == "simuler") & sim["outcome"].notna()].itertuples(index=False):
            recs.append({"kind": "settlement", "id": make_id("settle", sport, r.game_id, r.market, r.selection, r.line, r.bookmaker, r.odds),
                         "origine": origin, "sport": sport, "game_id": r.game_id, "market": r.market, "selection": r.selection,
                         "line": None if pd.isna(r.line) else r.line, "odds": r.odds, "outcome": r.outcome,
                         "profit_units": r.profit, "demo": origin == "demo"})
    return recs


def run_sport(origin: str, sport: str) -> dict:
    s = st.Store(origin)
    try:
        games = s.games(sport)
        odds_all = s.odds(sport)
    finally:
        s.close()
    n_final = int((games["status"] == "final").sum()) if len(games) else 0
    if n_final < MIN_FINALS:
        rep = {"sport": sport, "origin": origin, "statut": "données insuffisantes",
               "detail": f"{n_final} matchs finaux (< {MIN_FINALS}) : voir la page Données pour le blocage exact"}
        (config.origin_dir(origin) / f"report_{sport}.json").write_text(json.dumps(rep, indent=2, ensure_ascii=False), encoding="utf-8")
        return rep
    split = make_split(games, sport, origin)
    preds, fit_info = walk_forward(games, sport, split["train_end"])
    dates = dict(zip(games["game_id"].astype(str), games["game_date"]))
    adm, refused = oddsmod.admissible(odds_all, dates) if len(odds_all) else (odds_all, 0)
    ann, rep = evaluate(sport, origin, games, preds, split, fit_info, market_fair=adm if len(adm) else None)
    sim = simulate(ann, adm) if len(adm) else pd.DataFrame()
    rep["cotes"] = {"importees": int(len(odds_all)), "admissibles": int(len(adm)), "refusees_posterieures_au_cutoff": refused,
                    "fixtures": bool(len(odds_all) and odds_all["is_fixture"].all())}
    rep["simulation"] = {seg: summarize(sim, seg) for seg in ("test", "calibration")}
    if origin == "demo" or rep["cotes"]["fixtures"]:
        rep["simulation"]["note"] = "Cotes FIXTURES : teste les règlements, ne prouve aucun ROI réel."
    cfg = {"sport": sport, "train_end": split["train_end"], "calib_end": split["calib_end"],
           "winner": rep["modele_vainqueur_selectionne_sur_validation"], "total": rep["modele_total_selectionne_sur_validation"],
           "elo": config.ELO[sport], "k_grid": list(config.ELO_K_GRID), "poisson_k": config.POISSON_SHRINK_K,
           "ev_threshold": config.EV_THRESHOLD, "horizon_hours": config.HORIZON_HOURS}
    ch = config_hash(cfg)
    rep["config_hash"] = ch
    j = Journal(origin)
    rep["journal"] = {"ecrit": j.append_many(_entries(sport, origin, ann, sim, cfg, ch, rep["total"]["ligne"])), "chaine_valide": j.verify()}
    ann.to_parquet(config.origin_dir(origin) / f"predictions_{sport}.parquet", index=False)
    if len(sim):
        sim.to_parquet(config.origin_dir(origin) / f"simulation_{sport}.parquet", index=False)
    (config.origin_dir(origin) / f"report_{sport}.json").write_text(json.dumps(rep, indent=2, ensure_ascii=False, default=float), encoding="utf-8")
    return rep


def run_all(origin: str, sports: list[str] | None = None) -> dict:
    return {sp: run_sport(origin, sp) for sp in (sports or config.SPORTS)}


def refit_upcoming(origin: str, sport: str) -> dict:
    """Nouvelle version du modèle pour les matchs à venir, ajustée avec les seuls résultats terminés connus.

    Chronologie : entraînement (75 % des matchs terminés) < calibration/sélection (le reste, jusqu'à la date limite).
    Aucun résultat futur ; le backtest existant (fichiers `*_<sport>.*`) n'est ni lu ni modifié ; le journal n'est qu'étendu.
    """
    s = st.Store(origin)
    try:
        games, odds_all = s.games(sport), s.odds(sport)
    finally:
        s.close()
    fin = games[games["status"] == "final"]
    if len(fin) < MIN_FINALS:
        return {"sport": sport, "origin": origin, "statut": "données insuffisantes", "detail": f"{len(fin)} matchs finaux"}
    cutoff = fin["game_date"].max()
    daily = fin.groupby("game_date").size().sort_index()
    cum = daily.cumsum() / daily.sum()
    train_end = cum.index[int(cum.to_numpy().__ge__(0.75).argmax())]
    split = {"train_end": str(train_end.date()), "calib_end": str(cutoff.date()), "n_final": int(len(fin)), "kind": "refit"}
    base = {"kind": "refit", "sport": sport, "data_cutoff": str(cutoff.date()), **split, "elo": config.ELO[sport],
            "k_grid": list(config.ELO_K_GRID), "poisson_k": config.POISSON_SHRINK_K, "horizon_hours": config.HORIZON_HOURS}
    vh = config_hash(base)
    version = f"refit-{cutoff:%Y-%m-%d}-{vh}"
    tag = f"_upcoming_{cutoff:%Y%m%d}_{vh}"
    preds, fit_info = walk_forward(games, sport, train_end)
    dates = dict(zip(games["game_id"].astype(str), games["game_date"]))
    adm, refused = oddsmod.admissible(odds_all, dates) if len(odds_all) else (odds_all, 0)
    meta = {"version": version, "type": "prevision_a_venir", "date_limite_donnees": str(cutoff.date()),
            "resultats_termines_utilises": int(len(fin))}
    ann, rep = evaluate(sport, origin, games, preds, split, fit_info, market_fair=None, tag=tag, meta=meta)
    up = ann[ann["status"] != "final"].reset_index(drop=True)
    sim = simulate(up, adm) if len(adm) and len(up) else pd.DataFrame()
    cfg = {**base, "version": version, "winner": rep["modele_vainqueur_selectionne_sur_validation"],
           "total": rep["modele_total_selectionne_sur_validation"], "ev_threshold": config.EV_THRESHOLD}
    ch = config_hash(cfg)
    j = Journal(origin)
    rep["config_hash"] = ch
    rep["journal"] = {"ecrit": j.append_many(_entries(sport, origin, up, sim, cfg, ch, rep["total"]["ligne"], version)),
                      "chaine_valide": j.verify()}
    rep["a_venir"] = int(len(up))
    up.to_parquet(config.origin_dir(origin) / f"predictions_{sport}{tag}.parquet", index=False)
    (config.origin_dir(origin) / f"report_{sport}{tag}.json").write_text(
        json.dumps(rep, indent=2, ensure_ascii=False, default=float), encoding="utf-8")
    return rep
