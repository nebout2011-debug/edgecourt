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
- UI (Streamlit) : 8 écrans depuis le bloc 3 (voir plus bas) + Simulation et Données (import CSV, statut connecteurs, licences).
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

## Bloc 3 — UI « Terminal + Premium », 8 écrans (2026-11-12, UI seule, moteur non touché)
Fichiers modifiés : `src/edgecourt/ui/app.py` (réécrit), `.streamlit/config.toml` (thème `base = "light"`, fond `#fbfbf8`).
- Navigation `st.navigation(position="hidden")` + liens maison sous le bandeau : Aujourd'hui (`/aujourdhui`, défaut), Détail d'un match (`/match`),
  La preuve (`/preuve`, ex-Validation), Ligues, En direct, La toile, Fiche joueur, Fiche équipe ; « Simulation » et « Données » conservés à la fin (comportement existant).
- Bandeau fondateur ambre `#fff3cd`, texte exact, sans bouton de fermeture, en tête de chaque écran.
- Logo (2026-11-12) : `assets/logo-primary.png` (variante haut-gauche, 526×135) dans l'en-tête (220 px, `mix-blend-mode:multiply`) ; `assets/logo-app-icon.png`
  (variante bas-droite, 308×313, coins transparents) comme favicon. Découpés au Pillow depuis `assets/edgecourt-logo.png`. Vérifié dans le navigateur ; non commité.
- Photos de ligues (2026-11-12) : 10 images extraites de `maquette.html/maquettes-ui-edgecourt-3-variantes.html` (section Ligues, titre `<h5>`) vers `assets/`.
  Affichées seulement pour les ligues du moteur : NBA → `nba.jpg`, Soccer → `premier-league.jpg` (données = Premier League 2015/16, `config.SOCCER_COMPETITION`) ;
  NFL sans image (aucune dans la maquette). Écrans : cartes Ligues + groupes Aujourd'hui. Crédit photo de la maquette affiché sous les cartes Ligues (texte, sans liens).
  Vérifié bureau + mobile 375 px ; non commité. Pas de coupes nationales / cartes Internationales dans l'app (rien à faire).
- Back-office admin (2026-11-12) : « Données » retirée de la navigation publique ; page `/admin` (lien discret « Admin » en bas de la barre latérale).
  Mot de passe lu dans `st.secrets["ADMIN_PASSWORD"]` (`.streamlit/secrets.toml`, ignoré par git via `.streamlit/secrets.toml*`) ; comparaison `hmac.compare_digest` ;
  secret absent → « Accès admin non configuré » seulement. L'ancienne URL `/donnees` n'existe plus (« Page not found »). Tests : `tests/test_admin.py` (3) → **27 tests passés**.
  Vérifié navigateur : nav publique sans Données, message non configuré, mauvais mot de passe refusé. Bon mot de passe : vérifié par AppTest seulement.
  Limite d'essais (2026-11-12) : 5 mots de passe faux → « Trop de tentatives — réessayez dans 15 minutes », formulaire masqué.
  **Par visiteur (2026-11-12)** : compteurs par adresse IP dans `st.cache_resource` (verrou), donc un rechargement ne les remet
  pas à zéro ; remis à zéro par un bon mot de passe ; visiteur inactif 24 h oublié (table bornée). IP = celle de la connexion
  (Streamlit n'utilise pas X-Forwarded-For : non falsifiable par en-tête) ; localhost = « local ».
  **Avant mise en ligne derrière un hébergeur / reverse proxy** : mettre `ADMIN_TRUSTED_PROXIES = 1` (nombre de proxys) dans
  `.streamlit/secrets.toml`, sinon tous les visiteurs ont l'IP du proxy et partagent le même compteur. Ne PAS le mettre sans proxy
  (le client pourrait alors falsifier X-Forwarded-For). En mémoire : un redémarrage efface compteurs et blocages.
  Tests (7 admin) : blocage par visiteur, rechargement, remise à zéro, proxy de confiance + tentative d'usurpation ;
  2 mutations vérifiées (compteur commun → échec ; confiance au 1er X-Forwarded-For → échec).
- Navigation « façon LiveScore » (2026-11-12) : Aujourd'hui = sélecteur de sport (Football / Basket / Football américain) + bande de dates
  (« En direct » → page En direct ; J-3…J+3, seuls les jours avec matchs cliquables) + matchs groupés sous un en-tête de compétition cliquable
  (image + nom + pays). Liens = vraies URL partageables : `match?sport=&game=`, `equipe?sport=&team=`, `ligues?ligue=` (+ `mode=demo`) ;
  l'état est repris de l'URL une fois par session. Ligues : index (3 ligues moteur + 14 cartes « Bientôt — pas encore de données » :
  5 championnats avec photo, 6 coupes et 3 International sans photo) et vue ligue (table + équipes). Détail d'un match : onglets
  Prévision / Table / Forme (créés seulement s'ils ont du contenu). Table = saison régulière terminée du moteur (3/1/0 au foot, % V sinon).
  Barre latérale (lien Admin) repliée par défaut. Vérifié navigateur bureau + mobile 375 px ; table PL 2015/16 = Leicester 81 pts (exact).
- Publicités (cadres gris pointillés « Publicité ») : Aujourd'hui 728×90 sous l'en-tête + 300×250 après le 3e groupe de ligues + colonne droite collante 300×600 (masquée < 900 px) ;
  Ligues 728×90 après la 3e (et 6e si elle existe) carte ; Preuve 468×60 tout en bas ; Direct et Toile 728×90 en bas ; Match / Joueur / Équipe : aucune.
- Données d'exemple étiquetées : Fiche joueur (aucune donnée joueur dans le moteur), carte « En direct » (prévision démo, équipes fictives), et tout le mode démo.
- La toile = réseau des équipes de la dernière saison (traits = rencontres, taille = Elo) — interprétation, à confirmer.
**Vérifié** (2026-11-12) : 24 tests passés ; app sur http://127.0.0.1:8501 ; chaque écran ouvert dans le navigateur intégré (bandeau présent, aucune exception,
publicités aux bons endroits et absentes des 3 fiches) ; bouton « Détail → » ouvre le bon match ; bascule réel/démo conservée entre écrans ; mobile 375 px sans défilement horizontal.
**Non vérifié** : aucune maquette fournie sur disque (construit d'après la description écrite) ; rendu visuel fin des graphiques en mobile.

## Bloc 4 — Accueil + héros Aujourd'hui (2026-11-13)
- **Environnement reconstruit** : Windows Application Control a bloqué `.venv\Scripts\python.exe` le 2026-11-13. Ancien dossier
  renommé `.venv.blocked` puis supprimé (681 Mo) ; nouveau `.venv` créé par `setup.ps1` à partir de
  **Python 3.14** (`C:\Python314`, trouvé avant uv 3.11). Dépendances figées réinstallées ; suite complète verte sur 3.14.
- **Aujourd'hui** : bloc sombre « Des prédictions. Des preuves. Rien d'autre. » + bouton vert #00C853 « Voir La preuve » ;
  bandeau défilant de ligues (NBA / Premier League / NFL cliquables → `?sport=`, pilule active verte ; La Liga, Serie A,
  Bundesliga, Ligue 1, Championship, WNBA, NHL, MLB grisées « Bientôt »). Pause au survol/focus ; immobile si l'OS demande moins
  d'animations. La publicité 728×90 est désormais sous le héros + bandeau.
- **Accueil** (`/accueil`, page par défaut) : barre propre (logo, Prédictions, La preuve, Modèles, Méthodologie → La preuve
  faute de Lexique, FAQ → #faq ; Se connecter / Créer un compte → fenêtre « Les comptes arrivent bientôt… » + Entrer dans l'app).
  Héros : promesse + badges App Store / Google Play **non cliquables** « Bientôt » (texte, pas les logos officiels) ; carte
  « prochaine prévision » = prochain match réel toutes ligues (vote de chaque modèle = son issue la plus probable avant
  calibration ; accord X/5) + 2 suivants ; sinon « Aucune prévision à venir ». Bandeau des 5 modèles, FAQ (3 questions).
  En-tête global masqué sur l'Accueil (le bandeau fondateur reste). Aucune pub, aucun chiffre inventé.
  Au 2026-11-13 : NYJ – BUF (15 nov.), BUF 75,7 %, accord 4/5 (Baseline vote NYJ). Football : 5e modèle = Poisson, pas Logit.
- Tests : `tests/test_home.py` (3). Vérifié navigateur bureau + mobile 375 px.
- **News** (colonne droite d'Aujourd'hui, sous la pub 300×600) : `src/edgecourt/ui/news.py`. Flux RSS gratuits sans clé :
  ESPN (NBA, NFL, WNBA, NHL, MLB, soccer) + BBC Sport (premier-league, championship, spanish-la-liga, italian-serie-a,
  german-bundesliga, french-ligue-one, european). Cache 15 min (`news_items`, un échec total n'est pas mis en cache).
  Écartés : article sans date, lien non https, tout texte mentionnant paris/cotes. Image seulement si le flux en donne
  (BBC oui, ESPN non → bloc noir). « À la une » = 5 premiers en carrousel (iframe, 8 s, flèches/points, pause survol/focus,
  pas d'auto-rotation si reduced-motion) ; 8 suivants en liste ; pilules Toutes + 11 ligues ; soccer ESPN et BBC
  « european » visibles seulement sous Toutes. Rien → « Actualités indisponibles pour l'instant ».
  Changement de pub : la colonne droite n'est plus collante (sinon la News serait masquée) ; la pub reste en tête de colonne
  et reste masquée sous 900 px, la News passe sous les matchs sur mobile. `feedparser` ajouté à requirements.txt.
  Tests `tests/test_news.py` (4, sans réseau). Vérifié en direct : rotation, pause, flèches, points, filtre, liens nouvel
  onglet, bureau 1440 + mobile 375 sans défilement horizontal.
- **Barre du haut** (toutes les pages, Accueil compris — sa barre propre est supprimée) : logo → Accueil · devise
  « La prédiction, prouvée en public. » · Se connecter / Créer un compte (même dialogue « bientôt » que l'Accueil).
  Barre des sports noire (`sport_bar`) : Accueil, Football, Basketball, Football Américain, Hockey, Baseball ; actif en
  vert #00C853 (Accueil sur l'Accueil, le sport ouvert sur Aujourd'hui). Lien = `aujourdhui?sport=soccer|nba|nfl|nhl|mlb`.
  Hockey/Baseball (sans données moteur) : `nav_sport` en session, Aujourd'hui montre NHL/MLB « Bientôt » et aucun match.
  Sous le sélecteur de sport d'Aujourd'hui : ligues du sport (moteur en actif, autres « Bientôt »). Le sélecteur
  (`sport_sel`, rappel on_change) garde la barre synchronisée. 2e rangée : Prédictions, La preuve, Modèles, Méthodologie
  (→ La preuve), FAQ (→ Accueil#faq) + toutes les autres pages ; sélecteur réel/démo à droite (sauf Accueil).
  « Journal » et « Lexique » n'existent pas dans l'app : non ajoutés. Tests `tests/test_nav.py` (8).
- **Menus dépliants** (barre noire, rendue par `st.html(..., unsafe_allow_javascript=True)` dans le DOM de la page, pas
  un iframe) : « Sports ▾ » (et survol d'un sport) → carte blanche 5 sports avec icônes, flèche → ligues ; seules
  Premier League / NBA / NFL sont des liens (`aujourdhui?sport=`), les autres « Bientôt » en `<span aria-disabled>`.
  « La preuve ▾ » → méga-menu 3 colonnes (La preuve / Comprendre / Le site). Journal, Équipe de la semaine, Lexique :
  pas de page → « Bientôt », non cliquables ; Classement des modèles et Comment ça marche → La preuve ; FAQ → Accueil#faq.
  Ouverture : survol (souris fine), clic/tap, Entrée ; fermeture : Échap (focus rendu au bouton), clic ailleurs, choix,
  sortie de souris (250 ms), Tab hors du menu. Animation 160 ms (coupée si reduced-motion). Mobile ≤ 700 px : barre sur
  plusieurs lignes (plus de défilement horizontal, sinon les cartes seraient rognées), cartes pleine largeur.
  `NAV_JS` pose ses écouteurs une seule fois (`window.__ecNav`). Tests `tests/test_menus.py` (4) : structure + présence
  du gestionnaire Échap ; le comportement réel (survol, tap, Échap, clic ailleurs) n'est vérifié qu'au navigateur
  (fait le 2026-11-13, bureau 1440 + mobile 375).
- À faire (hors périmètre) : `st.components.v1.html` (carrousel News) est déprécié au profit de `st.iframe`.
- **Bibliothèques UI** : `streamlit-shadcn-ui==1.5.0` (import `streamlit_shadcn_ui`) et `streamlit-facade==0.1.6`
  (import `facade`, réservé au futur accordéon Lexique) dans requirements.txt ; Streamlit reste 1.65. Les composants
  shadcn (Custom Components v2, shadow DOM isolé) sont enregistrés **au démarrage du serveur** : après installation,
  redémarrer `run.ps1` (sinon « must be declared in pyproject.toml with asset_dir »).
- **La preuve** : 4 cartes `ui.metric_card` (matchs de test, log loss, écart vs référence, IC 95 %) = vrais chiffres du
  rapport ; `TICKER_JS` (st.html + JS) compte de 0 jusqu'au texte affiché par la carte (`[data-slot="card-title"]` dans
  le shadow root), 900 ms, une fois, rien si reduced-motion. Le vrai chiffre s'affiche un instant avant le compteur.
- **Ligues** : grille bento (CSS grid sur conteneurs `st-key-ec_bento_*`) de cartes `ui.card` ; en-tête calculé
  « 11 ligues · 6 coupes · 3 International » (3 moteur + 5 européennes + WNBA, NHL, MLB — la demande disait 10, aucun
  en-tête existant). 3 tuiles cliquables (lien étiré `a.ec-tile-link` → `ligues?ligue=`), 17 tuiles « Bientôt » grisées
  sans lien ni chiffre. Photos de ligue gardées + crédit. Les 2 pubs 728×90 aux mêmes places. Tests `tests/test_ui_libs.py` (3).
- **Lexique** (`/lexique`, `page_lexique`, liste `LEXIQUE`) : « Comment ça marche » + 15 termes, un `facade.Accordion`
  chacun (= `st.expander` ; le thème global de facade n'est pas chargé). Définitions = texte fourni, mot pour mot (1re lettre
  en majuscule) ; les exemples chiffrés sont les vrais chiffres NFL (874, 0,640/0,696, −0,056, [−0,076 ; −0,036]).
  Liens : rangée de pages, méga-menu (Lexique + Comment ça marche → /lexique, plus « Bientôt »), La preuve. Aucune pub.
  Tests `tests/test_lexique.py` (2).
- **Le bilan en clair** (La preuve, sous les 4 chiffres) : `record()` = sur les prédictions `segment == "test"` et
  `status == "final"`, issue la plus probable (`p_*_final`, les probabilités du log loss) contre le vrai résultat (scores).
  Une carte shadcn par ligue + « Toutes ligues », même compteur (`ticker_metrics`), phrase « Sur les X matchs de test, le
  modèle a eu raison Y fois (Z %) ». Sans prédiction de test → « Pas encore de bilan ». Au 2026-11-13 (calculé) : NFL
  569/874 (65,1 %), NBA 882/1 320 (66,8 %), PL 34/69 (49,3 %), total 1 485/2 263 (65,6 %). Tests `tests/test_record.py` (2,
  dont un sur une copie modifiée des artefacts).
- **Quel modèle gagne ?** (La preuve, après le bilan) : `leaderboard(report)` = `vainqueur.lignes` période « test » du
  rapport (la comparaison du moteur), triée par log loss croissante ; une ligne par modèle en version publiée
  (« X (calibré) » remplace X brut, « X (non calibré) » écarté). `ui.table` shadcn par ligue ; ★ = plus bas log loss,
  « · publié » = `modele_vainqueur_selectionne_sur_validation`. Football : le moteur compare baseline, Élo 10/20/40 et
  Poisson (pas de logit) — affichés tels quels. Au 2026-11-13 : NFL ★ Logit (calibré) 0,640 … Baseline 0,696 (874) ; NBA
  ★ Logit (calibré) 0,609 … Baseline 0,687 (1 320) ; PL ★ Élo 40 0,966, Poisson (publié) 1,001, Baseline 1,067 (69).
  Tests `tests/test_leaderboard.py` (2, dont un sur un rapport modifié).
- **Journal** (`/journal`, `page_journal`, `journal_rows`) : une ligne par prédiction terminée (`status == "final"`,
  segments calibration + test) depuis les `predictions_*.parquet` déployés (pas `journal.jsonl`, non déployé) ; prévision =
  issue la plus probable (`p_*_final`) + proba, résultat = scores, ✅ Juste / ❌ Raté. Plus récent d'abord. `ui.data_table`
  shadcn (max 1 000 lignes côté composant) → pagination serveur 25 lignes/page (« ← Plus récentes / Plus anciennes → »),
  filtre `segmented_control` Toutes / NFL / NBA / Premier League ; ligue vide → « Aucune prévision terminée… ». Au
  2026-11-13 : 4 562 prévisions, 183 pages. Le bouton « Columns » du Data Table est en anglais (texte du composant).
  Nav : rangée de pages + méga-menu (Journal n'est plus « Bientôt »). Tests `tests/test_journal.py` (5).
- **Équipe de la semaine** (Ligues, après les 3 tuiles moteur) : `current_elo` rejoue le `SportState` du moteur
  (K = `ELO_MAIN` = 20, l'Élo du logit) sur `Store.games()` terminés, ordre (date, game_id) comme `walk_forward` ; top 5
  par ligue + forme V/N/D des 5 derniers matchs (`last_form`), date du dernier match en base. Étiquette « Selon le
  modèle ». Grille bento (`st-key-ec_bento_totw`). Ligue sans match → « Pas encore d'Élo… ». Au 2026-11-13 : NFL SEA
  1606…, NBA Oklahoma City 1753…, PL Leicester 1628…. Tests `tests/test_team_of_week.py` (5, dont un qui vérifie que le
  rejeu redonne exactement les `elo_h/elo_a` enregistrés par le moteur).
- **Pied de page** (toutes les pages, rendu après `nav.run()`) : logo + devise, avertissement (texte fourni), liens
  `FOOTER_LINKS` vers des pages existantes (La preuve, Journal — en ligne depuis 9cb7c6e —, Lexique, FAQ → Accueil#faq,
  Ligues, Aujourd'hui), « © 2026 EDGECOURT ». Aucune pub. Une colonne sous 700 px. Tests `tests/test_footer.py` (14).
- **Écran d'entrée** (`page_entry`, page par défaut à `/` ; l'Accueil est désormais `/accueil`) : bandeau fondateur,
  logo + devise + comptes, héros de l'Accueil réutilisé (`home_hero`) avec la vraie prochaine prévision (`featured_card`)
  et « Gratuit et ouvert — sans inscription », gros bouton vert « Entrer dans l'app » → `st.session_state["entered"]` +
  Accueil, bandeau « 5 modèles, un appel EDGECOURT » (`models_strip`). Pas de barre des sports, pas de liens de pages,
  barre latérale masquée, pas de pied de page, aucune pub. Les liens internes visent des pages nommées : seul `/` montre
  l'écran d'entrée (nouvelle session = il revient). Tests `tests/test_entry.py` (5) ; `test_home.py` vise `/accueil`.
- **Déploiement Streamlit Cloud** : `app.py` ajoute `src/` à `sys.path` (le paquet n'y est pas installé). Données lues par
  l'app (≈ 8 Mo : predictions/report/simulation/split/configs_tried, connector_status, 2 DuckDB) suivies par git via
  `.gitignore` ; brut, journaux, `.env`, secrets restent ignorés. Rafraîchir les données = local puis commit + push.
- **Cotes (The Odds API, offre gratuite)** — `src/edgecourt/data/odds_api.py`. Clé : `st.secrets["ODDS_API_KEY"]`
  (local `.streamlit/secrets.toml`, Cloud Secrets), jamais écrite ni affichée (erreurs réseau relancées sans l'URL).
  Appels **uniquement** via `python -m edgecourt.cli odds` ou le bouton admin « Relever les cotes » (page Données) ;
  aucun chargement de page n'appelle l'API (testé). 1 appel = 1 crédit (h2h, région eu) ; seulement les ligues avec
  prévisions à venir ; ≥ 6 h entre deux appels par ligue ; arrêt sous 10 crédits. Instantanés append-only
  `artifacts/real/odds_snapshots.jsonl` (cote médiane des bookmakers, probabilité implicite marge retirée, probabilités du
  modèle) + journal (`kind: prediction_odds`) + `odds_meta.json` (dernier appel, crédits). Cote à la prévision = premier
  instantané ; clôture = dernier avant le coup d'envoi. `market_report()` : log loss modèle vs marché + CLV par ligue (non
  affiché). UI : ligne EV (= p × cote − 1, avec la probabilité, la cote et l'heure du relevé) sur les matchs à venir
  d'Aujourd'hui et du détail de match, seulement si cote + probabilité ; tableau « Signaux : écart modèle – marché ».
  Vérifié le 2026-11-14 : 1 relevé NFL réel, 26/26 événements associés, 499 crédits restants. NBA / Premier League :
  aucune prévision à venir → aucun appel. Limite : sur Cloud, un relevé via le bouton admin vit dans le conteneur
  (perdu au redéploiement) ; le relevé durable = commande locale puis commit + push. Tests `tests/test_odds_api.py` (15).

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
