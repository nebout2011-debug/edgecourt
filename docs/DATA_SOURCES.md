# Sources de données — EDGECOURT

Vérification courte réalisée le **2026-10-11** (documentation et licences officielles consultées, pas de recherche exhaustive).
Distinction essentielle : la **licence du code** (celui d'EDGECOURT ou des paquets tiers) n'est pas la **licence des données**.
Les données brutes sont conservées sous `data/raw/<source>/` (ignorées par git ; ne pas redistribuer).

## NFL — nflverse-data (utilisée)

| Élément | Détail |
|---|---|
| URL | https://github.com/nflverse/nflverse-data/releases/download/schedules/games.csv |
| Licence des données | Dépôt `nflverse/nflverse-data` détecté par l'API GitHub comme **CC-BY-4.0** → attribution « nflverse » exigée. Le paquet `nflreadr` (code) est sous MIT, ce qui est distinct. Son README précise que les données NFL accédées restent soumises aux conditions d'utilisation de leurs propriétaires : usage ici = recherche personnelle locale, sans redistribution. |
| Couverture importée | Saisons 2010 → 2026 (matchs terminés et calendrier à venir), 4 635 lignes au 2026-10-11. Pas de play-by-play. |
| Champs utilisés | game_id, season, game_type, gameday, home/away team & score, location (Neutral), overtime |
| Limites | La colonne `gameday` est une date locale ; l'heure `gametime` n'est pas utilisée (fuseau non fiable). Relocalisations normalisées : OAK→LV, SD→LAC, STL→LA. |
| Non utilisé | Les colonnes de cotes (`moneyline`, `spread_line`, `total_line`) de games.csv : sans horodatage ni bookmaker identifiés, elles ne prouvent pas une exécution possible. Elles ne servent donc **pas** de cotes. |

## Soccer — StatsBomb Open Data (utilisée)

| Élément | Détail |
|---|---|
| URL | https://github.com/statsbomb/open-data (`data/matches/2/27.json`) ; accord : https://github.com/statsbomb/open-data/blob/master/LICENSE.pdf |
| Conditions (LICENSE.pdf, lu le 2026-10-11) | Usage « recherche / analyse ». **Interdit** : modifier/distribuer/revendre les données à un tiers (1.2.1) ; exploiter commercialement les données ou analyses dérivées (1.2.2). **Obligatoire** : créditer StatsBomb avec son logo pour toute publication d'analyse (1.4). StatsBomb demande une inscription (nom + e-mail) sur son site. Service « as is », peut être retiré à tout moment. |
| Compétition choisie | **Premier League 2015/2016** : 380 matchs, 20 équipes, calendrier complet — la seule combinaison large, complète et cohérente d'un championnat national. La Liga/Serie A/Ligue 1 2015/16 sont aussi complètes, mais une seule saison de chaque ; les autres saisons La Liga/Bundesliga ne contiennent que les matchs d'une équipe. |
| Limites | Une seule saison → très peu de prévisions de test (≈ 70) → statut « preuves insuffisantes ». Aucune couverture « actuelle ». Droit commercial **non** accordé. Scores = temps réglementaire (championnat, pas de prolongation). |
| Attribution à afficher | « Data provided by StatsBomb » + logo (media pack StatsBomb) en cas de publication ; usage actuel = local et privé. |
| Écartée | Football-Data.co.uk : conditions non retenues pour un entraînement automatisé. |

## NBA — BALLDONTLIE (adaptateur prêt, bloqué sans clé)

| Élément | Détail |
|---|---|
| URL | https://docs.balldontlie.io/ ; spec https://www.balldontlie.io/openapi/nba.yml |
| Accès | Une clé API est **requise** (requête sans clé testée le 2026-10-11 : HTTP 401). Le tableau « Account Tiers » de la documentation indique que **Teams, Players et Games sont accessibles au niveau Free** (5 requêtes/min, 0 $). Tout le reste (stats par match, cotes, props, etc.) est payant. Les essais 48 h exigent un moyen de paiement : **non utilisés**. |
| Statut | Aucune clé n'est disponible ici → **bloqué**, aucun test réel de l'endpoint n'a été fait. L'adaptateur (`edgecourt.data.connectors.fetch_balldontlie`) est écrit d'après la spec et testé sur une réponse fixture seulement. |
| Seul besoin utilisateur | Créer un compte **gratuit** sur balldontlie.io, copier la clé dans `.env` (`BALLDONTLIE_API_KEY=`), puis `.\scripts\fetch.ps1`. Vérifier alors que Games répond bien en niveau Free. |
| Alternative | Import CSV de données dont l'utilisateur détient les droits (`samples/games_example.csv`). |
| Limites | Les dates de l'API peuvent être exprimées en UTC : la date retenue est celle fournie. Prolongations non fournies par l'endpoint (laissées vides). |

## Cotes

Aucune source de cotes gratuite n'est branchée. Import manuel CSV (`samples/odds_example.csv`) avec horodatage `observed_at`, règle de règlement et ligne. Une cote observée **après** le cutoff de la prévision (début du jour du match, UTC) est refusée. Une cote de clôture sans horodatage fiable ne démontre pas qu'elle était exécutable à l'horizon choisi. Un fournisseur ultérieur s'ajoute comme simple producteur du même CSV.

## Données synthétiques

Générées par `edgecourt.data.synthetic` (graine fixe), équipes « DEMO … », stockées dans `data/processed/edgecourt_demo.duckdb` et `artifacts/demo/`. Jamais mélangées à la base `real`. Les cotes associées sont des *fixtures* servant à tester le règlement.
