"""Walk-forward : prévisions jour par jour, modèles ajustés UNIQUEMENT sur les matchs <= train_end.

Pour chaque jour (ordre chronologique) : 1) variables depuis l'état passé, 2) prévision, 3) seulement ensuite
mise à jour de l'état avec les résultats du jour. Les modèles appris (régression logistique, ridge) sont figés à
`train_end` : ni le calibrateur ni le test final ne les ont servis.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression, Ridge
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from .. import config
from ..features.state import ELO_MAIN, SportState
from .markets import dist_from_params

MIN_FIT = 100
WIN_FEATS = ["elo_diff20", "rest_diff", "form_diff"]
TOT_FEATS = ["pace_h", "pace_a"]
UI_FEATS = ["elo_h", "elo_a", "rest_h", "rest_a", "form_h", "form_a", "pace_h", "pace_a"]


def winner_models(sport: str) -> list[str]:
    return ["baseline", *[f"elo{int(k)}" for k in config.ELO_K_GRID], "poisson" if sport == "soccer" else "logit"]


@dataclass
class Fit:
    ok: bool = False
    n: int = 0
    logit: object = None
    rm: object = None
    rt: object = None
    sd_m: float = 0.0
    sd_t: float = 0.0
    tie_rate: float = 0.0
    info: dict = field(default_factory=dict)


def _fit(sport: str, rows: list[tuple[dict, object]]) -> Fit:
    fit = Fit(n=len(rows))
    if sport == "soccer" or len(rows) < MIN_FIT:
        fit.info = {"raison": "non requis (Poisson en ligne)" if sport == "soccer" else f"effectif {len(rows)} < {MIN_FIT}"}
        return fit
    F = pd.DataFrame([f for f, _ in rows])
    margin = np.array([r.home_score - r.away_score for _, r in rows], dtype=float)
    total = np.array([r.home_score + r.away_score for _, r in rows], dtype=float)
    fit.tie_rate = float((margin == 0).mean())
    dec = margin != 0
    y = (margin[dec] > 0).astype(int)
    if y.min() == y.max() or min(y.sum(), (1 - y).sum()) < 5:
        fit.info = {"raison": "classes insuffisantes"}
        return fit
    fit.logit = make_pipeline(StandardScaler(), LogisticRegression(C=1.0, max_iter=1000)).fit(F.loc[dec, WIN_FEATS], y)
    fit.rm = make_pipeline(StandardScaler(), Ridge(alpha=10.0)).fit(F[WIN_FEATS], margin)
    fit.rt = make_pipeline(StandardScaler(), Ridge(alpha=10.0)).fit(F[TOT_FEATS], total)
    fit.sd_m = float(np.std(margin - fit.rm.predict(F[WIN_FEATS]), ddof=1))  # variance estimée sur résidus d'entraînement
    fit.sd_t = float(np.std(total - fit.rt.predict(F[TOT_FEATS]), ddof=1))
    fit.ok = True
    fit.info = {"n_train": len(rows), "coef_logit": dict(zip(WIN_FEATS, fit.logit[-1].coef_[0].round(4).tolist())),
                "sd_marge": round(fit.sd_m, 3), "sd_total": round(fit.sd_t, 3), "taux_nul": round(fit.tie_rate, 4)}
    return fit


def _lin(pipe, x: list[float]) -> float:
    """Inférence directe (scaler + modèle linéaire) sans surcoût DataFrame/sklearn."""
    sc, est = pipe[0], pipe[-1]
    return float(((np.asarray(x) - sc.mean_) / sc.scale_) @ est.coef_.ravel() + float(np.ravel(est.intercept_)[0]))


def _three_way(e: float, dr: float, shaped: bool) -> tuple[float, float, float]:
    pd_ = dr * 4 * e * (1 - e) if shaped else dr
    pd_ = min(pd_, 2 * min(e, 1 - e))
    return (e - pd_ / 2, pd_, 1 - e - pd_ / 2)


def _predict(sport: str, f: dict, fit: Fit) -> dict:
    out = {}
    lg_dr = f["lg_draw_rate"]
    hw, aw = f["lg_home_win_rate"], f["lg_away_win_rate"]
    s = hw + aw + lg_dr
    out["w_baseline"] = (hw / s, lg_dr / s, aw / s)
    for k in config.ELO_K_GRID:
        e = 1.0 / (1.0 + 10 ** (-f[f"elo_diff{int(k)}"] / 400.0))
        out[f"w_elo{int(k)}"] = _three_way(e, lg_dr, shaped=(sport == "soccer"))
    base_params = (
        {"kind": "poisson", "lh": f["lam_h0"], "la": f["lam_a0"]} if sport == "soccer" else
        {"kind": "normal", "mu_m": f["lg_mean_margin"], "sd_m": f["lg_sd_margin"],
         "mu_t": f["lg_mean_total"], "sd_t": f["lg_sd_total"]})
    out["dp_base"] = base_params
    if sport == "soccer":
        mp = {"kind": "poisson", "lh": f["lam_h"], "la": f["lam_a"]}
        out["w_poisson"] = dist_from_params(mp).one_x_two()
        out["dp_model"] = mp
    elif fit.ok:
        xw = [f[k] for k in WIN_FEATS]
        p = 1.0 / (1.0 + np.exp(-_lin(fit.logit, xw)))
        pd_ = min(max(fit.tie_rate, 0.0), 0.05)
        out["w_logit"] = ((1 - pd_) * p, pd_, (1 - pd_) * (1 - p))
        out["dp_model"] = {"kind": "normal", "mu_m": _lin(fit.rm, xw), "sd_m": fit.sd_m,
                           "mu_t": _lin(fit.rt, [f[k] for k in TOT_FEATS]), "sd_t": fit.sd_t}
    else:  # volume insuffisant : repli explicite sur Elo / référence
        out["w_logit"] = out["w_elo20"]
        out["dp_model"] = base_params
    return out


def walk_forward(games: pd.DataFrame, sport: str, train_end) -> tuple[pd.DataFrame, dict]:
    """Retourne (prévisions pour tous les matchs de date > train_end, informations d'ajustement)."""
    train_end = pd.Timestamp(train_end)
    games = games.sort_values(["game_date", "game_id"]).reset_index(drop=True)
    state, fp, fit = SportState(sport), hashlib.sha256(), None
    train_rows: list[tuple[dict, object]] = []
    out: list[dict] = []
    for date, day in games.groupby("game_date", sort=True):
        if fit is None and date > train_end:
            fit = _fit(sport, train_rows)
        fp_day = fp.hexdigest()[:16]
        rows = list(day.itertuples(index=False))
        feats = [state.features(r) for r in rows]  # tout le jour est calculé AVANT toute mise à jour
        for r, f in zip(rows, feats):
            if date <= train_end:
                if r.status == "final":
                    train_rows.append((f, r))
                continue
            preds = _predict(sport, f, fit)
            rec = {"game_id": r.game_id, "game_date": r.game_date, "season": r.season, "home_team": r.home_team,
                   "away_team": r.away_team, "status": r.status,
                   "home_score": r.home_score if r.status == "final" else np.nan,
                   "away_score": r.away_score if r.status == "final" else np.nan,
                   "data_fp": fp_day, "fitted": bool(fit.ok) if sport != "soccer" else True}
            for key, v in preds.items():
                if key.startswith("w_"):
                    rec[key + "_h"], rec[key + "_d"], rec[key + "_a"] = v
                else:
                    rec[key] = json.dumps(v)
            rec.update({k: f[k] for k in UI_FEATS})
            out.append(rec)
        for r in rows:
            if r.status == "final":
                state.update(r)
                fp.update(f"{r.game_id}|{r.home_score}|{r.away_score};".encode())
            else:
                state.note_scheduled(r)
    info = fit.info if fit else {"raison": "aucun match après train_end"}
    return pd.DataFrame(out), info
