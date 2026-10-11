"""Découpage chronologique fixe, sélection sur validation, calibration, test final intact, rapport."""
from __future__ import annotations

import json

import numpy as np
import pandas as pd

from .. import config
from ..data.store import now_utc
from ..models.calibration import Calibrator
from ..models.engine import winner_models
from ..models.markets import dist_from_params, total_probs
from . import metrics as M


def make_split(games: pd.DataFrame, sport: str, origin: str, resplit: bool = False) -> dict:
    """60 % entraînement / 20 % calibration+sélection / 20 % test final, par date. Figé une fois créé."""
    path = config.origin_dir(origin) / f"split_{sport}.json"
    if path.exists() and not resplit:
        return json.loads(path.read_text(encoding="utf-8"))
    fin = games[games["status"] == "final"]
    d = fin.groupby("game_date").size().sort_index()
    cum = d.cumsum() / d.sum()
    train_end = cum.index[int(np.argmax(cum.to_numpy() >= 0.6))]
    calib_end = cum.index[int(np.argmax(cum.to_numpy() >= 0.8))]
    sp = {"train_end": str(train_end.date()), "calib_end": str(calib_end.date()), "n_final": int(len(fin)),
          "created_at": now_utc().isoformat(timespec="seconds")}
    path.write_text(json.dumps(sp, indent=2), encoding="utf-8")
    return sp


def ref_total_line(games: pd.DataFrame, sport: str, train_end) -> float:
    if sport == "soccer":
        return 2.5
    tr = games[(games["status"] == "final") & (games["game_date"] <= pd.Timestamp(train_end))]
    return float(np.floor((tr["home_score"] + tr["away_score"]).mean())) + 0.5  # ligne .5 : jamais de remboursement


def _wp(df: pd.DataFrame, m: str) -> np.ndarray:
    return df[[f"w_{m}_h", f"w_{m}_d", f"w_{m}_a"]].to_numpy(dtype=float)


def _total_matrix(df: pd.DataFrame, which: str, line: float) -> np.ndarray:
    col = "dp_base" if which == "base" else "dp_model"
    return np.array([total_probs(dist_from_params(json.loads(s)), line) for s in df[col]])


def _total_y(df: pd.DataFrame, line: float) -> np.ndarray:
    t = (df["home_score"] + df["away_score"]).to_numpy(dtype=float)
    return np.stack([t > line, t == line, t < line], axis=1).astype(float)


def _rows(model: str, period: str, P, Y) -> dict:
    b, l = M.brier_rows(P, Y), M.logloss_rows(P, Y)
    return {"modele": model, "periode": period, "n": int(len(P)), "brier": float(b.mean()), "logloss": float(l.mean())}


def evaluate(sport: str, origin: str, games: pd.DataFrame, preds: pd.DataFrame, split: dict, fit_info: dict,
             market_fair: pd.DataFrame | None = None, tag: str = "",
             meta: dict | None = None) -> tuple[pd.DataFrame, dict]:
    """Retourne (prévisions annotées, rapport). `preds` = sortie de walk_forward (matchs > train_end)."""
    te, ce = pd.Timestamp(split["train_end"]), pd.Timestamp(split["calib_end"])
    p = preds.copy()
    p["segment"] = np.where(p["status"] != "final", "a_venir", np.where(p["game_date"] <= ce, "calibration", "test"))
    fin = p[p["status"] == "final"]
    val, test = fin[fin["segment"] == "calibration"], fin[fin["segment"] == "test"]
    Yv, Yt = M.onehot_winner(val["home_score"], val["away_score"]), M.onehot_winner(test["home_score"], test["away_score"])
    cfg_tried, wrows = [], []

    # --- marché vainqueur (1X2 / moneyline) ---
    cands = winner_models(sport)
    val_ll = {}
    for m in cands:
        if len(val):
            r = _rows(m, "validation", _wp(val, m), Yv)
            val_ll[m] = r["logloss"]
            wrows.append(r)
            cfg_tried.append({"marche": "vainqueur", "modele": m, "periode": "validation", **{k: r[k] for k in ("n", "logloss", "brier")}})
    selected = min(val_ll, key=val_ll.get) if val_ll else "baseline"
    cal = Calibrator()
    if len(val):
        cal.fit(_wp(val, selected)[:, 0], Yv[:, 0])
    p["p_home_final"], p["p_draw_final"], p["p_away_final"] = cal.apply(*_wp(p, selected).T)
    p["model_selected"] = selected
    p["calibrated"] = cal.model is not None
    base_ll_rows = None
    winner_ci = None
    if len(test):
        for m in cands:
            wrows.append(_rows(m, "test", _wp(test, m), Yt))
        tt = p.loc[test.index]
        Pf = tt[["p_home_final", "p_draw_final", "p_away_final"]].to_numpy()
        wrows.append(_rows(f"{selected} ({'calibré' if cal.model is not None else 'non calibré'})", "test", Pf, Yt))
        diff = M.logloss_rows(Pf, Yt) - M.logloss_rows(_wp(test, "baseline"), Yt)
        blocks = test["game_date"].dt.strftime("%G-%V").to_numpy()
        mean, lo, hi = M.block_bootstrap(diff, blocks)
        winner_ci = {"delta_logloss_vs_baseline": mean, "ic95_bas": lo, "ic95_haut": hi,
                     "statut": M.evidence_status(len(test), lo, hi), "blocs": "semaines ISO"}
    base_b = next((r["brier"] for r in wrows if r["modele"] == "baseline" and r["periode"] == "test"), None)
    for r in wrows:
        r["skill_brier_vs_baseline"] = (1 - r["brier"] / base_b) if base_b and r["periode"] == "test" else None
    curve = []
    if len(test):
        tt = p.loc[test.index]
        curve = M.calibration_table(tt["p_home_final"].to_numpy(), Yt[:, 0]).to_dict("records")

    # --- marché total (ligne de référence fixée sur l'entraînement) ---
    L = ref_total_line(games, sport, te)
    trows, total_ci, selected_total = [], None, "base"
    if len(val):
        vl = {}
        for which in ("base", "model"):
            r = _rows(which, "validation", _total_matrix(val, which, L), _total_y(val, L))
            vl[which] = r["logloss"]
            trows.append(r)
            cfg_tried.append({"marche": f"total@{L}", "modele": which, "periode": "validation", **{k: r[k] for k in ("n", "logloss", "brier")}})
        selected_total = min(vl, key=vl.get)
    if len(test):
        Yq = _total_y(test, L)
        res = {}
        for which in ("base", "model"):
            P = _total_matrix(test, which, L)
            res[which] = P
            trows.append(_rows(which, "test", P, Yq))
        diff = M.logloss_rows(res["model"], Yq) - M.logloss_rows(res["base"], Yq)
        mean, lo, hi = M.block_bootstrap(diff, test["game_date"].dt.strftime("%G-%V").to_numpy())
        total_ci = {"delta_logloss_vs_baseline": mean, "ic95_bas": lo, "ic95_haut": hi,
                    "statut": M.evidence_status(len(test), lo, hi), "blocs": "semaines ISO"}
    p["total_dist_selected"] = selected_total

    # --- référence marché (mêmes événements, même bookmaker) ---
    mref = {"statut": "rendement non évaluable : aucune cote valide jointe à ces prévisions"}
    if market_fair is not None and len(market_fair) and len(test):
        mref = _market_reference(sport, p, test, market_fair)

    report = {
        "sport": sport, "origin": origin, "generated_at": now_utc().isoformat(timespec="seconds"),
        "split": split, "ligne_total_reference": L, "ajustement": fit_info,
        "effectifs": {"matchs_finaux_evalues": int(len(fin)), "calibration": int(len(val)), "test": int(len(test)),
                      "a_venir": int((p["status"] != "final").sum())},
        "modele_vainqueur_selectionne_sur_validation": selected, "calibration": cal.status,
        "modele_total_selectionne_sur_validation": selected_total,
        "vainqueur": {"lignes": wrows, "ic": winner_ci, "courbe_calibration": curve},
        "total": {"ligne": L, "lignes": trows, "ic": total_ci},
        "reference_marche": mref,
        "avertissement": "Aucun avantage durable n'est démontré. Résultats rétrospectifs, simulation uniquement.",
    }
    if meta:
        report.update(meta)
    if origin == "demo":
        report["etiquette"] = "DÉMONSTRATION SYNTHÉTIQUE - aucune valeur sportive"
    (config.origin_dir(origin) / f"report_{sport}{tag}.json").write_text(json.dumps(report, indent=2, ensure_ascii=False, default=float), encoding="utf-8")
    with (config.origin_dir(origin) / "configs_tried.jsonl").open("a", encoding="utf-8") as fh:
        for c in cfg_tried:
            fh.write(json.dumps({"at": report["generated_at"], "sport": sport, "origine": origin, **({"version": meta["version"]} if meta else {}), **c}, ensure_ascii=False) + "\n")
    return p, report


def _market_reference(sport: str, p: pd.DataFrame, test: pd.DataFrame, fair: pd.DataFrame) -> dict:
    mk = "1x2" if sport == "soccer" else "moneyline"
    f = fair[fair["market"] == mk]
    if f.empty:
        return {"statut": "rendement non évaluable : pas de cotes vainqueur admissibles sur la période test"}
    best_bk = f.groupby("bookmaker")["game_id"].nunique().idxmax()
    f = f[f["bookmaker"] == best_bk]
    piv = f.pivot_table(index="game_id", columns="selection", values="fair", aggfunc="first")
    piv = piv.reindex(columns=["home", "draw", "away"])
    piv["draw"] = piv["draw"].fillna(0.0)
    t = test[test["game_id"].isin(piv.index)]
    if len(t) < 2:
        return {"statut": "couverture des cotes insuffisante sur la période test", "n": int(len(t))}
    t = t.drop_duplicates("game_id")
    Pm = piv.loc[t["game_id"]].to_numpy(dtype=float)
    Pb = _wp(t, "baseline")
    Pf = p.loc[t.index, ["p_home_final", "p_draw_final", "p_away_final"]].to_numpy()
    Y = M.onehot_winner(t["home_score"], t["away_score"])
    note = "retrait de marge proportionnel ; cotes horodatées avant le cutoff du jour"
    if sport != "soccer":  # le marché ne cote pas le nul : comparaison sur les issues décisives, tout renormalisé
        dec = (t["home_score"] != t["away_score"]).to_numpy()
        Pm, Pb, Pf, Y = (x[dec][:, [0, 2]] for x in (Pm, Pb, Pf, Y))
        Pb, Pf, Pm = (x / x.sum(axis=1, keepdims=True) for x in (Pb, Pf, Pm))
        t = t[dec]
        note += " ; nuls exclus de cette comparaison seulement (le marché ne les cote pas)"
    else:
        Pm = Pm / Pm.sum(axis=1, keepdims=True)
    return {"bookmaker": best_bk, "n_evenements": int(len(t)), "couverture_test": float(len(t) / len(test)),
            "lignes": [_rows("référence simple", "test (mêmes événements)", Pb, Y),
                       _rows("modèle retenu", "test (mêmes événements)", Pf, Y),
                       _rows("marché sans marge", "test (mêmes événements)", Pm, Y)],
            "limite": note}
