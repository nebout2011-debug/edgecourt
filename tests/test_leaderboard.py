"""« Quel modèle gagne ? » (La preuve) : classement par log loss de test croissante, valeurs lues dans la comparaison
du moteur (rapport → vainqueur.lignes), jamais codées en dur ; ★ = le plus bas."""
import json
import shutil
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest
from streamlit.util import calc_hash

from edgecourt import config

ROOT = Path(__file__).resolve().parents[1]
APP = str(ROOT / "src" / "edgecourt" / "ui" / "app.py")


def tables(at: AppTest) -> dict[str, list[list[str]]]:
    def walk(n, out):
        for c in getattr(n, "children", {}).values():
            out.append(c)
            walk(c, out)
        return out
    els = [e for e in walk(at._tree, []) if getattr(e, "type", "") == "bidi_component"]
    props = [json.loads(e.proto.json) for e in els]
    return {sp: p["props"]["rows"] for sp, p in zip(("nfl", "nba", "soccer"), [p for p in props if p["kind"] == "table"])}


def engine_test_rows(sp: str, artifacts: Path) -> list[tuple[str, float, int]]:
    """Lecture directe du rapport : lignes « test », version publiée de chaque modèle (calibrée si elle existe)."""
    lignes = json.loads((artifacts / "real" / f"report_{sp}.json").read_text(encoding="utf-8"))["vainqueur"]["lignes"]
    test = [l for l in lignes if l["periode"] == "test" and "non calibr" not in l["modele"]]
    names = {l["modele"] for l in test}
    return [(l["modele"], l["logloss"], l["n"]) for l in test if f'{l["modele"]} (calibré)' not in names]


def preuve() -> AppTest:
    at = AppTest.from_file(APP, default_timeout=120)
    at._page_hash = calc_hash("preuve")
    return at.run()


def check(rows: list[list[str]], engine: list[tuple[str, float, int]]):
    values = [float(r[1].replace(",", ".")) for r in rows]
    assert values == sorted(values)  # du plus bas (meilleur) au plus haut
    assert sorted(values) == sorted(round(ll, 3) for _, ll, _ in engine)  # chaque valeur vient du moteur
    assert [r[2].replace(" ", "") for r in rows] == [str(engine[0][2])] * len(rows)  # matchs de test du moteur
    best = min(engine, key=lambda e: e[1])
    assert rows[0][0].startswith("★ ") and sum(r[0].startswith("★") for r in rows) == 1  # un seul gagnant, en tête
    assert values[0] == round(best[1], 3)


def test_leaderboard_ranks_engine_models_by_test_log_loss():
    at = preuve()
    assert not at.exception and "Quel modèle gagne ?" in "".join(m.value for m in at.markdown)
    t = tables(at)
    for sp in ("nfl", "nba", "soccer"):
        check(t[sp], engine_test_rows(sp, config.ARTIFACTS))
    assert [r[0] for r in t["soccer"]] and not any("Logit" in r[0] for r in t["soccer"])  # pas de logit inventé en football
    assert t["nfl"][0][:2] == ["★ Logit (calibré) · publié", "0,640"] and t["nfl"][-1][:2] == ["Baseline", "0,696"]


@pytest.fixture
def altered_report(tmp_path, monkeypatch):
    """Copie des artefacts où la baseline NFL devient (artificiellement) la meilleure sur le test."""
    shutil.copytree(config.ARTIFACTS / "real", tmp_path / "real", ignore=shutil.ignore_patterns("journal.jsonl"))
    p = tmp_path / "real" / "report_nfl.json"
    r = json.loads(p.read_text(encoding="utf-8"))
    for l in r["vainqueur"]["lignes"]:
        if l["modele"] == "baseline" and l["periode"] == "test":
            l["logloss"] = 0.123
    p.write_text(json.dumps(r, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(config, "ARTIFACTS", tmp_path)
    return tmp_path


def test_leaderboard_follows_the_engine_data(altered_report):
    at = preuve()
    assert not at.exception
    rows = tables(at)["nfl"]
    check(rows, engine_test_rows("nfl", altered_report))
    assert rows[0][:2] == ["★ Baseline", "0,123"]  # le gagnant suit les données, pas un nom codé en dur
