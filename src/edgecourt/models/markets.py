"""Distributions discrètes d'écart et de total, puis probabilités de gain / remboursement / perte par marché."""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.stats import norm, poisson


@dataclass
class Dist:
    mk: np.ndarray  # écarts possibles (domicile - extérieur)
    mp: np.ndarray
    tk: np.ndarray  # totaux possibles
    tp: np.ndarray

    def one_x_two(self) -> tuple[float, float, float]:
        return (float(self.mp[self.mk > 0].sum()), float(self.mp[self.mk == 0].sum()), float(self.mp[self.mk < 0].sum()))


def _norm_pmf(mu: float, sd: float, lo: int | None = None) -> tuple[np.ndarray, np.ndarray]:
    sd = max(float(sd), 1e-6)
    a, b = int(np.floor(mu - 7 * sd)) - 1, int(np.ceil(mu + 7 * sd)) + 1
    if lo is not None:
        a = max(a, lo)
    k = np.arange(a, b + 1)
    p = norm.cdf((k + 0.5 - mu) / sd) - norm.cdf((k - 0.5 - mu) / sd)
    return k, p / p.sum()


def dist_from_params(p: dict) -> Dist:
    """Reconstruit la distribution depuis les paramètres journalisés (normal ou Poisson indépendants)."""
    if p["kind"] == "normal":
        mk, mp = _norm_pmf(p["mu_m"], p["sd_m"])
        tk, tp = _norm_pmf(p["mu_t"], p["sd_t"], lo=0)
        return Dist(mk, mp, tk, tp)
    if p["kind"] == "poisson":
        g = np.arange(0, 13)
        ph, pa = poisson.pmf(g, max(p["lh"], 1e-6)), poisson.pmf(g, max(p["la"], 1e-6))
        M = np.outer(ph, pa)
        M /= M.sum()
        mk = np.arange(-12, 13)
        mp = np.array([np.trace(M, offset=-d) for d in mk])
        tk = np.arange(0, 25)
        tp = np.array([np.fliplr(M).trace(offset=12 - t) for t in tk])
        return Dist(mk, mp / mp.sum(), tk, tp / tp.sum())
    raise ValueError(p["kind"])


def _check_line(line: float) -> None:
    if abs(line * 2 - round(line * 2)) > 1e-9:
        raise ValueError(f"ligne {line} non supportée (quarts de points / handicaps asiatiques exclus)")


def total_probs(d: Dist, line: float) -> tuple[float, float, float]:
    """(gain « plus de », remboursement, perte « plus de ») ; « moins de » = (perte, remb., gain)."""
    _check_line(line)
    return (float(d.tp[d.tk > line].sum()), float(d.tp[np.isclose(d.tk, line)].sum()), float(d.tp[d.tk < line].sum()))


def spread_probs(d: Dist, line: float) -> tuple[float, float, float]:
    """Handicap `line` appliqué au DOMICILE : gain si écart + ligne > 0, remboursement si = 0."""
    _check_line(line)
    adj = d.mk + line
    return (float(d.mp[adj > 1e-9].sum()), float(d.mp[np.abs(adj) < 1e-9].sum()), float(d.mp[adj < -1e-9].sum()))


def selection_probs(market: str, selection: str, line: float | None, d: Dist, winner: tuple[float, float, float],
                    rule: str) -> tuple[float, float, float]:
    """(p_gain, p_remboursement, p_perte) pour une sélection. `winner` = (p_dom, p_nul, p_ext) du modèle retenu."""
    ph, pd_, pa = winner
    if market == "1x2":
        w = {"home": ph, "draw": pd_, "away": pa}[selection]
        return (w, 0.0, 1 - w)
    if market == "moneyline":
        w = ph if selection == "home" else pa
        if rule == "tie_refund":
            return (w, pd_, 1 - w - pd_)
        return (w, 0.0, 1 - w)  # tie_loss : le nul fait perdre les deux côtés
    if market == "total":
        po, pp, pu = total_probs(d, float(line))
        return (po, pp, pu) if selection == "over" else (pu, pp, po)
    if market == "spread":
        if selection == "home":
            return spread_probs(d, float(line))
        # l'extérieur reçoit `line` : gain si -écart + line > 0  <=> écart + (-line) < 0
        w, p, l = spread_probs(d, -float(line))
        return (l, p, w)
    raise ValueError(market)


def ev_per_unit(p_win: float, p_loss: float, odds: float) -> float:
    """Espérance par unité misée : p_gain*(cote-1) - p_perte ; les remboursements valent 0."""
    return p_win * (odds - 1.0) - p_loss
