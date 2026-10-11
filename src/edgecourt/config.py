"""Chemins et constantes. Tout paramètre statistique est fixé ici, a priori, et journalisé."""
from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(os.environ.get("EDGECOURT_ROOT", Path(__file__).resolve().parents[2]))
RAW = ROOT / "data" / "raw"
PROCESSED = ROOT / "data" / "processed"
ARTIFACTS = ROOT / "artifacts"

SPORTS = ("nba", "soccer", "nfl")
SPORT_LABEL = {"nba": "NBA", "soccer": "Soccer", "nfl": "NFL"}
ORIGINS = ("real", "demo")  # jamais mélangés : un fichier DuckDB et un dossier d'artefacts par origine

MIN_N_EVIDENCE = 200   # en dessous : « preuves insuffisantes »
MIN_N_CALIBRATION = 300  # en dessous : modèle non calibré
EV_THRESHOLD = 0.03    # seuil de simulation fixé a priori (espérance par unité)
HORIZON_HOURS = 0      # cutoff = début du jour du match (UTC) - heures ; voir docs/DATA_SOURCES.md
SOCCER_COMPETITION = ("Premier League", "2015/2016")  # StatsBomb open data, 380 matchs complets
NFL_FIRST_SEASON = 2010
NBA_SEASONS = (2021, 2022, 2023, 2024, 2025)  # BALLDONTLIE, offre gratuite : 5 requêtes/min, ≈ 15 min d'import

# Paramètres Elo / modèles : fixés a priori. Les variantes essayées sont listées dans ELO_K_GRID.
ELO = {
    "nba": {"hfa": 70.0, "carry": 0.75},
    "nfl": {"hfa": 48.0, "carry": 0.75},
    "soccer": {"hfa": 65.0, "carry": 1.0},
}
ELO_K_GRID = (10.0, 20.0, 40.0)
POISSON_SHRINK_K = 5.0
FORM_WINDOW = 5
REST_CAP = 14


def origin_dir(origin: str) -> Path:
    p = ARTIFACTS / origin
    p.mkdir(parents=True, exist_ok=True)
    return p


def db_path(origin: str) -> Path:
    PROCESSED.mkdir(parents=True, exist_ok=True)
    return PROCESSED / f"edgecourt_{origin}.duckdb"
