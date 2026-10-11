"""État des équipes mis à jour match par match. Toute variable est calculée AVANT la rencontre.

`features(row)` ne lit que l'état (résultats passés). `update(row)` n'est appelé qu'après la prévision
du jour entier : les matchs d'une même date ne se voient donc jamais entre eux.
"""
from __future__ import annotations

import math
from collections import defaultdict, deque

import numpy as np

from .. import config

PRIOR_DRAW = {"nba": 0.0, "nfl": 0.003, "soccer": 0.26}  # règle : prolongations NBA => jamais de nul
PRIOR_W = 20.0
DEFAULT_SD = {"nba": (13.0, 20.0), "nfl": (13.5, 13.0), "soccer": (1.8, 1.6)}  # (écart, total) avant 30 matchs
ELO_MAIN = 20.0
TOTAL_WINDOW = 10
SHRINK = 3.0


class SportState:
    def __init__(self, sport: str):
        self.sport = sport
        cfg = config.ELO[sport]
        self.hfa, self.carry = cfg["hfa"], cfg["carry"]
        self.elo = {k: defaultdict(lambda: 1500.0) for k in config.ELO_K_GRID}
        self.team_season: dict[str, str] = {}
        self.last_date: dict = {}
        self.margins = defaultdict(lambda: deque(maxlen=config.FORM_WINDOW))
        self.totals = defaultdict(lambda: deque(maxlen=TOTAL_WINDOW))
        self.gf, self.ga, self.n = defaultdict(float), defaultdict(float), defaultdict(int)
        self.lg = dict(n=0, home=0.0, away=0.0, hw=0, dr=0, aw=0, margin=0.0, total=0.0, msq=0.0, tsq=0.0)

    # ---- ratings -----
    def _elo(self, k: float, team: str, season: str) -> float:
        r = self.elo[k][team]
        if team in self.team_season and self.team_season[team] != season:
            r = 1500.0 + self.carry * (r - 1500.0)  # régression partielle entre saisons (sans lire le futur)
        return r

    # ---- statistiques de ligue (passé seulement) -----
    def league(self) -> dict:
        lg, n = self.lg, self.lg["n"]
        sd_m0, sd_t0 = DEFAULT_SD[self.sport]
        mm = lg["margin"] / n if n else 0.0
        mt = lg["total"] / n if n else {"nba": 220.0, "nfl": 44.0, "soccer": 2.7}[self.sport]
        if n >= 30:
            sd_m = math.sqrt(max(lg["msq"] / n - mm * mm, 0.25))
            sd_t = math.sqrt(max(lg["tsq"] / n - mt * mt, 0.25))
        else:
            sd_m, sd_t = sd_m0, sd_t0
        dr = (lg["dr"] + PRIOR_W * PRIOR_DRAW[self.sport]) / (n + PRIOR_W)
        hw = (lg["hw"] + 10 * 0.55) / (n + 10) if self.sport != "soccer" else (lg["hw"] + 10 * 0.45) / (n + 10)
        mh = (lg["home"] + 10 * 1.5) / (n + 10) if self.sport == "soccer" else 0.0
        ma = (lg["away"] + 10 * 1.2) / (n + 10) if self.sport == "soccer" else 0.0
        return dict(n=n, mean_margin=mm, mean_total=mt, sd_margin=sd_m, sd_total=sd_t, draw_rate=dr,
                    home_win_rate=hw, away_win_rate=max(1 - hw - dr, 0.0), mu_home=mh, mu_away=ma)

    def features(self, row) -> dict:
        h, a, s = row.home_team, row.away_team, str(row.season)
        lg = self.league()
        hfa = 0.0 if bool(getattr(row, "neutral", False)) else self.hfa
        f: dict = {}
        for k in config.ELO_K_GRID:
            eh, ea = self._elo(k, h, s), self._elo(k, a, s)
            f[f"elo_diff{int(k)}"] = eh + hfa - ea
        f["elo_h"], f["elo_a"] = self._elo(ELO_MAIN, h, s), self._elo(ELO_MAIN, a, s)

        def rest(t):
            if t not in self.last_date:
                return 7
            return min((row.game_date - self.last_date[t]).days, config.REST_CAP)

        f["rest_h"], f["rest_a"] = rest(h), rest(a)
        f["rest_diff"] = f["rest_h"] - f["rest_a"]

        def form(t):
            m = self.margins[t]
            return sum(m) / (len(m) + SHRINK)

        f["form_h"], f["form_a"] = form(h), form(a)
        f["form_diff"] = f["form_h"] - f["form_a"]

        def pace(t):
            d = self.totals[t]
            return (sum(d) + SHRINK * lg["mean_total"]) / (len(d) + SHRINK)

        f["pace_h"], f["pace_a"] = pace(h), pace(a)
        f["n_h"], f["n_a"] = self.n[h], self.n[a]
        if self.sport == "soccer":
            m = max((lg["mu_home"] + lg["mu_away"]) / 2, 0.5)
            K = config.POISSON_SHRINK_K

            def att(t):
                return (self.gf[t] + K * m) / (self.n[t] + K) / m

            def dfn(t):
                return (self.ga[t] + K * m) / (self.n[t] + K) / m

            f["lam_h"] = lg["mu_home"] * att(h) * dfn(a)
            f["lam_a"] = lg["mu_away"] * att(a) * dfn(h)
            f["lam_h0"], f["lam_a0"] = lg["mu_home"], lg["mu_away"]
        f.update({f"lg_{k}": v for k, v in lg.items()})
        return f

    def update(self, row) -> None:
        h, a, s = row.home_team, row.away_team, str(row.season)
        hs, as_ = int(row.home_score), int(row.away_score)
        margin, total = hs - as_, hs + as_
        hfa = 0.0 if bool(getattr(row, "neutral", False)) else self.hfa
        score = 1.0 if margin > 0 else 0.0 if margin < 0 else 0.5
        for k in config.ELO_K_GRID:
            eh, ea = self._elo(k, h, s), self._elo(k, a, s)
            e = 1.0 / (1.0 + 10 ** (-(eh + hfa - ea) / 400.0))
            d = k * (score - e)
            self.elo[k][h], self.elo[k][a] = eh + d, ea - d
        self.team_season[h] = self.team_season[a] = s
        self.last_date[h] = self.last_date[a] = row.game_date
        self.margins[h].append(margin)
        self.margins[a].append(-margin)
        self.totals[h].append(total)
        self.totals[a].append(total)
        self.gf[h] += hs; self.ga[h] += as_; self.n[h] += 1
        self.gf[a] += as_; self.ga[a] += hs; self.n[a] += 1
        lg = self.lg
        lg["n"] += 1; lg["home"] += hs; lg["away"] += as_
        lg["hw"] += margin > 0; lg["aw"] += margin < 0; lg["dr"] += margin == 0
        lg["margin"] += margin; lg["total"] += total; lg["msq"] += margin * margin; lg["tsq"] += total * total
