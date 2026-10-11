# EDGECOURT

MVP personnel **local** (Windows, 127.0.0.1) de recherche prédictive sur NBA, Soccer et NFL. **Simulation uniquement** : aucun pari, dépôt ni compte bookmaker. **Aucun avantage ni taux de réussite n'est démontré.**

## Démarrage (PowerShell, depuis ce dossier)

```powershell
.\scripts\setup.ps1     # 1) initialise .venv (Python >= 3.11) et installe les dépendances figées
.\scripts\demo.ps1      # 2) parcours complet en DÉMONSTRATION SYNTHÉTIQUE (import, validation, entraînement, évaluation, simulation)
.\scripts\fetch.ps1     # 3) données réelles gratuites (NFL, soccer ; NBA si clé) puis évaluation
.\scripts\run.ps1       # 4) application sur http://127.0.0.1:8501
.\scripts\test.ps1      # tests (≈ 1 min)
```

## Clés et besoins gratuits

- NFL (nflverse) et soccer (StatsBomb Open Data) : aucune clé.
- **NBA** : clé **gratuite** BALLDONTLIE (endpoint Games, 5 requêtes/min). Créer un compte sur balldontlie.io, puis mettre `BALLDONTLIE_API_KEY=...` dans `.env` (copié depuis `.env.example` par `setup.ps1`), puis `.\scripts\fetch.ps1`. Sans clé : statut « bloqué » explicite, le reste fonctionne.
- Cotes : aucune source branchée ; import CSV manuel seulement.

## Importer vos données (ou via la page Données)

```powershell
.\.venv\Scripts\python.exe -m edgecourt.cli import-games --sport nba --csv chemin\matchs.csv   # modèle : samples\games_example.csv
.\.venv\Scripts\python.exe -m edgecourt.cli import-odds  --sport nba --csv chemin\cotes.csv    # modèle : samples\odds_example.csv
.\.venv\Scripts\python.exe -m edgecourt.cli run --origin real
```

Seulement des données dont vous avez les droits. Imports idempotents ; doublons, scores négatifs et incohérences rejetés ; fichiers bruts conservés dans `data/raw/`.
Cotes : `observed_at` obligatoire ; toute cote postérieure au cutoff de la prévision (début du jour du match, UTC) est refusée.

## Principes

Variables calculées avant le match, matchs d'un même jour regroupés ; modèles ajustés sur l'entraînement seul, sélection sur la validation, calibration sur la validation, test final intact ; journal append-only (`artifacts/<origine>/journal.jsonl`) ; démo et réel strictement séparés (deux bases DuckDB, deux dossiers d'artefacts). Sources et licences : `docs/DATA_SOURCES.md`. Bilan : `MASTER_HANDOFF.md`.
