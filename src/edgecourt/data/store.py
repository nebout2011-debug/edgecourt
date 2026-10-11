"""Stockage DuckDB (un fichier par origine) : validation, import idempotent, traçabilité."""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

from .. import config

GAME_COLS = [
    "sport", "game_id", "source", "competition", "season", "game_date", "home_team", "away_team",
    "home_score", "away_score", "status", "overtime", "neutral", "game_type",
]
KEY = ["sport", "source", "game_id"]
ODDS_COLS = ["event_key", "sport", "game_id", "source", "bookmaker", "market", "selection", "line", "odds",
             "observed_at", "settlement_rule", "import_id", "is_fixture"]

SCHEMA = """
CREATE TABLE IF NOT EXISTS games (
  sport VARCHAR, game_id VARCHAR, source VARCHAR, competition VARCHAR, season VARCHAR,
  game_date DATE, home_team VARCHAR, away_team VARCHAR, home_score INTEGER, away_score INTEGER,
  status VARCHAR, overtime BOOLEAN, neutral BOOLEAN, game_type VARCHAR, import_id VARCHAR,
  PRIMARY KEY (sport, source, game_id));
CREATE TABLE IF NOT EXISTS imports (
  import_id VARCHAR, sport VARCHAR, source VARCHAR, raw_file VARCHAR, sha256 VARCHAR, retrieved_at TIMESTAMP,
  rows_read INTEGER, accepted INTEGER, inserted INTEGER, updated INTEGER, unchanged INTEGER, rejected INTEGER,
  min_date DATE, max_date DATE, coverage VARCHAR, is_demo BOOLEAN);
CREATE TABLE IF NOT EXISTS rejects (import_id VARCHAR, row_ref VARCHAR, reason VARCHAR);
CREATE TABLE IF NOT EXISTS odds (
  event_key VARCHAR, sport VARCHAR, game_id VARCHAR, source VARCHAR, bookmaker VARCHAR, market VARCHAR,
  selection VARCHAR, line DOUBLE, odds DOUBLE, observed_at TIMESTAMP, settlement_rule VARCHAR,
  import_id VARCHAR, is_fixture BOOLEAN);
"""


def now_utc() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def save_raw(source: str, name: str, content: bytes) -> tuple[Path, str]:
    """Conserve le fichier brut sans jamais écraser (nom = horodatage + empreinte)."""
    digest = sha256_bytes(content)
    d = config.RAW / source
    d.mkdir(parents=True, exist_ok=True)
    path = d / f"{now_utc():%Y%m%dT%H%M%S}_{digest[:8]}_{name}"
    path.write_bytes(content)
    return path, digest


def event_key(sport: str, source: str, game_id: str) -> str:
    return f"{sport}:{source}:{game_id}"


def validate_games(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Retourne (acceptés, rejetés[row_ref, reason]). Rejette doublons, scores invalides, incohérences."""
    required = ["sport", "game_id", "source", "season", "game_date", "home_team", "away_team",
                "home_score", "away_score", "status"]
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise ValueError(f"colonnes manquantes : {missing}")
    df = df.copy().reset_index(drop=True)
    for c, default in (("overtime", None), ("neutral", False), ("game_type", ""), ("competition", "")):
        if c not in df.columns:
            df[c] = default
    df["game_date"] = pd.to_datetime(df["game_date"], errors="coerce")
    for c in ("home_score", "away_score"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    reasons: dict[int, str] = {}

    def flag(mask, why):
        for i in df.index[mask]:
            reasons.setdefault(i, why)

    flag(~df["sport"].isin(config.SPORTS), "sport inconnu")
    flag(df["game_date"].isna(), "date invalide")
    flag(df["game_id"].isna() | (df["game_id"].astype(str).str.strip() == ""), "identifiant manquant")
    flag(df["home_team"].isna() | df["away_team"].isna() | (df["home_team"] == df["away_team"]), "équipes invalides")
    scored = df["home_score"].notna() & df["away_score"].notna()
    flag(df["home_score"].notna() ^ df["away_score"].notna(), "score incomplet")
    flag(scored & ((df["home_score"] < 0) | (df["away_score"] < 0)), "score négatif")
    flag(scored & ((df["home_score"] % 1 != 0) | (df["away_score"] % 1 != 0)), "score non entier")
    flag(~df["status"].isin(["final", "scheduled"]), "statut invalide")
    flag((df["status"] == "final") & ~scored, "match final sans score")
    flag((df["status"] == "scheduled") & scored, "match planifié avec score")
    flag(df.duplicated(KEY, keep="first"), "doublon (clé sport/source/id)")
    ok = ~df.index.isin(list(reasons))
    flag(ok & df.duplicated(["sport", "game_date", "home_team", "away_team", "competition"], keep="first"),
         "doublon (même date et mêmes équipes)")
    bad = pd.DataFrame({"row_ref": [str(df.at[i, "game_id"]) for i in reasons], "reason": list(reasons.values())})
    good = df[~df.index.isin(list(reasons))].copy()
    good["game_date"] = good["game_date"].dt.date
    for c in ("home_score", "away_score"):
        good[c] = good[c].astype("Int64")
    good["season"] = good["season"].astype(str)
    good["game_id"] = good["game_id"].astype(str)
    return good[GAME_COLS], bad


def _canon(df: pd.DataFrame) -> pd.DataFrame:
    """Représentation textuelle stable pour comparer des lignes (dates, scores entiers, valeurs manquantes)."""
    out = pd.DataFrame(index=df.index)
    for c in GAME_COLS:
        s = df[c]
        if c == "game_date":
            out[c] = pd.to_datetime(s).dt.strftime("%Y-%m-%d")
        elif c in ("home_score", "away_score"):
            out[c] = pd.to_numeric(s, errors="coerce").fillna(-1).astype(int).astype(str)
        else:
            out[c] = s.astype(object).where(s.notna(), "").astype(str)
    return out


class Store:
    def __init__(self, origin: str):
        assert origin in config.ORIGINS
        self.origin = origin
        self.con = duckdb.connect(str(config.db_path(origin)))
        self.con.execute(SCHEMA)

    def close(self):
        self.con.close()

    def import_games(self, df: pd.DataFrame, sport: str, source: str, raw_file: str, sha256: str,
                     coverage: str, retrieved_at: datetime | None = None) -> dict:
        """Import idempotent : mêmes données => 0 insertion, 0 modification."""
        retrieved_at = retrieved_at or now_utc()
        df = df.copy()
        df["sport"], df["source"] = sport, source
        good, bad = validate_games(df)
        import_id = f"{sport}-{source}-{sha256[:10]}-{retrieved_at:%Y%m%dT%H%M%S}"
        existing = self.con.execute(
            "SELECT * EXCLUDE (import_id) FROM games WHERE sport=? AND source=?", [sport, source]).df()
        ins = upd = same = 0
        todo = good.iloc[0:0]
        if len(good):
            if len(existing):
                m = _canon(good).merge(_canon(existing), on=KEY, how="left", suffixes=("", "_old"), indicator=True)
                new = np.array(m["_merge"] == "left_only", dtype=bool)
                chg = np.zeros(len(m), dtype=bool)
                for c in [c for c in GAME_COLS if c not in KEY]:
                    chg = chg | (np.array(m[c] != m[c + "_old"], dtype=bool) & ~new)
                ins, upd, same = int(new.sum()), int(chg.sum()), int((~new & ~chg).sum())
                todo = good[new | chg]
            else:
                ins, todo = len(good), good
        if len(todo):
            todo = todo.assign(import_id=import_id)
            self.con.register("todo_df", todo)
            self.con.execute(f"INSERT OR REPLACE INTO games ({', '.join(GAME_COLS)}, import_id) "
                             f"SELECT {', '.join(GAME_COLS)}, import_id FROM todo_df")
            self.con.unregister("todo_df")
        for _, r in bad.iterrows():
            self.con.execute("INSERT INTO rejects VALUES (?,?,?)", [import_id, r.row_ref, r.reason])
        dmin = min(good["game_date"]) if len(good) else None
        dmax = max(good["game_date"]) if len(good) else None
        self.con.execute("INSERT INTO imports VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                         [import_id, sport, source, raw_file, sha256, retrieved_at, len(df), len(good), ins, upd, same,
                          len(bad), dmin, dmax, coverage, self.origin == "demo"])
        return {"import_id": import_id, "rows_read": len(df), "accepted": len(good), "inserted": ins,
                "updated": upd, "unchanged": same, "rejected": len(bad),
                "reject_reasons": bad["reason"].value_counts().to_dict() if len(bad) else {}}

    def games(self, sport: str) -> pd.DataFrame:
        df = self.con.execute("SELECT * EXCLUDE (import_id) FROM games WHERE sport=? ORDER BY game_date, game_id",
                              [sport]).df()
        df["game_date"] = pd.to_datetime(df["game_date"])
        return df

    def imports(self) -> pd.DataFrame:
        return self.con.execute("SELECT * FROM imports ORDER BY retrieved_at DESC").df()

    def rejects(self) -> pd.DataFrame:
        return self.con.execute("SELECT * FROM rejects").df()

    def import_odds(self, df: pd.DataFrame, import_id: str, is_fixture: bool = False) -> int:
        """Idempotent : seules les lignes absentes (clé complète) sont insérées. Retourne le nombre inséré."""
        if df.empty:
            return 0
        df = df.assign(import_id=import_id, is_fixture=is_fixture)
        self.con.register("odds_df", df[ODDS_COLS])
        before = self.con.execute("SELECT count(*) FROM odds").fetchone()[0]
        self.con.execute(
            "INSERT INTO odds SELECT d.* FROM odds_df d WHERE NOT EXISTS (SELECT 1 FROM odds o WHERE "
            "o.event_key=d.event_key AND o.bookmaker=d.bookmaker AND o.market=d.market AND o.selection=d.selection "
            "AND o.line IS NOT DISTINCT FROM d.line AND o.observed_at=d.observed_at AND o.odds=d.odds)")
        self.con.unregister("odds_df")
        return self.con.execute("SELECT count(*) FROM odds").fetchone()[0] - before

    def odds(self, sport: str | None = None) -> pd.DataFrame:
        if sport:
            return self.con.execute("SELECT * FROM odds WHERE sport=?", [sport]).df()
        return self.con.execute("SELECT * FROM odds").df()
