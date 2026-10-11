"""Métriques de probabilités, calibration et intervalles par blocs temporels."""
from __future__ import annotations

import numpy as np
import pandas as pd

from .. import config

EPS = 1e-12


def onehot_winner(hs, as_) -> np.ndarray:
    hs, as_ = np.asarray(hs, dtype=float), np.asarray(as_, dtype=float)
    return np.stack([hs > as_, hs == as_, hs < as_], axis=1).astype(float)


def brier_rows(P: np.ndarray, Y: np.ndarray) -> np.ndarray:
    """Brier multi-classes (somme des carrés). Comparable seulement au sein d'un même marché."""
    return ((P - Y) ** 2).sum(axis=1)


def logloss_rows(P: np.ndarray, Y: np.ndarray) -> np.ndarray:
    return -(Y * np.log(np.clip(P, EPS, 1.0))).sum(axis=1)


def calibration_table(p: np.ndarray, y: np.ndarray, bins: int = 10) -> pd.DataFrame:
    p, y = np.asarray(p, dtype=float), np.asarray(y, dtype=float)
    idx = np.clip((p * bins).astype(int), 0, bins - 1)
    rows = []
    for b in range(bins):
        m = idx == b
        rows.append({"classe": f"{b / bins:.1f}-{(b + 1) / bins:.1f}", "n": int(m.sum()),
                     "p_moyenne": float(p[m].mean()) if m.any() else np.nan,
                     "frequence_observee": float(y[m].mean()) if m.any() else np.nan})
    return pd.DataFrame(rows)


def block_bootstrap(diff_rows: np.ndarray, block_ids: np.ndarray, n_boot: int = 1000, seed: int = 7):
    """IC 95 % de la moyenne d'un écart de pertes, en rééchantillonnant des BLOCS (semaines) et non des matchs."""
    diff_rows = np.asarray(diff_rows, dtype=float)
    blocks = pd.Series(diff_rows).groupby(np.asarray(block_ids)).agg(["sum", "count"])
    if len(blocks) < 2:
        return float(diff_rows.mean()), np.nan, np.nan
    rng = np.random.default_rng(seed)
    s, c = blocks["sum"].to_numpy(), blocks["count"].to_numpy()
    pick = rng.integers(0, len(blocks), size=(n_boot, len(blocks)))
    means = s[pick].sum(axis=1) / c[pick].sum(axis=1)
    return float(diff_rows.mean()), float(np.percentile(means, 2.5)), float(np.percentile(means, 97.5))


def evidence_status(n: int, lo: float, hi: float) -> str:
    """Jamais de « fiable » : au mieux, un écart observé sur cet échantillon (perte du modèle - perte de référence)."""
    if n < config.MIN_N_EVIDENCE:
        return "preuves insuffisantes"
    if np.isnan(lo):
        return "preuves insuffisantes"
    if hi < 0:
        return "écart favorable vs référence simple sur ce test (marché non battu ni comparé ; non garanti durable)"
    if lo > 0:
        return "écart défavorable vs référence simple sur ce test"
    return "aucune différence démontrée avec la référence simple"
