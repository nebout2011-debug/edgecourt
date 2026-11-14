"""Ligne de commande : python -m edgecourt.cli <commande>."""
from __future__ import annotations

import argparse
import json
import sys

from . import config, pipeline


def _p(obj) -> None:
    print(json.dumps(obj, indent=2, ensure_ascii=False, default=str))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="edgecourt", description="EDGECOURT - recherche locale, simulation uniquement")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("demo", help="données synthétiques + parcours complet (étiqueté DÉMONSTRATION)")
    f = sub.add_parser("fetch", help="télécharge les sources gratuites autorisées vers la base « real »")
    f.add_argument("--sport", choices=[*config.SPORTS, "all"], default="all")
    r = sub.add_parser("run", help="valide, entraîne, évalue, simule")
    r.add_argument("--origin", choices=config.ORIGINS, default="real")
    r.add_argument("--sport", choices=[*config.SPORTS, "all"], default="all")
    rf = sub.add_parser("refit", help="nouvelle version du modèle pour les matchs à venir (résultats terminés connus)")
    rf.add_argument("--origin", choices=config.ORIGINS, default="real")
    rf.add_argument("--sport", choices=config.SPORTS, default="nfl")
    g = sub.add_parser("import-games", help="import CSV de matchs (droits d'usage requis)")
    g.add_argument("--sport", choices=config.SPORTS, required=True)
    g.add_argument("--csv", required=True)
    o = sub.add_parser("import-odds", help="import CSV de cotes horodatées")
    o.add_argument("--sport", choices=config.SPORTS, required=True)
    o.add_argument("--csv", required=True)
    o.add_argument("--source", default=None)
    o.add_argument("--origin", choices=config.ORIGINS, default="real")
    od = sub.add_parser("odds", help="relève les cotes d'avant-match (The Odds API, offre gratuite) des matchs à venir")
    od.add_argument("--sport", choices=[*config.SPORTS, "all"], default="all")
    a = ap.parse_args(argv)

    sports = lambda s: list(config.SPORTS) if s == "all" else [s]  # noqa: E731
    if a.cmd == "demo":
        _p({"import": pipeline.build_demo()})
        res = pipeline.run_all("demo")
        _p({sp: {k: v for k, v in r_.items() if k in ("modele_vainqueur_selectionne_sur_validation", "calibration", "effectifs", "journal", "statut")} for sp, r_ in res.items()})
    elif a.cmd == "fetch":
        _p(pipeline.fetch_real(sports(a.sport)))
    elif a.cmd == "run":
        res = pipeline.run_all(a.origin, sports(a.sport))
        _p({sp: {k: v for k, v in r_.items() if k in ("modele_vainqueur_selectionne_sur_validation", "calibration", "effectifs", "journal", "statut", "detail")} for sp, r_ in res.items()})
    elif a.cmd == "refit":
        r_ = pipeline.refit_upcoming(a.origin, a.sport)
        _p({k: r_.get(k) for k in ("version", "date_limite_donnees", "resultats_termines_utilises", "split", "modele_vainqueur_selectionne_sur_validation", "calibration", "a_venir", "journal", "statut", "detail")})
    elif a.cmd == "import-games":
        _p(pipeline.import_games_csv("real", a.sport, a.csv))
    elif a.cmd == "import-odds":
        _p(pipeline.import_odds_csv(a.origin, a.sport, a.csv, a.source))
    elif a.cmd == "odds":
        import streamlit as st  # la clé vient de .streamlit/secrets.toml, jamais du code ni de la ligne de commande

        from .data import odds_api
        _p(odds_api.refresh(st.secrets["ODDS_API_KEY"], "real", sports(a.sport)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
