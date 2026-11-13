"""Journal : lignes issues des prédictions déployées (pas codées en dur), verdict ✅/❌ cohérent avec le résultat,
pagination serveur, filtre par ligue, message quand une ligue n'a aucune prévision terminée."""
import json
import shutil
from pathlib import Path

import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest
from streamlit.util import calc_hash

from edgecourt import config

ROOT = Path(__file__).resolve().parents[1]
APP = str(ROOT / "src" / "edgecourt" / "ui" / "app.py")
FINAL = ["p_home_final", "p_draw_final", "p_away_final"]
SPORTS = {"NFL": "nfl", "NBA": "nba", "Premier League": "soccer"}


def walk(n, out):
    for c in getattr(n, "children", {}).values():
        out.append(c)
        walk(c, out)
    return out


def table(at: AppTest) -> list[dict]:
    props = [json.loads(e.proto.json) for e in walk(at._tree, []) if getattr(e, "type", "") == "bidi_component"]
    t = next(p["props"] for p in props if p["kind"] == "data_table")
    keys = [c["key"] for c in t["columns"]]
    return [dict(zip(keys, r["cells"]), id=r["id"]) for r in t["rows"]]


def finished(artifacts: Path, sp: str) -> pd.DataFrame:
    p = artifacts / "real" / f"predictions_{sp}.parquet"
    if not p.exists():
        return pd.DataFrame()
    P = pd.read_parquet(p)
    return P[P["status"] == "final"].dropna(subset=["home_score", "away_score", *FINAL]).set_index("game_id")


def split_id(row_id: str) -> tuple[str, str]:
    sp, gid = row_id.removeprefix("s:").split("_", 1)
    return sp, gid


def journal(league: str | None = None) -> AppTest:
    at = AppTest.from_file(APP, default_timeout=120)
    at._page_hash = calc_hash("journal")
    at.run()
    if league:
        at.button_group[0].set_value(league).run()
    return at


def check_rows(rows: list[dict], artifacts: Path):
    """Chaque ligne affichée = une prédiction terminée du parquet ; prévision, résultat et verdict recalculés à part."""
    for row in rows:
        sp, gid = split_id(row["id"])
        r = finished(artifacts, sp).loc[gid]
        hs, as_ = int(r.home_score), int(r.away_score)
        names = (r.home_team, "Nul", r.away_team)
        top = max(range(3), key=lambda k: r[FINAL[k]])
        actual = 0 if hs > as_ else 1 if hs == as_ else 2
        assert row["Match"] == f"{r.home_team} – {r.away_team}"
        assert row["Prévision du modèle"].startswith(names[top] + " ")
        assert row["Résultat"] == f"{names[actual]} ({hs}–{as_})"
        assert row["Verdict"] == ("✅ Juste" if top == actual else "❌ Raté")


def test_journal_rows_come_from_the_deployed_predictions():
    at = journal()
    assert not at.exception
    total = sum(len(finished(config.ARTIFACTS, sp)) for sp in SPORTS.values())
    note = "".join(m.value for m in at.markdown)
    assert f"{total:,}".replace(",", " ") + " prévisions terminées · page 1 / " in note
    rows = table(at)
    assert len(rows) == 25  # pagination : jamais des milliers de lignes d'un coup
    check_rows(rows, config.ARTIFACTS)
    dates = [pd.Timestamp(finished(config.ARTIFACTS, sp).loc[gid].game_date) for sp, gid in (split_id(r["id"]) for r in rows)]
    assert dates == sorted(dates, reverse=True)  # le plus récent d'abord
    first = rows[0]["id"]
    next(b for b in at.button if b.label == "Plus anciennes →").click().run()
    page2 = table(at)
    assert len(page2) == 25 and first not in {r["id"] for r in page2}


@pytest.mark.parametrize("league", list(SPORTS))
def test_league_filter_and_verdicts(league):
    rows = table(journal(league))
    assert rows and {r["Ligue"] for r in rows} == {league}
    check_rows(rows, config.ARTIFACTS)


@pytest.fixture
def altered(tmp_path, monkeypatch):
    """Copie des artefacts : plus aucune prédiction de football, et le dernier match NFL au score inversé."""
    real = tmp_path / "real"
    shutil.copytree(config.ARTIFACTS / "real", real, ignore=shutil.ignore_patterns("journal.jsonl"))
    (real / "predictions_soccer.parquet").unlink()
    P = pd.read_parquet(real / "predictions_nfl.parquet")
    last = P[P["status"] == "final"]["game_date"].idxmax()
    P.loc[last, ["home_score", "away_score"]] = P.loc[last, ["away_score", "home_score"]].to_numpy()
    P.to_parquet(real / "predictions_nfl.parquet")
    monkeypatch.setattr(config, "ARTIFACTS", tmp_path)
    return tmp_path


def test_journal_follows_the_data_and_empty_league_says_so(altered):
    check_rows(table(journal("NFL")), altered)  # verdict recalculé sur le score modifié : rien n'est figé
    at = journal("Premier League")
    assert not at.exception
    assert "Aucune prévision terminée pour cette ligue pour l'instant." in "".join(m.value for m in at.markdown)
    assert not [e for e in walk(at._tree, []) if getattr(e, "type", "") == "bidi_component"
                and json.loads(e.proto.json)["kind"] == "data_table"]
