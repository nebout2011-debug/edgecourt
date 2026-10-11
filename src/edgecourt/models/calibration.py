"""Calibrateur de Platt sur P(domicile gagne). Ajusté uniquement sur la période de calibration."""
from __future__ import annotations

import numpy as np
from sklearn.linear_model import LogisticRegression

from .. import config


def _logit(p):
    p = np.clip(np.asarray(p, dtype=float), 1e-6, 1 - 1e-6)
    return np.log(p / (1 - p))


class Calibrator:
    def __init__(self):
        self.model = None
        self.n = 0
        self.status = "non calibré"

    def fit(self, p_home, home_won) -> "Calibrator":
        y = np.asarray(home_won, dtype=int)
        self.n = len(y)
        if self.n < config.MIN_N_CALIBRATION or min(y.sum(), (1 - y).sum()) < 10:
            self.status = f"non calibré (effectif de calibration {self.n} < {config.MIN_N_CALIBRATION})"
            return self
        self.model = LogisticRegression(C=1e6, max_iter=1000).fit(_logit(p_home).reshape(-1, 1), y)
        self.status = f"calibré (Platt, n={self.n})"
        return self

    def apply(self, ph, pd_, pa):
        ph, pd_, pa = (np.asarray(x, dtype=float) for x in (ph, pd_, pa))
        if self.model is None:
            return ph, pd_, pa
        new_h = self.model.predict_proba(_logit(ph).reshape(-1, 1))[:, 1]
        rest = pd_ + pa
        share_d = np.where(rest > 0, pd_ / np.where(rest > 0, rest, 1), 0.0)
        return new_h, (1 - new_h) * share_d, (1 - new_h) * (1 - share_d)
