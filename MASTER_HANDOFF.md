# MASTER_HANDOFF — EDGECOURT (mis à jour le 2026-10-11, fin du bloc 2)

## Décisions
- Python 3.11 (uv) dans `.venv`, dépendances figées (`requirements.txt`). Serveur Streamlit sur 127.0.0.1:8501.
- Soccer : **Premier League 2015/16** (StatsBomb Open Data) — seule saison de championnat complète ; volume très faible, assumé.
- NFL : nflverse-data `schedules/games.csv` (CC-BY-4.0), saisons 2010–2026 ; les colonnes de cotes du fichier ne sont **pas** utilisées (sans horodatage).
- NBA : BALLDONTLIE Games (offre gratuite, clé gratuite dans `.env`) **importée et évaluée** ; accès gratuit confirmé le 2026-10-11 (HTTP 200, 5 req/min).
- Cutoff d'une prévision = début du jour du match (UTC) ; seule la date est fiable. Matchs du jour regroupés.
- Découpage fixe par date 60/20/20 (entraînement / validation+calibration / test final), persisté dans `artifacts/<origine>/split_<sport>.json`. Modèles appris (logit, ridge) **figés** à la fin de l'entraînement ; Elo, Poisson, référence se mettent à jour en ligne avec le passé.
- Sélection du modèle sur la validation seulement ; calibrateur de Platt sur la validation seulement, désactivé si n < 300.
- Démo et réel : deux bases DuckDB (`data/processed/edgecourt_{demo,real}.duckdb`) et deux dossiers d'artefacts.

## Réalisé et vérifié
- Données : connecteurs nflverse, StatsBomb, BALLDONTLIE, CSV générique ; imports idempotents (vérifié 2 exécutions : 0 insertion), rejets motivés, bruts conservés, checksum/couverture enregistrés.
- Modèles : référence en fréquences passées, Elo (K = 10/20/40), Poisson soccer avec lissage, logit régularisé + ridge (écart/total, variance sur résidus d'entraînement) NBA/NFL ; nul NFL traité (remboursé/perdu selon `settlement_rule`), prolongations NBA = pas de nul ; lignes entières → gain/remboursement/perte.
- Cotes : validation CSV, jointure temporelle stricte (cotes postérieures refusées et comptées), jointures ambiguës et lignes incompatibles refusées, retrait de marge proportionnel (même bookmaker/instant/ligne). Sans cotes : « rendement non évaluable ».
- Journal append-only chaîné (`journal.jsonl`) : config, prediction (backtest | prospective), result, settlement ; relecture idempotente, altération détectée.
- Rapport par sport : effectifs, Brier/log loss, calibration avec effectifs, IC par blocs de semaines ISO, configurations essayées (`configs_tried.jsonl`).
- UI (Streamlit) : Matchs, Analyse, Validation (réel et démo séparés), Simulation, Données (import CSV, statut connecteurs, licences).
- **Tests : 24 passés** (`.\scripts\test.ps1`, ≈ 50 s) : absence de fuite (propre score, même jour), invariance d'une prévision passée après ajout de résultats futurs, imports idempotents, sommes de probabilités, nuls/remboursements, refus des cotes futures, journal persistant, séparation démo/réel, parcours complet. Mutation vérifiée : une fuite injectée volontairement fait échouer le test.
- **Vérification réelle** : application démarrée et inspectée dans Chrome (Matchs NFL réel, Validation NFL réel, Données, Simulation en mode démo). Onglet « Analyse d'un match », filtres date/équipe et upload CSV **non** inspectés visuellement.
- Commit local : voir `git log` (aucun dépôt distant).

## Bloc 2 — modèle NFL actualisé pour les matchs à venir (2026-10-11)
- Commande : `.\.venv\Scripts\python.exe -m edgecourt.cli refit --origin real --sport nfl` (après `fetch`). Données re-téléchargées : 4 635 lignes, aucun changement depuis le premier import.
- **Version : `refit-2026-10-08-78d0d6ba24a9`** ; date limite des données **2026-10-08** (dernier résultat terminé connu, 4 428 matchs). Aucun résultat futur utilisé.
- Chronologie : entraînement ≤ 2022-10-23 (3 331 matchs) → calibration/sélection 2022-10-24 … 2026-10-08 (1 097 matchs, Platt calibré). Modèle retenu sur validation : logit (log loss validation 0,641 ; Elo20 0,656 ; référence 0,700). **Pas de test final pour cette version** : l'évaluation de référence reste celle du backtest.
- Séparation : le backtest (`report_nfl.json`, `predictions_nfl.parquet`, `split_nfl.json`, figé au 2019-12-29) est **inchangé octet pour octet** (empreintes SHA-256 vérifiées avant/après). La nouvelle version écrit `*_nfl_upcoming_20261008_78d0d6ba24a9.*`.
- Journal : 415 lignes **ajoutées** (207 × 2 marchés + configuration), mode `prospective`, champ `version` ; le préfixe existant (4 021 131 octets) est identique ; les anciennes prévisions prospectives du backtest restent en place, ids différents.
- Repos et forme (corrigé) : le repos d'un match planifié se calcule depuis le **calendrier connu** (match planifié précédent de l'équipe) et non plus depuis le dernier résultat (qui donnait 14 j plafonnés pour un match lointain). La forme n'utilise que des résultats terminés. Test dédié (`test_rest_and_form_use_only_currently_known_information`). Limite : la forme et Elo des matchs lointains n'intègrent pas les matchs intermédiaires, encore inconnus.
- UI : date limite, version, calibration et nombre de prévisions affichés ; badges « PRÉVISION À VENIR » (version) vs « BACKTEST » ; l'onglet Analyse sélectionne par défaut le prochain match à venir (ATL – BAL, 2026-10-11). Vérifié dans Chrome (Matchs et Analyse, NFL réel).
- Non fait / hors périmètre : cotes pour les matchs à venir (aucune) ; le backtest `run` régénère encore ses propres lignes « à venir » (jamais affichées comme version actuelle).

## Données réelles (au 2026-10-11)
- NFL : 4 635 lignes (4 428 terminés, 207 à venir). Test final 874 matchs : log loss logit calibré 0,640 vs référence simple 0,696 (écart −0,056, IC95 par semaines [−0,076 ; −0,036]) → « écart favorable vs référence simple, marché non battu ni comparé ». Total : −0,013 vs référence. Ne démontre **aucun** avantage économique.
- Soccer : 380 matchs ; 69 prévisions de test → **preuves insuffisantes**. Modèle choisi sur validation : Poisson, non calibré (n = 83).
- NBA : 6 605 matchs (saisons 2021–2025). Découpage chronologique : entraînement ≤ 2024-10-22 (3 964 matchs), validation/calibration 2024-10-23 … 2025-10-21 (1 321, Platt), **test final 2025-26 : 1 320 matchs**. Logit retenu sur validation. Test : log loss 0,609 (calibré 0,609) vs référence simple 0,687 (écart −0,078, IC95 par semaines [−0,107 ; −0,045]) ; total (ligne 225,5) : −0,025 vs référence. Ne compare **pas** au marché (aucune cote) : aucun avantage économique démontré. Aucun match à venir (saison 2026-27 non commencée / non importée).
- Aucune cote réelle : aucun EV/ROI réel. La simulation chiffrée existe **uniquement** en démo avec cotes *fixtures* (teste règlements, ne prouve rien).

## Limites connues
- Le réentraînement est une commande explicite (`refit`), jamais automatique ; à relancer après chaque import de nouveaux résultats.
- Évaluation total/handicap sur une ligne de référence fixée sur l'entraînement (.5), pas sur les lignes réelles du marché.
- Retrait de marge proportionnel (biais favori/outsider ignoré). Pas de CLV. Quarts de points / handicaps asiatiques refusés.
- Générateur synthétique : forces redessinées chaque saison (Elo inter-saisons peu pertinent en démo).
- Parcours démo ≈ 1,5 min (boucles Python par match) ; acceptable, optimisable.
- Droit commercial non accordé sur StatsBomb ; attribution obligatoire en cas de publication.

- NBA : débloquée (clé en place). Reste : cotes horodatées pour un rendement évaluable.
- NBA : créer un compte **gratuit** BALLDONTLIE, mettre la clé dans `.env`, relancer `.\scripts\fetch.ps1`, vérifier que Games répond en niveau Free.
- Cotes horodatées (CSV) pour obtenir un rendement évaluable ; aucune dépense nécessaire pour continuer.

## Prochaine action
1. Fournir un CSV de cotes avec `observed_at` fiable (NFL ou NBA) pour la première comparaison au marché.
2. Après le début de la saison NBA 2026-27 : ajouter la saison 2026 dans `config.NBA_SEASONS`, relancer `fetch.ps1`, puis une version « à venir » NBA (la commande `refit` existe pour NFL ; elle accepte `--sport nba`).
3. Ajouter plus de saisons soccer via CSV autorisé pour dépasser 200 prévisions de test.
