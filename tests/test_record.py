"""« Le bilan en clair » (La preuve) : calculé sur les prédictions de test, jamais codé en dur ; sans test → « Pas encore de bilan »."""
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
LABELS = {"nfl": "NFL", "nba": "NBA", "soccer": "Premier League"}


def expected(P: pd.DataFrame) -> tuple[int, int]:
    """Calcul indépendant de celui de l'app : résultat réel vs issue la plus probable du modèle."""
    T = P[(P["segment"] == "test") & (P["status"] == "final")]
    act = T.apply(lambda r: "p_home_final" if r.home_score > r.away_score else "p_draw_final" if r.home_score == r.away_score
                  else "p_away_final", axis=1)
    return len(T), int((T[FINAL].idxmax(axis=1) == act).sum())


def card(x: int, y: int) -> tuple[str, str]:
    z = f"{100 * y / x:.1f}".replace(".", ",")
    th = lambda n: f"{n:,}".replace(",", " ")
    return f"{z} %", f"Sur les {th(x)} matchs de test, le modèle a eu raison {th(y)} fois ({z} %)"


def bilan(at: AppTest) -> dict[str, dict]:
    def walk(n, out):
        for c in getattr(n, "children", {}).values():
            out.append(c)
            walk(c, out)
        return out
    props = [json.loads(e.proto.json) for e in walk(at._tree, []) if getattr(e, "type", "") == "bidi_component"]
    cards = [p["props"] for p in props if p["kind"] == "metric_card"]
    return {c["label"]: c for c in cards if c["label"] in (*LABELS.values(), "Toutes ligues")}


def preuve() -> AppTest:
    at = AppTest.from_file(APP, default_timeout=120)
    at._page_hash = calc_hash("preuve")
    return at.run()


def test_record_matches_the_test_predictions():
    at = preuve()
    assert not at.exception and "Le bilan en clair" in "".join(m.value for m in at.markdown)
    cards, tot = bilan(at), [0, 0]
    for sp, label in LABELS.items():
        x, y = expected(pd.read_parquet(config.ARTIFACTS / "real" / f"predictions_{sp}.parquet"))
        tot[0] += x
        tot[1] += y
        assert (cards[label]["value"], cards[label]["description"]) == card(x, y)
    assert (cards["Toutes ligues"]["value"], cards["Toutes ligues"]["description"]) == card(*tot)


@pytest.fixture
def altered_artifacts(tmp_path, monkeypatch):
    """Copie des artefacts réels où : le test NFL prédit toujours « domicile », et le football n'a aucune prédiction."""
    real = tmp_path / "real"
    shutil.copytree(config.ARTIFACTS / "real", real, ignore=shutil.ignore_patterns("journal.jsonl"))
    (real / "predictions_soccer.parquet").unlink()
    P = pd.read_parquet(real / "predictions_nfl.parquet")
    t = P["segment"] == "test"
    P.loc[t, FINAL] = [1.0, 0.0, 0.0]
    P.to_parquet(real / "predictions_nfl.parquet")
    monkeypatch.setattr(config, "ARTIFACTS", tmp_path)
    return P


def test_record_follows_the_data_and_missing_league_has_no_record(altered_artifacts):
    at = preuve()
    assert not at.exception
    cards = bilan(at)
    T = altered_artifacts[(altered_artifacts["segment"] == "test") & (altered_artifacts["status"] == "final")]
    nfl = (len(T), int((T["home_score"] > T["away_score"]).sum()))  # toujours « domicile » → juste quand le domicile gagne
    assert nfl != expected(pd.read_parquet(ROOT / "artifacts" / "real" / "predictions_nfl.parquet"))  # vraiment différent du réel
    assert (cards["NFL"]["value"], cards["NFL"]["description"]) == card(*nfl)
    assert (cards["Premier League"]["value"], cards["Premier League"]["description"]) == ("—", "Pas encore de bilan")
    nba = expected(pd.read_parquet(config.ARTIFACTS / "real" / "predictions_nba.parquet"))
    assert (cards["Toutes ligues"]["value"], cards["Toutes ligues"]["description"]) == card(nfl[0] + nba[0], nfl[1] + nba[1])
