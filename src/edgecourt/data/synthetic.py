"""Données SYNTHÉTIQUES de démonstration. Jamais écrites dans la base « real » ; équipes et ids préfixés DEMO.

Aucune valeur sportive : sert uniquement à tester le parcours complet et les règlements (cotes = fixtures).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from ..models.markets import dist_from_params

BOOK = "FIXTURE-BOOK"


def _names(sport: str, n: int) -> list[str]:
    return [f"DEMO {sport.upper()} {i + 1:02d}" for i in range(n)]


def _round_robin(n: int, rng) -> list[list[tuple[int, int]]]:
    teams = list(range(n))
    rounds = []
    for r in range(n - 1):
        pairs = [(teams[i], teams[n - 1 - i]) for i in range(n // 2)]
        rounds.append([(a, b) if (i + r) % 2 == 0 else (b, a) for i, (a, b) in enumerate(pairs)])
        teams = [teams[0]] + [teams[-1]] + teams[1:-1]
    return rounds + [[(b, a) for a, b in rd] for rd in rounds]


def make_games(sport: str, seed: int = 11):
    """Retourne (games canoniques, vérité[game_id] = paramètres de distribution réels)."""
    rng = np.random.default_rng(seed + {"nba": 0, "nfl": 1, "soccer": 2}[sport])
    rows, truth = [], {}
    n_teams, seasons = {"nba": (30, 3), "nfl": (32, 4), "soccer": (20, 3)}[sport]
    names = _names(sport, n_teams)
    gid = 0
    for s in range(seasons):
        season = f"DEMO {2001 + s}"
        base = pd.Timestamp(f"{2001 + s}-09-01")
        st = rng.normal(0, 1, n_teams)          # force latente
        pace = rng.normal(0, 1, n_teams)
        att, dfn = rng.normal(0, 0.22, n_teams), rng.normal(0, 0.22, n_teams)
        if sport == "soccer":
            days = [(base + pd.Timedelta(days=7 * w), pairs) for w, pairs in enumerate(_round_robin(n_teams, rng))]
        elif sport == "nfl":
            days = []
            for w in range(17):
                perm = rng.permutation(n_teams)
                days.append((base + pd.Timedelta(days=7 * w), [(int(perm[2 * i]), int(perm[2 * i + 1])) for i in range(16)]))
        else:
            days = []
            for dd in range(165):
                perm = rng.permutation(n_teams)[:14]
                days.append((base + pd.Timedelta(days=dd), [(int(perm[2 * i]), int(perm[2 * i + 1])) for i in range(7)]))
        for date, pairs in days:
            for h, a in pairs:
                gid += 1
                ot = None
                if sport == "soccer":
                    lh, la = np.exp(0.28 + att[h] - dfn[a]), np.exp(0.0 + att[a] - dfn[h])
                    hs, as_ = int(rng.poisson(lh)), int(rng.poisson(la))
                    truth_p = {"kind": "poisson", "lh": float(lh), "la": float(la)}
                else:
                    mu_m = (3.0 if sport == "nba" else 2.2) + (4.0 if sport == "nba" else 3.5) * (st[h] - st[a])
                    mu_t = (220.0 + 4 * (pace[h] + pace[a])) if sport == "nba" else (44.0 + 2.0 * (pace[h] + pace[a]))
                    sd_m, sd_t = (12.0, 18.0) if sport == "nba" else (13.0, 13.0)
                    m = rng.normal(mu_m, sd_m)
                    t = max(rng.normal(mu_t, sd_t), 20.0)
                    hs, as_ = int(round((t + m) / 2)), int(round((t - m) / 2))
                    hs, as_ = max(hs, 0), max(as_, 0)
                    if sport == "nba" and hs == as_:
                        hs += int(rng.integers(1, 3)); ot = True  # prolongation : le nul est impossible
                    truth_p = {"kind": "normal", "mu_m": float(mu_m), "sd_m": sd_m, "mu_t": float(mu_t), "sd_t": sd_t}
                    if sport == "nfl":
                        ot = bool(abs(hs - as_) <= 3 and rng.random() < 0.06)
                g = f"demo-{sport}-{gid:05d}"
                rows.append({"game_id": g, "competition": f"DEMO {sport.upper()}", "season": season,
                             "game_date": date, "home_team": names[h], "away_team": names[a],
                             "home_score": hs, "away_score": as_, "status": "final", "overtime": ot,
                             "neutral": False, "game_type": "demo"})
                truth[g] = truth_p
    return pd.DataFrame(rows), truth


def make_fixture_odds(sport: str, games: pd.DataFrame, truth: dict, seed: int = 5) -> pd.DataFrame:
    """Cotes FIXTURE : probabilités vraies bruitées + marge 5 %. Quelques cotes tardives pour tester le refus."""
    rng = np.random.default_rng(seed)
    out = []

    def add(g, market, sel, line, odds, when, rule="standard"):
        out.append({"event_id": g, "bookmaker": BOOK, "market": market, "selection": sel, "line": line,
                    "odds_decimal": round(float(odds), 3), "observed_at": when.isoformat(), "settlement_rule": rule})

    def price(probs):
        q = np.clip(np.array(probs) * np.exp(rng.normal(0, 0.06, len(probs))), 1e-4, None)
        q /= q.sum()
        return 1.0 / (q * 1.05)

    for r in games.itertuples():
        d = dist_from_params(truth[r.game_id])
        when = r.game_date.normalize() - pd.Timedelta(hours=6)
        late = r.game_date.normalize() + pd.Timedelta(hours=3) if rng.random() < 0.03 else None
        ph, pd_, pa = d.one_x_two()
        if sport == "soccer":
            for when_i, flip in ((when, False), (late, True)):
                if when_i is None:
                    continue
                o = price([ph, pd_, pa][::-1] if flip else [ph, pd_, pa])
                for s, od in zip(("home", "draw", "away"), o):
                    add(r.game_id, "1x2", s, None, od, when_i)
            for line in (2.5, 2.0):
                po, pp, pu = (float(d.tp[d.tk > line].sum()), float(d.tp[d.tk == line].sum()), float(d.tp[d.tk < line].sum()))
                # prix de la ligne entière : la mise est remboursée au push, donc cote ajustée par p_win/(1-p_push)
                o = price([po / (1 - pp), pu / (1 - pp)])
                add(r.game_id, "total", "over", line, o[0], when)
                add(r.game_id, "total", "under", line, o[1], when)
        else:
            rule = "tie_refund" if sport == "nfl" else "standard"
            pw = ph / (ph + pa) if sport == "nba" else ph
            o = price([pw, 1 - pw]) if sport == "nba" else price([ph / (ph + pa), pa / (ph + pa)])
            add(r.game_id, "moneyline", "home", None, o[0], when, rule)
            add(r.game_id, "moneyline", "away", None, o[1], when, rule)
            tl = float(round(truth[r.game_id]["mu_t"]))
            po, pp, pu = (float(d.tp[d.tk > tl].sum()), float(d.tp[d.tk == tl].sum()), float(d.tp[d.tk < tl].sum()))
            o = price([po / (1 - pp), pu / (1 - pp)])
            add(r.game_id, "total", "over", tl, o[0], when)
            add(r.game_id, "total", "under", tl, o[1], when)
            sl = float(round(truth[r.game_id]["mu_m"]))
            w = float(d.mp[d.mk > sl].sum()); pu_ = float(d.mp[d.mk == sl].sum()); l = float(d.mp[d.mk < sl].sum())
            o = price([w / (1 - pu_), l / (1 - pu_)])
            add(r.game_id, "spread", "home", -sl, o[0], when)
            add(r.game_id, "spread", "away", sl, o[1], when)
    return pd.DataFrame(out)
