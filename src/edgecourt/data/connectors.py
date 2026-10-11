"""Connecteurs de données : nflverse (NFL), StatsBomb Open Data (soccer), BALLDONTLIE (NBA), CSV générique.

Chaque fetch_* retourne (DataFrame canonique, chemin brut, sha256, couverture). Les fichiers bruts sont conservés.
"""
from __future__ import annotations

import io
import json
import os
import time
from pathlib import Path

import pandas as pd
import requests

from .. import config
from . import store

UA = {"User-Agent": "EDGECOURT-local-research/0.1"}
NFL_URL = "https://github.com/nflverse/nflverse-data/releases/download/schedules/games.csv"
SB_BASE = "https://raw.githubusercontent.com/statsbomb/open-data/master/data"
BDL_URL = "https://api.balldontlie.io/v1/games"
NFL_TEAM_FIX = {"OAK": "LV", "SD": "LAC", "STL": "LA"}  # relocations : une franchise = un identifiant


class Blocked(Exception):
    """Source inaccessible : message = le seul besoin utilisateur."""


def _get(url: str, **kw) -> requests.Response:
    r = requests.get(url, headers={**UA, **kw.pop("headers", {})}, timeout=60, **kw)
    r.raise_for_status()
    return r


def fetch_nfl(first_season: int = config.NFL_FIRST_SEASON):
    content = _get(NFL_URL).content
    path, digest = store.save_raw("nflverse", "games.csv", content)
    raw = pd.read_csv(io.BytesIO(content))
    raw = raw[raw["season"] >= first_season]
    scored = raw["home_score"].notna() & raw["away_score"].notna()
    out = pd.DataFrame({
        "game_id": raw["game_id"], "competition": "NFL", "season": raw["season"].astype(str),
        "game_date": raw["gameday"], "home_team": raw["home_team"].replace(NFL_TEAM_FIX),
        "away_team": raw["away_team"].replace(NFL_TEAM_FIX),
        "home_score": raw["home_score"], "away_score": raw["away_score"],
        "status": scored.map({True: "final", False: "scheduled"}),
        "overtime": raw["overtime"].map(lambda v: None if pd.isna(v) else bool(v)).astype(object),
        "neutral": raw["location"].eq("Neutral"), "game_type": raw["game_type"],
    })
    cov = f"nflverse-data schedules/games.csv, saisons {first_season}-{raw['season'].max()}, {len(out)} matchs"
    return out, path, digest, cov


def fetch_statsbomb(competition: str = config.SOCCER_COMPETITION[0], season: str = config.SOCCER_COMPETITION[1]):
    comps = _get(f"{SB_BASE}/competitions.json").json()
    hit = [c for c in comps if c["competition_name"] == competition and c["season_name"] == season]
    if not hit:
        raise Blocked(f"compétition introuvable dans StatsBomb Open Data : {competition} {season}")
    cid, sid = hit[0]["competition_id"], hit[0]["season_id"]
    content = _get(f"{SB_BASE}/matches/{cid}/{sid}.json").content
    path, digest = store.save_raw("statsbomb", f"matches_{cid}_{sid}.json", content)
    rows = json.loads(content)
    out = pd.DataFrame({
        "game_id": [str(m["match_id"]) for m in rows], "competition": competition, "season": season,
        "game_date": [m["match_date"] for m in rows],  # date seule : l'heure locale n'est pas un horaire fiable
        "home_team": [m["home_team"]["home_team_name"] for m in rows],
        "away_team": [m["away_team"]["away_team_name"] for m in rows],
        "home_score": [m.get("home_score") for m in rows], "away_score": [m.get("away_score") for m in rows],
        "status": ["final" if m.get("home_score") is not None and m.get("away_score") is not None else "scheduled"
                   for m in rows],
        "overtime": None, "neutral": False, "game_type": "league",
    })
    cov = f"StatsBomb Open Data, {competition} {season}, {len(out)} matchs (temps réglementaire, scores finaux)"
    return out, path, digest, cov


def parse_balldontlie(pages: list[dict]) -> pd.DataFrame:
    games = [g for p in pages for g in p.get("data", [])]
    final = [str(g.get("status", "")).lower() == "final" or g.get("status_state") == "final" for g in games]
    return pd.DataFrame({
        "game_id": [str(g["id"]) for g in games], "competition": "NBA", "season": [str(g["season"]) for g in games],
        "game_date": [str(g["date"])[:10] for g in games],
        "home_team": [g["home_team"]["full_name"] for g in games],
        "away_team": [g["visitor_team"]["full_name"] for g in games],
        "home_score": [g["home_team_score"] if f else None for g, f in zip(games, final)],
        "away_score": [g["visitor_team_score"] if f else None for g, f in zip(games, final)],
        "status": ["final" if f else "scheduled" for f in final],
        "overtime": None, "neutral": False,
        "game_type": ["postseason" if g.get("postseason") else "regular" for g in games],
    })


def fetch_balldontlie(seasons: list[int], api_key: str | None = None, pause: float = 13.0):
    """Endpoint Games : gratuit avec clé (5 req/min). Sans clé => Blocked (adaptateur prêt, besoin = clé gratuite)."""
    api_key = api_key or os.environ.get("BALLDONTLIE_API_KEY") or _dotenv("BALLDONTLIE_API_KEY")
    if not api_key:
        raise Blocked("clé BALLDONTLIE manquante : créer un compte gratuit sur balldontlie.io puis renseigner "
                      "BALLDONTLIE_API_KEY dans .env (le endpoint Games est annoncé gratuit, 5 requêtes/min)")
    pages, cursor = [], None
    while True:
        params = [("per_page", 100)] + [("seasons[]", s) for s in seasons] + ([("cursor", cursor)] if cursor else [])
        r = requests.get(BDL_URL, params=params, headers={**UA, "Authorization": api_key}, timeout=60)
        if r.status_code in (401, 403):
            raise Blocked(f"BALLDONTLIE a refusé la clé (HTTP {r.status_code}) : vérifier la clé gratuite et l'accès Games")
        if r.status_code == 429:
            time.sleep(60)
            continue
        r.raise_for_status()
        page = r.json()
        pages.append(page)
        cursor = (page.get("meta") or {}).get("next_cursor")
        if not cursor:
            break
        time.sleep(pause)
    content = json.dumps(pages, ensure_ascii=False).encode("utf-8")
    path, digest = store.save_raw("balldontlie", "games.json", content)
    out = parse_balldontlie(pages)
    return out, path, digest, f"BALLDONTLIE Games, saisons {seasons}, {len(out)} matchs"


def _dotenv(name: str) -> str | None:
    p = config.ROOT / ".env"
    if p.exists():
        for line in p.read_text(encoding="utf-8").splitlines():
            if line.startswith(name + "=") and line.split("=", 1)[1].strip():
                return line.split("=", 1)[1].strip()
    return None


def read_games_csv(path: Path, sport: str):
    """Import CSV générique (données dont l'utilisateur a les droits). Colonnes : voir samples/games_example.csv."""
    content = Path(path).read_bytes()
    raw_path, digest = store.save_raw("csv", Path(path).name, content)
    df = pd.read_csv(io.BytesIO(content), encoding="utf-8-sig")
    df.columns = [c.strip().lower() for c in df.columns]
    if "status" not in df.columns:
        scored = df["home_score"].notna() & df["away_score"].notna()
        df["status"] = scored.map({True: "final", False: "scheduled"})
    df["sport"] = sport
    for c in ("season", "game_id"):
        if c in df.columns:
            df[c] = df[c].astype(str)
    return df, raw_path, digest, f"CSV utilisateur {Path(path).name}, {len(df)} lignes"


def status_table(st: "store.Store") -> pd.DataFrame:
    """Statut explicite des connecteurs, d'après les imports déjà réalisés."""
    imp = st.imports()
    rows = []
    for name, sport, src, need in [
        ("nflverse-data (CC-BY-4.0)", "nfl", "nflverse", "aucun"),
        ("StatsBomb Open Data (recherche locale)", "soccer", "statsbomb", "aucun (inscription gratuite recommandée par StatsBomb)"),
        ("BALLDONTLIE Games (offre gratuite)", "nba", "balldontlie", "clé gratuite dans .env (BALLDONTLIE_API_KEY)"),
    ]:
        sub = imp[imp["source"] == src] if len(imp) else imp
        if len(sub):
            last = sub.iloc[0]
            state = f"importé le {pd.Timestamp(last.retrieved_at):%Y-%m-%d %H:%M} UTC ({int(sub['accepted'].max())} matchs)"
        elif src == "balldontlie" and not (os.environ.get("BALLDONTLIE_API_KEY") or _dotenv("BALLDONTLIE_API_KEY")):
            state = "bloqué : clé absente"
        else:
            state = "jamais importé"
        rows.append({"connecteur": name, "sport": sport, "statut": state, "besoin utilisateur": need})
    rows.append({"connecteur": "CSV générique", "sport": "tous", "statut": "prêt", "besoin utilisateur": "fichier CSV avec droits d'usage"})
    rows.append({"connecteur": "Fournisseur de cotes", "sport": "tous", "statut": "non configuré (import CSV manuel seulement)",
                 "besoin utilisateur": "source de cotes horodatées, ajoutée plus tard"})
    return pd.DataFrame(rows)
