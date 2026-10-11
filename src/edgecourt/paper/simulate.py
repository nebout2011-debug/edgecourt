"""Simulation à mise fixe d'une unité. Ce n'est PAS une gestion de bankroll et ne démontre aucun rendement durable."""
from __future__ import annotations

import json

import numpy as np
import pandas as pd

from .. import config
from ..evaluation import metrics as M
from ..models.markets import dist_from_params, ev_per_unit, selection_probs
from .settlement import profit_units, settle

FEES_PER_UNIT = 0.0  # hypothèse visible : aucun frais (abonnements nuls)


def simulate(preds: pd.DataFrame, odds: pd.DataFrame, threshold: float = config.EV_THRESHOLD) -> pd.DataFrame:
    """`odds` = cotes admissibles (colonnes de data.odds.admissible). Une ligne par cote avec p, EV, décision, résultat."""
    if odds.empty or preds.empty:
        return pd.DataFrame()
    by_game = {r["game_id"]: r for r in preds.to_dict("records")}
    cache: dict = {}
    rows = []
    for o in odds.itertuples(index=False):
        g = by_game.get(o.game_id)
        if g is None:
            continue
        if o.game_id not in cache:
            dp = g["dp_model"] if g["total_dist_selected"] == "model" else g["dp_base"]
            cache[o.game_id] = dist_from_params(json.loads(dp))
        d = cache[o.game_id]
        winner = (g["p_home_final"], g["p_draw_final"], g["p_away_final"])
        pw, pp, pl = selection_probs(o.market, o.selection, None if pd.isna(o.line) else o.line, d, winner, o.settlement_rule)
        ev = ev_per_unit(pw, pl, o.odds) - FEES_PER_UNIT
        final = g["status"] == "final"
        outcome = settle(o.market, o.selection, o.line, o.settlement_rule, int(g["home_score"]), int(g["away_score"])) if final else None
        rows.append({"game_id": o.game_id, "game_date": g["game_date"], "segment": g["segment"], "bookmaker": o.bookmaker,
                     "market": o.market, "selection": o.selection, "line": o.line, "odds": o.odds,
                     "observed_at": o.observed_at, "fair_prob": o.fair, "p_win": pw, "p_push": pp, "p_loss": pl, "ev": ev,
                     "outcome": outcome, "is_fixture": bool(getattr(o, "is_fixture", False))})
    s = pd.DataFrame(rows)
    if s.empty:
        return s
    grp = ["game_id", "bookmaker", "market"]
    s["_k"] = s["line"].abs().fillna(-1.0)
    best = s.groupby(grp + ["_k"])["ev"].transform("max")
    is_best = s["ev"] == best
    ok = is_best & (s["ev"] >= threshold)
    s["decision"] = np.where(ok, "simuler", "abstention")
    s["raison_abstention"] = np.where(ok, "", np.where(~is_best, "sélection non retenue (EV inférieure dans le groupe)",
                                                       f"EV estimée < seuil {threshold:.2f}"))
    s["profit"] = [profit_units(oc, od) - FEES_PER_UNIT if (dec == "simuler" and oc) else 0.0
                   for oc, od, dec in zip(s["outcome"], s["odds"], s["decision"])]
    return s.drop(columns="_k").sort_values(["game_date", "game_id"]).reset_index(drop=True)


def summarize(sim: pd.DataFrame, segment: str = "test") -> dict:
    """ROI fictif net, profit en unités, drawdown, courbe cumulée. « rendement non évaluable » sans cotes."""
    if sim.empty:
        return {"statut": "rendement non évaluable", "raison": "aucune cote valide jointe"}
    s = sim[(sim["segment"] == segment) & (sim["decision"] == "simuler") & sim["outcome"].notna()]
    if s.empty:
        return {"statut": "rendement non évaluable", "raison": f"aucun pari simulé sur la période « {segment} »",
                "n_cotes": int((sim["segment"] == segment).sum())}
    cum = s["profit"].cumsum().to_numpy()
    dd = float((np.maximum.accumulate(np.concatenate([[0.0], cum]))[1:] - cum).max())
    mean, lo, hi = M.block_bootstrap(s["profit"].to_numpy(), s["game_date"].dt.strftime("%G-%V").to_numpy())
    n = len(s)
    return {"statut": "preuves insuffisantes" if n < config.MIN_N_EVIDENCE else "simulation rétrospective",
            "segment": segment, "paris": n, "gagnes": int((s["outcome"] == "win").sum()), "perdus": int((s["outcome"] == "loss").sum()),
            "rembourses": int((s["outcome"] == "push").sum()), "mise_totale_unites": float(n),
            "profit_unites": float(s["profit"].sum()), "roi_net": float(s["profit"].sum() / n),
            "roi_ic95": [lo, hi], "drawdown_max_unites": dd, "frais_par_unite": FEES_PER_UNIT,
            "courbe_cumulee": [{"date": str(d.date()), "cumul": float(c)} for d, c in list(zip(s["game_date"], cum))[:: max(1, n // 300)]],
            "avertissement": "Mise fixe 1 unité : pas une gestion de bankroll. Un ROI passé ne prouve rien sur l'avenir."}
