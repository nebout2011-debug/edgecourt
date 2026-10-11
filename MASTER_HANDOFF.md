# MASTER_HANDOFF — EDGECOURT (mis à jour le 2026-10-11, fin du bloc 1)

## Décisions
- Python 3.11 (uv) dans `.venv`, dépendances figées (`requirements.txt`). Serveur Streamlit sur 127.0.0.1:8501.
- Soccer : **Premier League 2015/16** (StatsBomb Open Data) — seule saison de championnat complète ; volume très faible, assumé.
- NFL : nflverse-data `schedules/games.csv` (CC-BY-4.0), saisons 2010–2026 ; les colonnes de cotes du fichier ne sont **pas** utilisées (sans horodatage).
- NBA : adaptateur BALLDONTLIE prêt, **bloqué faute de clé** (Games annoncé gratuit avec clé ; requête sans clé = 401). Jamais testé contre l'API réelle.
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
- **Tests : 22 passés** (`.\scripts\test.ps1`, ≈ 50 s) : absence de fuite (propre score, même jour), invariance d'une prévision passée après ajout de résultats futurs, imports idempotents, sommes de probabilités, nuls/remboursements, refus des cotes futures, journal persistant, séparation démo/réel, parcours complet. Mutation vérifiée : une fuite injectée volontairement fait échouer le test.
- **Vérification réelle** : application démarrée et inspectée dans Chrome (Matchs NFL réel, Validation NFL réel, Données, Simulation en mode démo). Onglet « Analyse d'un match », filtres date/équipe et upload CSV **non** inspectés visuellement.
- Commit local : voir `git log` (aucun dépôt distant).

## Données réelles (au 2026-10-11)
- NFL : 4 635 lignes (4 428 terminés, 207 à venir). Test final 874 matchs : log loss logit calibré 0,640 vs référence simple 0,696 (écart −0,056, IC95 par semaines [−0,076 ; −0,036]) → « écart favorable vs référence simple, marché non battu ni comparé ». Total : −0,013 vs référence. Ne démontre **aucun** avantage économique.
- Soccer : 380 matchs ; 69 prévisions de test → **preuves insuffisantes**. Modèle choisi sur validation : Poisson, non calibré (n = 83).
- NBA : 0 match (clé absente) → « données insuffisantes ».
- Aucune cote réelle : aucun EV/ROI réel. La simulation chiffrée existe **uniquement** en démo avec cotes *fixtures* (teste règlements, ne prouve rien).

## Limites connues
- Prévisions prospectives NFL (207) produites par le modèle figé à fin d'entraînement (2019) + état Elo à jour ; réentraînement explicite non automatisé.
- Évaluation total/handicap sur une ligne de référence fixée sur l'entraînement (.5), pas sur les lignes réelles du marché.
- Retrait de marge proportionnel (biais favori/outsider ignoré). Pas de CLV. Quarts de points / handicaps asiatiques refusés.
- Générateur synthétique : forces redessinées chaque saison (Elo inter-saisons peu pertinent en démo).
- Parcours démo ≈ 1,5 min (boucles Python par match) ; acceptable, optimisable.
- Droit commercial non accordé sur StatsBomb ; attribution obligatoire en cas de publication.

## Blocages / besoins utilisateur
- NBA : créer un compte **gratuit** BALLDONTLIE, mettre la clé dans `.env`, relancer `.\scripts\fetch.ps1`, vérifier que Games répond en niveau Free.
- Cotes horodatées (CSV) pour obtenir un rendement évaluable ; aucune dépense nécessaire pour continuer.

## Prochaine action
1. Obtenir la clé NBA gratuite et exécuter `fetch.ps1`.
2. Fournir un CSV de cotes avec `observed_at` fiable (NFL ou NBA) pour la première comparaison au marché.
3. Ajouter plus de saisons soccer via CSV autorisé pour dépasser 200 prévisions de test.
