"""Cotes d'avant-match via The Odds API (offre gratuite : 500 crédits / mois). Prédiction uniquement, jamais de pari.

Règles :
- Aucun appel au chargement d'une page : `refresh()` n'est lancé que par la commande `edgecourt odds` ou le bouton admin.
- Un appel = 1 crédit (1 marché h2h × 1 région). On n'appelle que pour les ligues qui ont des prévisions à venir,
  au plus une fois toutes les MIN_HOURS par ligue, et jamais sous FLOOR crédits restants.
- Chaque appel ajoute des instantanés horodatés à `odds_snapshots.jsonl` (append-only) et au journal :
  cote au moment de la prévision = premier instantané du match ; cote de clôture = dernier instantané avant le coup d'envoi.
- Cote retenue par issue = médiane des bookmakers (aucun nom de bookmaker affiché) ; probabilité implicite = 1/cote
  normalisée sur les issues proposées (retrait de marge proportionnel).
La clé n'est jamais écrite, journalisée ni affichée ; les erreurs réseau sont relancées sans l'URL.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
import pandas as pd
import requests

from .. import config
from ..paper.journal import Journal, make_id

API = "https://api.the-odds-api.com/v4/sports/{key}/odds/"
SPORT_KEY = {"nfl": "americanfootball_nfl", "nba": "basketball_nba", "soccer": "soccer_epl"}
MIN_HOURS = 6   # ponytail: 3 ligues × 4 appels/jour × 30 = 360 crédits max/mois < 500
FLOOR = 10      # crédits restants sous lesquels on n'appelle plus
OUTCOMES = ("home", "draw", "away")

# Noms du moteur -> noms de l'API (seuls ceux qui diffèrent).
NFL = {"ARI": "Arizona Cardinals", "ATL": "Atlanta Falcons", "BAL": "Baltimore Ravens", "BUF": "Buffalo Bills",
       "CAR": "Carolina Panthers", "CHI": "Chicago Bears", "CIN": "Cincinnati Bengals", "CLE": "Cleveland Browns",
       "DAL": "Dallas Cowboys", "DEN": "Denver Broncos", "DET": "Detroit Lions", "GB": "Green Bay Packers",
       "HOU": "Houston Texans", "IND": "Indianapolis Colts", "JAX": "Jacksonville Jaguars", "KC": "Kansas City Chiefs",
       "LA": "Los Angeles Rams", "LAC": "Los Angeles Chargers", "LV": "Las Vegas Raiders", "MIA": "Miami Dolphins",
       "MIN": "Minnesota Vikings", "NE": "New England Patriots", "NO": "New Orleans Saints", "NYG": "New York Giants",
       "NYJ": "New York Jets", "PHI": "Philadelphia Eagles", "PIT": "Pittsburgh Steelers", "SEA": "Seattle Seahawks",
       "SF": "San Francisco 49ers", "TB": "Tampa Bay Buccaneers", "TEN": "Tennessee Titans", "WAS": "Washington Commanders"}
ALIAS = {"nfl": NFL, "nba": {"LA Clippers": "Los Angeles Clippers"},
         "soccer": {"AFC Bournemouth": "Bournemouth", "Brighton & Hove Albion": "Brighton and Hove Albion"}}


class OddsError(RuntimeError):
    pass


def snapshots_path(origin: str = "real") -> Path:
    return config.origin_dir(origin) / "odds_snapshots.jsonl"


def meta_path(origin: str = "real") -> Path:
    return config.origin_dir(origin) / "odds_meta.json"


def api_name(sport: str, team: str) -> str:
    return ALIAS.get(sport, {}).get(team, team)


def _nan(x) -> bool:
    return x is None or (isinstance(x, float) and math.isnan(x))


def implied(odds: dict) -> dict:
    """Probabilités implicites sans marge : (1/cote) / somme(1/cote) sur les issues proposées."""
    inv = {k: 1.0 / v for k, v in odds.items() if v and v > 1.0}
    s = sum(inv.values())
    return {k: v / s for k, v in inv.items()} if s else {}


def consensus(event: dict) -> tuple[dict, int]:
    """Cote médiane par issue (home/draw/away) sur les bookmakers qui proposent le marché h2h (dom. et ext. au moins)."""
    names = {event["home_team"]: "home", event["away_team"]: "away", "Draw": "draw"}
    per: dict[str, list[float]] = {}
    books = 0
    for b in event.get("bookmakers", []):
        m = next((m for m in b.get("markets", []) if m.get("key") == "h2h"), None)
        if not m:
            continue
        got = {names[o["name"]]: float(o["price"]) for o in m.get("outcomes", []) if o.get("name") in names}
        if "home" in got and "away" in got:
            books += 1
            for k, v in got.items():
                per.setdefault(k, []).append(v)
    return {k: float(np.median(v)) for k, v in per.items()}, books


def upcoming_predictions(sport: str, origin: str = "real", today=None) -> pd.DataFrame:
    """Prévisions à venir du moteur (dernière version actualisée, sinon lignes à venir du backtest), datées ≥ aujourd'hui."""
    d = config.origin_dir(origin)
    files = sorted(d.glob(f"predictions_{sport}_upcoming_*.parquet"), key=lambda f: (f.name, f.stat().st_mtime))
    if files:
        U = pd.read_parquet(files[-1])
    elif (d / f"predictions_{sport}.parquet").exists():
        P = pd.read_parquet(d / f"predictions_{sport}.parquet")
        U = P[P["status"] != "final"]
    else:
        return pd.DataFrame()
    today = pd.Timestamp.today().normalize() if today is None else pd.Timestamp(today)
    return U[U["game_date"] >= today].reset_index(drop=True)


def match_events(sport: str, events: list[dict], U: pd.DataFrame) -> list[tuple[dict, pd.Series]]:
    """Associe un événement de l'API à une prévision : mêmes équipes (dom./ext.), coup d'envoi UTC le jour du match ou le lendemain."""
    out = []
    for e in events:
        start = pd.Timestamp(e["commence_time"]).tz_convert("UTC").tz_localize(None).normalize()
        for _, r in U.iterrows():
            lag = (start - pd.Timestamp(r["game_date"]).normalize()).days
            if 0 <= lag <= 1 and api_name(sport, r["home_team"]) == e["home_team"] and api_name(sport, r["away_team"]) == e["away_team"]:
                out.append((e, r))
                break
    return out


def _int(x):
    try:
        return int(float(x))
    except (TypeError, ValueError):
        return None


def fetch(sport: str, key: str) -> tuple[list[dict], dict]:
    """Un appel à l'API (1 crédit). Retourne (événements, compteurs de crédits). L'URL (avec la clé) n'est jamais exposée."""
    if not key:
        raise OddsError("clé ODDS_API_KEY absente")
    try:
        r = requests.get(API.format(key=SPORT_KEY[sport]), timeout=20,
                         params={"apiKey": key, "regions": "eu", "markets": "h2h", "oddsFormat": "decimal", "dateFormat": "iso"})
    except requests.RequestException as ex:
        raise OddsError(f"réseau : {type(ex).__name__}") from None
    if r.status_code != 200:
        raise OddsError(f"The Odds API a répondu {r.status_code}")
    h = r.headers
    return r.json(), {"remaining": _int(h.get("x-requests-remaining")), "used": _int(h.get("x-requests-used"))}


def read_meta(origin: str = "real") -> dict:
    p = meta_path(origin)
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


def due(sport: str, meta: dict, now: pd.Timestamp) -> bool:
    last = meta.get("last_fetch", {}).get(sport)
    return last is None or now - pd.Timestamp(last) >= pd.Timedelta(hours=MIN_HOURS)


def snapshot_rows(sport: str, pairs, fetched_at: pd.Timestamp) -> list[dict]:
    rows = []
    for e, r in pairs:
        odds, books = consensus(e)
        if "home" not in odds or "away" not in odds:
            continue
        imp = implied(odds)
        rows.append({"sport": sport, "game_id": str(r["game_id"]), "event_id": str(e["id"]), "home_team": r["home_team"],
                     "away_team": r["away_team"], "game_date": str(pd.Timestamp(r["game_date"]).date()),
                     "commence_time": pd.Timestamp(e["commence_time"]).tz_convert("UTC").isoformat(),
                     "fetched_at": fetched_at.isoformat(), "n_books": books,
                     **{f"odds_{k}": odds.get(k) for k in OUTCOMES}, **{f"implied_{k}": imp.get(k) for k in OUTCOMES},
                     **{f"p_{k}": float(r[f"p_{k}_final"]) for k in OUTCOMES}})
    return rows


def refresh(key: str, origin: str = "real", sports=None, now=None, fetcher=fetch) -> dict:
    """Relève les cotes des ligues qui ont des prévisions à venir (si l'intervalle minimal est écoulé). Seul point d'appel réseau."""
    now = pd.Timestamp.now(tz="UTC") if now is None else pd.Timestamp(now)
    meta = read_meta(origin)
    report = {}
    for sp in sports or config.SPORTS:
        U = upcoming_predictions(sp, origin, today=now.tz_convert(None).normalize())
        if U.empty:
            report[sp] = "aucune prévision à venir : pas d'appel"
            continue
        if not due(sp, meta, now):
            report[sp] = f"déjà relevé il y a moins de {MIN_HOURS} h : pas d'appel"
            continue
        left = meta.get("credits", {}).get("remaining")
        if left is not None and left < FLOOR:
            report[sp] = f"moins de {FLOOR} crédits restants : pas d'appel"
            continue
        events, credits = fetcher(sp, key)
        rows = snapshot_rows(sp, match_events(sp, events, U), now)
        with snapshots_path(origin).open("a", encoding="utf-8", newline="\n") as fh:
            for row in rows:
                fh.write(json.dumps(row, ensure_ascii=False) + "\n")
        Journal(origin).append_many([{"id": make_id("odds", r["sport"], r["game_id"], r["fetched_at"]), "kind": "prediction_odds",
                                      "mode": "prospective", **r} for r in rows])
        meta.setdefault("last_fetch", {})[sp] = now.isoformat()
        meta["credits"] = credits
        report[sp] = f"{len(events)} événements, {len(rows)} associés à une prévision"
    meta_path(origin).write_text(json.dumps(meta, indent=2), encoding="utf-8")
    return report


def load_snapshots(origin: str = "real") -> pd.DataFrame:
    p = snapshots_path(origin)
    if not p.exists() or not p.read_text(encoding="utf-8").strip():
        return pd.DataFrame()
    S = pd.read_json(p, lines=True, dtype={"game_id": str, "event_id": str})
    for c in ("fetched_at", "commence_time"):
        S[c] = pd.to_datetime(S[c], utc=True)
    return S.sort_values(["sport", "game_id", "fetched_at"]).reset_index(drop=True)


def at_prediction(S: pd.DataFrame) -> pd.DataFrame:
    """Cote au moment de la prévision : premier instantané de chaque match."""
    return S.groupby(["sport", "game_id"], as_index=False).first() if len(S) else S


def latest(S: pd.DataFrame) -> pd.DataFrame:
    """Dernier instantané avant le coup d'envoi (devient la cote de clôture une fois le match commencé)."""
    if not len(S):
        return S
    pre = S[S["fetched_at"] < S["commence_time"]]
    return pre.groupby(["sport", "game_id"], as_index=False).last()


def closing(S: pd.DataFrame, now=None) -> pd.DataFrame:
    """Cote de clôture : dernier instantané avant le coup d'envoi, seulement pour les matchs déjà commencés."""
    now = pd.Timestamp.now(tz="UTC") if now is None else pd.Timestamp(now)
    L = latest(S)
    return L[L["commence_time"] <= now] if len(L) else L


def ev(p_model: float, odds: float) -> float:
    """EV = (probabilité du modèle × cote décimale) − 1."""
    return p_model * odds - 1.0


def signals(S: pd.DataFrame, n: int = 10, now=None) -> pd.DataFrame:
    """Matchs à venir où la probabilité du modèle s'écarte le plus de la probabilité implicite du marché (dernier instantané)."""
    now = pd.Timestamp.now(tz="UTC") if now is None else pd.Timestamp(now)
    L = latest(S)
    if not len(L):
        return pd.DataFrame()
    rows = []
    for r in L[L["commence_time"] > now].itertuples():
        best = None
        for k in OUTCOMES:
            m, p, o = getattr(r, f"implied_{k}"), getattr(r, f"p_{k}"), getattr(r, f"odds_{k}")
            if _nan(m) or _nan(o):
                continue
            if best is None or abs(p - m) > abs(best[1] - best[2]):
                best = (k, p, m, o)
        if best:
            rows.append({"sport": r.sport, "game_id": r.game_id, "home_team": r.home_team, "away_team": r.away_team,
                         "game_date": r.game_date, "outcome": best[0], "p_model": best[1], "p_market": best[2],
                         "odds": best[3], "gap": best[1] - best[2], "fetched_at": r.fetched_at})
    D = pd.DataFrame(rows)
    return D.reindex(D["gap"].abs().sort_values(ascending=False).index).head(n).reset_index(drop=True) if len(D) else D


def outcome(home_score, away_score) -> str:
    return "home" if home_score > away_score else "away" if home_score < away_score else "draw"


def market_report(S: pd.DataFrame, results: pd.DataFrame, now=None) -> dict:
    """Par ligue : log loss du modèle vs du marché (cotes au moment de la prévision) et CLV moyen sur l'issue choisie par le modèle.

    `results` : sport, game_id, home_score, away_score (matchs terminés). CLV = cote à la prévision / cote de clôture − 1.
    Les matchs dont l'issue n'est pas proposée par le marché (nul en NFL/NBA) sont exclus de la comparaison.
    """
    if not len(S) or not len(results):
        return {}
    A = at_prediction(S).merge(results, on=["sport", "game_id"])
    C = closing(S, now).set_index(["sport", "game_id"])
    out = {}
    for sp, g in A.groupby("sport"):
        ll_m, ll_k, clv = [], [], []
        for r in g.itertuples():
            y = outcome(r.home_score, r.away_score)
            pm = getattr(r, f"implied_{y}")
            if _nan(pm):
                continue
            ll_m.append(-math.log(max(getattr(r, f"p_{y}"), 1e-12)))
            ll_k.append(-math.log(max(pm, 1e-12)))
            pick = max(OUTCOMES, key=lambda k: getattr(r, f"p_{k}"))
            if (sp, r.game_id) in C.index:
                o0, o1 = getattr(r, f"odds_{pick}"), C.loc[(sp, r.game_id), f"odds_{pick}"]
                if not _nan(o0) and not _nan(o1):
                    clv.append(o0 / o1 - 1.0)
        if ll_m:
            out[sp] = {"n": len(ll_m), "logloss_modele": float(np.mean(ll_m)), "logloss_marche": float(np.mean(ll_k)),
                       "clv_moyen": float(np.mean(clv)) if clv else None, "n_clv": len(clv)}
    return out
