"""Cotes : validation de l'import CSV, jointure temporelle stricte, retrait de marge simple.

Schéma CSV : event_id, bookmaker, market, selection, line, odds_decimal, observed_at, settlement_rule
  market ∈ {1x2, moneyline, total, spread}; selection ∈ {home, draw, away, over, under}
  settlement_rule ∈ {standard, tie_refund, tie_loss}
Limite documentée : le retrait de marge proportionnel suppose une marge répartie au prorata des probabilités ;
il ignore le biais favori/outsider. Il n'est calculé que sur des issues exhaustives, même bookmaker, même instant, même ligne.
"""
from __future__ import annotations

import pandas as pd

from .. import config
from .store import event_key

SELECTIONS = {"1x2": {"home", "draw", "away"}, "moneyline": {"home", "away"},
              "total": {"over", "under"}, "spread": {"home", "away"}}
RULES = {"standard", "tie_refund", "tie_loss"}
CSV_COLS = ["event_id", "bookmaker", "market", "selection", "line", "odds_decimal", "observed_at", "settlement_rule"]


def cutoff_for(game_date, hours: int = config.HORIZON_HOURS) -> pd.Timestamp:
    """Horizon de prévision : début du jour (UTC) du match moins `hours`. Seule la date est fiable, pas l'heure."""
    return pd.Timestamp(game_date).normalize() - pd.Timedelta(hours=hours)


def validate_odds(df: pd.DataFrame, games: pd.DataFrame, sport: str, source: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Retourne (cotes valides au format table `odds`, rejets[row, reason])."""
    miss = [c for c in CSV_COLS if c not in df.columns]
    if miss:
        raise ValueError(f"colonnes manquantes : {miss}")
    d = df.copy().reset_index(drop=True)
    d["observed_at"] = pd.to_datetime(d["observed_at"], errors="coerce", utc=True).dt.tz_localize(None)
    d["odds"] = pd.to_numeric(d["odds_decimal"], errors="coerce")
    d["line"] = pd.to_numeric(d["line"], errors="coerce")
    d["event_id"] = d["event_id"].astype(str)
    d["settlement_rule"] = d["settlement_rule"].fillna("standard").astype(str)
    reasons: dict[int, str] = {}

    def flag(mask, why):
        for i in d.index[mask]:
            reasons.setdefault(i, why)

    flag(~d["event_id"].isin(set(games["game_id"].astype(str))), "événement inconnu")
    flag(d["observed_at"].isna(), "observed_at manquant ou invalide")
    flag(~(d["odds"] > 1.0), "cote décimale <= 1 ou invalide")
    flag(~d["market"].isin(SELECTIONS), "marché inconnu")
    ok_sel = [(m in SELECTIONS and s in SELECTIONS[m]) for m, s in zip(d["market"], d["selection"])]
    flag(~pd.Series(ok_sel, index=d.index), "sélection incompatible avec le marché")
    needs_line = d["market"].isin(["total", "spread"])
    flag(needs_line & d["line"].isna(), "ligne manquante")
    flag(~needs_line & d["line"].notna(), "ligne non applicable à ce marché")
    flag(needs_line & d["line"].notna() & ((d["line"] * 2 - (d["line"] * 2).round()).abs() > 1e-9),
         "ligne non supportée (quart de point)")
    flag(~d["settlement_rule"].isin(RULES), "règle de règlement inconnue")
    flag((d["market"] == "1x2") & (sport != "soccer"), "1x2 réservé au soccer")
    flag((d["market"] == "moneyline") & (sport == "soccer"), "moneyline interdit en soccer (utiliser 1x2)")
    d["_l"] = d["line"].fillna(-9999.0)
    key = ["event_id", "bookmaker", "market", "selection", "_l", "observed_at"]
    ok = ~d.index.isin(list(reasons))
    nun = d.groupby(key)["odds"].transform("nunique")
    flag(ok & (nun > 1), "jointure ambiguë : même clé et même instant avec cotes différentes")
    ok = ~d.index.isin(list(reasons))
    flag(ok & d.duplicated(key + ["odds"], keep="first"), "doublon exact")
    bad = pd.DataFrame({"row": list(reasons), "reason": list(reasons.values())})
    good = d[~d.index.isin(list(reasons))].copy()
    good["sport"], good["source"] = sport, source
    good["game_id"] = good["event_id"]
    good["event_key"] = [event_key(sport, source, g) for g in good["game_id"]]
    return good, bad


def admissible(odds: pd.DataFrame, game_dates: dict[str, pd.Timestamp], hours: int = config.HORIZON_HOURS):
    """Garde, par groupe exhaustif (event, bookmaker, market, ligne, instant), le dernier groupe COMPLET observé <= cutoff.

    Retourne (cotes admissibles avec colonne `fair` = probabilité implicite sans marge, nombre refusé car postérieur).
    """
    if odds.empty:
        return odds.assign(fair=pd.Series(dtype=float)), 0
    o = odds.copy()
    o["cutoff"] = [cutoff_for(game_dates[g], hours) for g in o["game_id"]]
    future = int((o["observed_at"] > o["cutoff"]).sum())
    o = o[o["observed_at"] <= o["cutoff"]].copy()
    if o.empty:
        return o.assign(fair=pd.Series(dtype=float)), future
    o["line_key"] = o["line"].abs().fillna(-1.0)  # spread : +L (dom.) et -L (ext.) forment une même ligne
    grp = ["game_id", "bookmaker", "market", "line_key", "observed_at"]
    need = {m: len(s) for m, s in SELECTIONS.items()}
    o["n_sel"] = o.groupby(grp)["selection"].transform("nunique")
    o = o[o["n_sel"] == o["market"].map(need)].copy()
    if o.empty:
        return o.assign(fair=pd.Series(dtype=float)), future
    # lignes compatibles : spread => dom. et ext. de signes opposés ; total => même ligne
    if (o["market"] == "spread").any():
        s = o[o["market"] == "spread"]
        bad = s.groupby(grp)["line"].apply(lambda x: abs(x.sum()) > 1e-9)
        bad_idx = bad[bad].index
        o = o[~o.set_index(grp).index.isin(bad_idx)]
    last = o.groupby(["game_id", "bookmaker", "market", "line_key"])["observed_at"].transform("max")
    o = o[o["observed_at"] == last].copy()
    inv = 1.0 / o["odds"]
    o["fair"] = inv / inv.groupby([o[c] for c in grp]).transform("sum")
    o["overround"] = inv.groupby([o[c] for c in grp]).transform("sum") - 1.0
    return o.drop(columns=["n_sel"]), future
