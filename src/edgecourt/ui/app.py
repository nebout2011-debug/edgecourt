"""Interface EDGECOURT (Streamlit, 127.0.0.1). Hiérarchie inspirée d'un site de pronostics par matchs ; identité propre.

Aucune note A/B, aucun badge « fiable » : seulement des probabilités, des effectifs et des statuts de preuve.
"""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from edgecourt import config, pipeline
from edgecourt.data import connectors, store
from edgecourt.models.markets import dist_from_params

st.set_page_config(page_title="EDGECOURT", page_icon="🏟️", layout="wide")

DAYS = ["lun.", "mar.", "mer.", "jeu.", "ven.", "sam.", "dim."]
MONTHS = ["janv.", "févr.", "mars", "avr.", "mai", "juin", "juil.", "août", "sept.", "oct.", "nov.", "déc."]
CSS = """
<style>
.block-container {padding-top: 1rem; max-width: 1250px;}
.ec-head {background:#10231c; color:#fff; padding:14px 22px; border-radius:10px; display:flex; align-items:baseline; gap:18px;}
.ec-head .brand {font-size:1.7rem; font-weight:800; letter-spacing:.14em;}
.ec-head .tag {opacity:.75; font-size:.9rem;}
.ec-demo {background:#fff4d6; color:#5c4300; border:2px dashed #d9a400; padding:10px 14px; border-radius:8px; font-weight:600; margin:8px 0;}
.ec-note {color:#5b6b64; font-size:.85rem;}
.ec-row {display:grid; grid-template-columns:110px 1fr 260px 190px; gap:12px; align-items:center; padding:10px 6px; border-bottom:1px solid #e5ebe8;}
.ec-date {color:#5b6b64; font-size:.85rem;}
.ec-bar {display:flex; height:14px; border-radius:7px; overflow:hidden; background:#e9eeec;}
.ec-bar .h {background:#0B6E4F;} .ec-bar .d {background:#b8c4bf;} .ec-bar .a {background:#c8553d;}
.ec-p {font-variant-numeric:tabular-nums; font-size:.85rem; color:#26332e;}
.ec-badge {display:inline-block; padding:2px 8px; border-radius:999px; font-size:.75rem; background:#e9eeec; color:#26332e;}
.ec-bt {background:#e8eefc; color:#1b3a8a;}
.ec-fut {background:#d9f2e6; color:#0b4d36; font-weight:700;}
</style>
"""
st.markdown(CSS, unsafe_allow_html=True)


# ---------------------------------------------------------------- chargement
def _mt(p: Path) -> float:
    return p.stat().st_mtime if p.exists() else 0.0


@st.cache_data(show_spinner=False)
def _parquet(path: str, mtime: float):
    return pd.read_parquet(path)


@st.cache_data(show_spinner=False)
def _json(path: str, mtime: float):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def preds(origin, sport):
    p = config.origin_dir(origin) / f"predictions_{sport}.parquet"
    return _parquet(str(p), _mt(p)) if p.exists() else None


def sim(origin, sport):
    p = config.origin_dir(origin) / f"simulation_{sport}.parquet"
    return _parquet(str(p), _mt(p)) if p.exists() else None


def report(origin, sport):
    p = config.origin_dir(origin) / f"report_{sport}.json"
    return _json(str(p), _mt(p)) if p.exists() else None


def fr_date(d) -> str:
    d = pd.Timestamp(d)
    return f"{DAYS[d.weekday()]} {d.day} {MONTHS[d.month - 1]} {d.year}"


def pct(x) -> str:
    return "—" if pd.isna(x) else f"{100 * x:.1f} %"


# ---------------------------------------------------------------- en-tête
st.markdown('<div class="ec-head"><span class="brand">EDGECOURT</span>'
            '<span class="tag">Recherche prédictive locale · simulation uniquement · aucun pari, aucun dépôt</span></div>',
            unsafe_allow_html=True)
c1, c2 = st.columns([3, 2])
with c1:
    sport = st.radio("Sport", list(config.SPORTS), format_func=config.SPORT_LABEL.get, horizontal=True, label_visibility="collapsed")
with c2:
    mode = st.radio("Données", ["real", "demo"], format_func=lambda m: "Données réelles" if m == "real" else "Démonstration synthétique",
                    horizontal=True, label_visibility="collapsed")
origin = mode
if origin == "demo":
    st.markdown('<div class="ec-demo">DÉMONSTRATION SYNTHÉTIQUE — équipes et scores fictifs, cotes « fixtures ». '
                'Sert à tester le parcours et les règlements ; n\'a aucune valeur sportive.</div>', unsafe_allow_html=True)
st.caption("Aucun avantage prédictif ni taux de réussite n'est démontré. Les résultats affichés sont rétrospectifs.")

P, R, S = preds(origin, sport), report(origin, sport), sim(origin, sport)


def upcoming(o: str, sp: str):
    """Dernière version « à venir » (modèle actualisé), séparée du backtest. Repli : lignes à venir du backtest."""
    d = config.origin_dir(o)
    files = sorted(d.glob(f"predictions_{sp}_upcoming_*.parquet"), key=lambda f: (f.name, f.stat().st_mtime))
    if files:
        rp = d / files[-1].name.replace("predictions_", "report_").replace(".parquet", ".json")
        return _parquet(str(files[-1]), _mt(files[-1])), (_json(str(rp), _mt(rp)) if rp.exists() else None)
    return None, None


U, UR = upcoming(origin, sport)
if U is None and P is not None:
    U = P[P["status"] != "final"].reset_index(drop=True)  # modèle du backtest, non actualisé
if UR:
    UP_LABEL = f"version {UR['version']} · données jusqu'au {UR['date_limite_donnees']}"
else:
    UP_LABEL = "modèle du backtest (non actualisé)"
WM = "1X2 (temps réglementaire)" if sport == "soccer" else "Vainqueur (prolongations incluses)"
tab_m, tab_a, tab_v, tab_s, tab_d = st.tabs(["Matchs", "Analyse d'un match", "Validation", "Simulation", "Données"])


def decision_table(df: pd.DataFrame) -> pd.DataFrame:
    """Colonnes cote / EV / décision / raison pour le marché vainqueur, depuis la simulation."""
    wm = "1x2" if sport == "soccer" else "moneyline"
    out = df.copy()
    out["cote"], out["ev"], out["decision"], out["raison"] = "—", "—", "abstention", "aucune cote valide à l'instant de la prévision"
    if S is not None and len(S):
        w = S[S["market"] == wm]
        if len(w):
            top = w.sort_values("ev", ascending=False).drop_duplicates("game_id").set_index("game_id")
            m = out["game_id"].isin(top.index)
            t = top.reindex(out.loc[m, "game_id"])
            out.loc[m, "cote"] = [f"{s} @ {o:.2f}" for s, o in zip(t["selection"], t["odds"])]
            out.loc[m, "ev"] = [f"{e:+.3f}" for e in t["ev"]]
            out.loc[m, "decision"] = t["decision"].to_numpy()
            out.loc[m, "raison"] = [r if r else "EV ≥ seuil (simulation)" for r in t["raison_abstention"]]
    return out


# ---------------------------------------------------------------- Matchs
with tab_m:
    if P is None:
        rep = R or {}
        st.info(f"Aucune prévision pour {config.SPORT_LABEL[sport]} ({'réel' if origin == 'real' else 'démo'}). "
                f"{rep.get('detail', 'Voir la page Données pour importer ou connaître le blocage.')}")
    else:
        today = pd.Timestamp.today().normalize()
        f1, f2, f3 = st.columns(3)
        market = f1.selectbox("Marché", [WM, f"Total (ligne {R['total']['ligne']})"])
        lo, hi = min(P["game_date"].min(), U["game_date"].min() if len(U) else P["game_date"].min()).date(),             max(P["game_date"].max(), U["game_date"].max() if len(U) else P["game_date"].max()).date()
        rng = f2.date_input("Période", value=(max(lo, (today - pd.Timedelta(days=30)).date()) if origin == "real" else hi - pd.Timedelta(days=60), hi),
                            min_value=lo, max_value=hi)
        team = f3.text_input("Équipe contient")
        d0, d1 = (rng[0], rng[1]) if isinstance(rng, tuple) and len(rng) == 2 else (lo, hi)
        view = P[(P["game_date"].dt.date >= d0) & (P["game_date"].dt.date <= d1)]
        if team:
            view = view[view["home_team"].str.contains(team, case=False) | view["away_team"].str.contains(team, case=False)]
        uview = U[(U["game_date"].dt.date >= d0) & (U["game_date"].dt.date <= d1)]
        if team:
            uview = uview[uview["home_team"].str.contains(team, case=False) | uview["away_team"].str.contains(team, case=False)]
        up = uview[uview["game_date"] >= today] if origin == "real" else uview.iloc[0:0]
        last_final = P[P["status"] == "final"]["game_date"].max()
        k1, k2, k3, k4 = st.columns(4)
        k1.metric("Matchs terminés en base", int(UR["resultats_termines_utilises"]) if UR else (int(R["split"]["n_final"]) if R and "split" in R else 0))
        k2.metric("Date limite des données", UR["date_limite_donnees"] if UR else (str(last_final.date()) if pd.notna(last_final) else "—"))
        k3.metric("Version du modèle (à venir)", UR["version"] if UR else "backtest")
        k4.metric("Prévisions à venir", int((U["game_date"] >= today).sum()) if origin == "real" else 0)
        st.caption(f"À venir : {UR['calibration'] if UR else 'non actualisé'} · Backtest : {R['calibration']} "
                   f"(modèle figé au {R['split']['train_end']}, évalué sur des matchs terminés).")
        st.subheader("Prévisions à venir")
        st.markdown(f'<span class="ec-badge ec-fut">PRÉVISION À VENIR</span> <span class="ec-note">{UP_LABEL}</span>', unsafe_allow_html=True)
        if up.empty:
            st.info("Aucune rencontre à venir dans les données pour ces filtres. Un historique n'est jamais affiché comme match à venir.")
        else:
            up = decision_table(up.sort_values("game_date").head(60))
            for r in up.itertuples():
                if market == WM:
                    h, d, a = r.p_home_final, r.p_draw_final, r.p_away_final
                    bar = (f'<div class="ec-bar"><span class="h" style="width:{h*100:.1f}%"></span>'
                           f'<span class="d" style="width:{d*100:.1f}%"></span><span class="a" style="width:{a*100:.1f}%"></span></div>')
                    pp = f"{pct(h)} · {pct(d)} · {pct(a)}"
                else:
                    pp = "voir Analyse"
                    bar = ""
                st.markdown(f'<div class="ec-row"><div class="ec-date">{fr_date(r.game_date)}</div>'
                            f'<div><b>{r.home_team}</b> – {r.away_team}<br><span class="ec-note">{r.decision} · {r.raison}</span></div>'
                            f'<div>{bar}</div><div class="ec-p">{pp}<br>cote : {r.cote}</div></div>', unsafe_allow_html=True)
            st.caption("Barres : domicile · nul · extérieur. Cotes absentes = « rendement non évaluable ».")
        st.subheader("Backtests (matchs terminés)")
        st.markdown('<span class="ec-badge ec-bt">BACKTEST</span> <span class="ec-note">prévisions reconstruites avec les seules données '
                    'antérieures à chaque match ; ce ne sont pas des prévisions prospectives.</span>', unsafe_allow_html=True)
        hist = decision_table(view[view["status"] == "final"].sort_values("game_date", ascending=False).head(300))
        if hist.empty:
            st.info("Aucun match de l'historique pour ces filtres.")
        else:
            hist["résultat"] = hist["home_score"].astype(int).astype(str) + " - " + hist["away_score"].astype(int).astype(str)
            t = pd.DataFrame({"Date": hist["game_date"].dt.date, "Match": hist["home_team"] + " – " + hist["away_team"],
                              "Période": hist["segment"], "P dom.": hist["p_home_final"].map(pct), "P nul": hist["p_draw_final"].map(pct),
                              "P ext.": hist["p_away_final"].map(pct), "Résultat": hist["résultat"], "Cote": hist["cote"], "EV": hist["ev"],
                              "Décision": hist["decision"], "Raison d'abstention": hist["raison"]})
            st.dataframe(t, use_container_width=True, hide_index=True)

# ---------------------------------------------------------------- Analyse
with tab_a:
    if P is None:
        st.info("Pas de prévisions disponibles.")
    else:
        today_a = pd.Timestamp.today().normalize()
        nxt = U[U["game_date"] >= today_a].sort_values(["game_date", "game_id"]) if origin == "real" else U.iloc[0:0]
        opts = {f"{r.game_date.date()} · {r.home_team} – {r.away_team} [À VENIR]": ("U", i) for i, r in nxt.iterrows()}  # le 1er = prochain match
        lab = P[P["status"] == "final"].sort_values("game_date", ascending=False).head(400)
        opts.update({f"{r.game_date.date()} · {r.home_team} – {r.away_team} [BACKTEST]": ("P", i) for i, r in lab.iterrows()})
        src, idx = opts[st.selectbox("Match (le prochain match à venir est sélectionné par défaut)", list(opts))]
        g = (U if src == "U" else P).loc[idx]
        st.subheader(f"{g['home_team']} – {g['away_team']}")
        if src == "U":
            st.markdown(f'<span class="ec-badge ec-fut">PRÉVISION À VENIR</span> <span class="ec-note">{UP_LABEL}</span>', unsafe_allow_html=True)
        else:
            st.markdown(f'<span class="ec-badge ec-bt">BACKTEST</span> <span class="ec-note">modèle du backtest, figé au {R["split"]["train_end"]}</span>', unsafe_allow_html=True)
        st.caption(f"{fr_date(g['game_date'])} · empreinte des données avant le match : {g['data_fp']} · modèle : {g['model_selected']}"
                   f"{' (calibré)' if g['calibrated'] else ' (non calibré)'}")
        cols = st.columns(3)
        cols[0].metric("Domicile", pct(g["p_home_final"]))
        cols[1].metric("Nul", pct(g["p_draw_final"]))
        cols[2].metric("Extérieur", pct(g["p_away_final"]))
        if g["status"] == "final":
            st.success(f"Résultat : {int(g['home_score'])} - {int(g['away_score'])} (prévision rétrospective « backtest »)")
        dp = g["dp_model"] if g["total_dist_selected"] == "model" else g["dp_base"]
        dist = dist_from_params(json.loads(dp))
        a1, a2 = st.columns(2)
        fig = go.Figure(go.Bar(x=dist.mk, y=dist.mp, marker_color="#0B6E4F"))
        fig.update_layout(title="Distribution de l'écart (domicile − extérieur)", height=300, margin=dict(l=10, r=10, t=40, b=10))
        a1.plotly_chart(fig, use_container_width=True)
        fig = go.Figure(go.Bar(x=dist.tk, y=dist.tp, marker_color="#c8553d"))
        fig.add_vline(x=R["total"]["ligne"], line_dash="dash")
        fig.update_layout(title=f"Distribution du total (ligne de référence {R['total']['ligne']})", height=300, margin=dict(l=10, r=10, t=40, b=10))
        a2.plotly_chart(fig, use_container_width=True)
        st.markdown("**Variables connues avant le match**")
        st.dataframe(pd.DataFrame([{"Elo dom.": round(g["elo_h"]), "Elo ext.": round(g["elo_a"]), "Repos dom. (j)": g["rest_h"], "Repos ext. (j)": g["rest_a"],
                                    "Forme dom.": round(g["form_h"], 2), "Forme ext.": round(g["form_a"], 2)}]), hide_index=True)
        cand = [c[2:-2] for c in P.columns if c.startswith("w_") and c.endswith("_h")]
        st.markdown("**Comparaison des modèles (avant calibration)**")
        st.dataframe(pd.DataFrame([{"Modèle": c, "Dom.": pct(g[f"w_{c}_h"]), "Nul": pct(g[f"w_{c}_d"]), "Ext.": pct(g[f"w_{c}_a"])} for c in cand]),
                     hide_index=True)
        if S is not None and len(S):
            gs = S[S["game_id"] == g["game_id"]]
            st.markdown("**Cotes admissibles et espérance (par unité)**")
            if gs.empty:
                st.info("Rendement non évaluable : aucune cote valide jointe à ce match.")
            else:
                st.dataframe(gs[["bookmaker", "market", "selection", "line", "odds", "fair_prob", "p_win", "p_push", "p_loss", "ev", "decision",
                                 "raison_abstention", "outcome"]], hide_index=True)
                st.caption("L'écart estimé n'est pas une garantie.")
        else:
            st.info("Rendement non évaluable : aucune cote valide.")

# ---------------------------------------------------------------- Validation
def render_validation(o: str):
    r = report(o, sport)
    if r is None or "vainqueur" not in r:
        st.info((r or {}).get("detail", "Pas de rapport pour ce sport.") if r else "Pas de rapport : lancer l'évaluation.")
        return
    if o == "demo":
        st.markdown('<div class="ec-demo">DÉMONSTRATION SYNTHÉTIQUE — ces chiffres ne décrivent aucune performance sportive.</div>', unsafe_allow_html=True)
    e = r["effectifs"]
    c = st.columns(4)
    c[0].metric("Prévisions test", e["test"]); c[1].metric("Validation", e["calibration"])
    c[2].metric("Découpage", f"{r['split']['train_end']} / {r['split']['calib_end']}")
    c[3].metric("Calibration", "oui" if r["calibration"].startswith("calibré") else "non")
    st.caption(f"Modèle sélectionné sur la validation (jamais sur le test) : **{r['modele_vainqueur_selectionne_sur_validation']}** — {r['calibration']}. "
               f"Total : **{r['modele_total_selectionne_sur_validation']}**. Ajustement : {r['ajustement']}")
    st.markdown(f"**{WM}** — Brier multi-classes et log loss ; comparables seulement dans un même marché.")
    t = pd.DataFrame(r["vainqueur"]["lignes"])
    st.dataframe(t, use_container_width=True, hide_index=True)
    ic = r["vainqueur"]["ic"]
    if ic:
        st.write(f"Écart de log loss vs référence simple : {ic['delta_logloss_vs_baseline']:+.4f} (IC 95 % par blocs {ic['blocs']} : "
                 f"{ic['ic95_bas']:+.4f} ; {ic['ic95_haut']:+.4f}) → **{ic['statut']}**")
    cur = pd.DataFrame(r["vainqueur"]["courbe_calibration"])
    if len(cur):
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=[0, 1], y=[0, 1], mode="lines", line=dict(dash="dash", color="#999"), name="parfait"))
        ok = cur.dropna()
        fig.add_trace(go.Scatter(x=ok["p_moyenne"], y=ok["frequence_observee"], mode="markers+lines+text",
                                 text=[f"n={n}" for n in ok["n"]], textposition="top center", name="observé", marker_color="#0B6E4F"))
        fig.update_layout(title="Calibration : P(domicile) prévue vs observée (effectifs par classe)", height=340,
                          xaxis_title="probabilité prévue", yaxis_title="fréquence observée", margin=dict(l=10, r=10, t=40, b=10))
        st.plotly_chart(fig, use_container_width=True)
    st.markdown(f"**Total, ligne de référence {r['total']['ligne']}** (fixée sur l'entraînement)")
    st.dataframe(pd.DataFrame(r["total"]["lignes"]), use_container_width=True, hide_index=True)
    ic = r["total"]["ic"]
    if ic:
        st.write(f"Écart de log loss vs référence : {ic['delta_logloss_vs_baseline']:+.4f} (IC 95 % : {ic['ic95_bas']:+.4f} ; {ic['ic95_haut']:+.4f}) → **{ic['statut']}**")
    m = r["reference_marche"]
    st.markdown("**Référence marché** (mêmes événements, même bookmaker)")
    if "lignes" in m:
        st.dataframe(pd.DataFrame(m["lignes"]), use_container_width=True, hide_index=True)
        st.caption(m["limite"] + (" — cotes FIXTURES" if o == "demo" else ""))
    else:
        st.info(m["statut"])
    st.caption(r["avertissement"])
    cfg = config.origin_dir(o) / "configs_tried.jsonl"
    if cfg.exists():
        with st.expander("Toutes les configurations essayées (validation)"):
            rows = [json.loads(l) for l in cfg.read_text(encoding="utf-8").splitlines()]
            st.dataframe(pd.DataFrame([x for x in rows if x["sport"] == sport]), use_container_width=True, hide_index=True)


with tab_v:
    st.markdown("Résultats **réels** et **démonstration synthétique** sont présentés séparément et ne sont jamais mélangés.")
    v1, v2 = st.tabs(["Données réelles", "Démonstration synthétique (fictive)"])
    with v1:
        render_validation("real")
    with v2:
        render_validation("demo")

# ---------------------------------------------------------------- Simulation
with tab_s:
    st.markdown("Simulation **à mise fixe d'une unité**, sans recommandation de mise ni Kelly. Ce n'est pas une gestion de bankroll.")
    if R is None or "simulation" not in R:
        st.info("Rendement non évaluable : pas de rapport.")
    else:
        seg = st.radio("Période", ["test", "calibration"], horizontal=True, format_func=lambda s: "test final" if s == "test" else "validation")
        sm = R["simulation"][seg]
        if R["simulation"].get("note"):
            st.warning(R["simulation"]["note"])
        if sm.get("statut") == "rendement non évaluable":
            st.info(f"Rendement non évaluable — {sm.get('raison', '')}")
        else:
            c = st.columns(5)
            c[0].metric("Paris simulés", sm["paris"]); c[1].metric("Profit (unités)", f"{sm['profit_unites']:+.2f}")
            c[2].metric("ROI fictif net", f"{100 * sm['roi_net']:+.1f} %"); c[3].metric("Drawdown max (u)", f"{sm['drawdown_max_unites']:.1f}")
            c[4].metric("G / P / R", f"{sm['gagnes']} / {sm['perdus']} / {sm['rembourses']}")
            st.write(f"Statut : **{sm['statut']}** · IC 95 % du profit moyen par pari : [{sm['roi_ic95'][0]:+.3f} ; {sm['roi_ic95'][1]:+.3f}] "
                     f"· frais supposés par unité : {sm['frais_par_unite']}")
            cv = pd.DataFrame(sm["courbe_cumulee"])
            fig = go.Figure(go.Scatter(x=cv["date"], y=cv["cumul"], mode="lines", line_color="#0B6E4F"))
            fig.update_layout(title="Profit cumulé (unités)", height=320, margin=dict(l=10, r=10, t=40, b=10))
            st.plotly_chart(fig, use_container_width=True)
            st.caption(sm["avertissement"])
        if S is not None and len(S):
            with st.expander("Détail des cotes évaluées"):
                st.dataframe(S[S["segment"] == seg].tail(500), use_container_width=True, hide_index=True)
        cts = R.get("cotes", {})
        st.caption(f"Cotes importées : {cts.get('importees', 0)} · admissibles : {cts.get('admissibles', 0)} · "
                   f"refusées (postérieures à la prévision) : {cts.get('refusees_posterieures_au_cutoff', 0)}")

# ---------------------------------------------------------------- Données
with tab_d:
    s_ = store.Store(origin)
    try:
        imp, rej = s_.imports(), s_.rejects()
        st.subheader("Connecteurs")
        st.dataframe(connectors.status_table(s_), use_container_width=True, hide_index=True)
        stp = config.origin_dir("real") / "connector_status.json"
        if origin == "real" and stp.exists():
            st.json(json.loads(stp.read_text(encoding="utf-8")), expanded=False)
        st.subheader("Imports et fraîcheur")
        if imp.empty:
            st.info("Aucun import. Exécuter `.\\scripts\\fetch.ps1` ou importer un CSV ci-dessous.")
        else:
            st.dataframe(imp[["sport", "source", "retrieved_at", "rows_read", "accepted", "inserted", "updated", "unchanged", "rejected",
                              "min_date", "max_date", "coverage", "sha256"]], use_container_width=True, hide_index=True)
        if len(rej):
            with st.expander(f"Lignes rejetées ({len(rej)})"):
                st.dataframe(rej, hide_index=True)
    finally:
        s_.close()
    st.subheader("Sources, licences et attribution")
    st.markdown(
        "- **nflverse-data** (NFL) : dépôt sous licence CC-BY-4.0 → attribution « nflverse » obligatoire.\n"
        "- **StatsBomb Open Data** (soccer, Premier League 2015/2016) : usage de recherche locale ; pas de redistribution ni d'exploitation "
        "commerciale ; toute publication doit créditer StatsBomb avec son logo.\n"
        "- **BALLDONTLIE** (NBA) : endpoint Games annoncé gratuit avec une clé gratuite (5 requêtes/min). Les autres endpoints sont payants.\n"
        "- Détails, dates de vérification et limites : `docs/DATA_SOURCES.md`.")
    st.subheader("Import CSV")
    if origin == "demo":
        st.info("Les imports sont désactivés en mode démonstration : la base synthétique est isolée de la base réelle.")
    else:
        i1, i2 = st.columns(2)
        with i1:
            st.markdown("**Matchs** (colonnes : voir `samples/games_example.csv`)")
            sp1 = st.selectbox("Sport du fichier", list(config.SPORTS), key="sp1", format_func=config.SPORT_LABEL.get)
            up1 = st.file_uploader("CSV de matchs (données dont vous avez les droits)", type="csv", key="u1")
            if up1 and st.button("Importer les matchs"):
                with tempfile.TemporaryDirectory() as td:
                    pth = Path(td) / up1.name
                    pth.write_bytes(up1.getvalue())
                    try:
                        st.json(pipeline.import_games_csv("real", sp1, str(pth)))
                        st.cache_data.clear()
                    except Exception as ex:
                        st.error(f"Import refusé : {ex}")
        with i2:
            st.markdown("**Cotes** (colonnes : voir `samples/odds_example.csv`)")
            sp2 = st.selectbox("Sport du fichier", list(config.SPORTS), key="sp2", format_func=config.SPORT_LABEL.get)
            up2 = st.file_uploader("CSV de cotes horodatées", type="csv", key="u2")
            if up2 and st.button("Importer les cotes"):
                with tempfile.TemporaryDirectory() as td:
                    pth = Path(td) / up2.name
                    pth.write_bytes(up2.getvalue())
                    try:
                        st.json(pipeline.import_odds_csv("real", sp2, str(pth)))
                        st.cache_data.clear()
                    except Exception as ex:
                        st.error(f"Import refusé : {ex}")
        if st.button("Recalculer l'évaluation (réel)"):
            with st.spinner("Évaluation en cours…"):
                pipeline.run_all("real")
            st.cache_data.clear()
            st.success("Évaluation terminée.")
