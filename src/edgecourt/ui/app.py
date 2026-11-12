"""Interface EDGECOURT (Streamlit, 127.0.0.1) — style « Terminal + Premium », 8 écrans.

Site de PRÉDICTION uniquement : aucun pari, aucun dépôt, aucun compte ni lien bookmaker.
Aucune note A/B, aucun badge « fiable » : des probabilités, des effectifs et des statuts de preuve.
Tout chiffre qui ne vient pas du moteur est étiqueté « Données d'exemple ».
"""
from __future__ import annotations

import json
import math
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
LONG_DAYS = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]
MONTHS = ["janv.", "févr.", "mars", "avr.", "mai", "juin", "juil.", "août", "sept.", "oct.", "nov.", "déc."]
LONG_MONTHS = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août", "septembre", "octobre", "novembre", "décembre"]
BANNER = ("⚠️ Attention: ceci n'est pas un site de pari. EDGECOURT est un site de prédiction — notre ambition: devenir le meilleur "
          "site de prédiction que le monde ait jamais connu. Nos prédictions sont des conseils et des idées pour vous aider à juger — "
          "la décision finale vous appartient.")
ACCENT, RED = "#0B6E4F", "#c8553d"

CSS = """
<style>
:root {--ink:#0d0f0e; --paper:#fbfbf8; --muted:#6b716e; --line:#e4e4de; --accent:#0B6E4F; --red:#c8553d;
       --mono: ui-monospace, "Cascadia Mono", "SF Mono", Menlo, Consolas, monospace;
       --display: "Segoe UI Variable Display", "Inter", "Helvetica Neue", system-ui, sans-serif;}
html, body, .stApp {background:var(--paper); color:var(--ink);}
header[data-testid="stHeader"] {display:none;}
.block-container {padding-top:0 !important; max-width:1240px;}
.ec-banner {background:#fff3cd; color:#4d3800; border-bottom:1px solid #f0d58a; padding:12px 18px; font-size:.92rem; line-height:1.45;}
.ec-brand {font-family:var(--mono); font-weight:800; font-size:1.5rem; letter-spacing:.22em; color:var(--ink); padding:22px 0 4px;}
.ec-brand span {color:var(--accent);}
[data-testid="stPageLink"] a {font-family:var(--mono); font-size:.8rem; text-transform:uppercase; letter-spacing:.06em; padding:2px 6px;}
.ec-kicker {font-family:var(--mono); font-size:.78rem; letter-spacing:.14em; text-transform:uppercase; color:var(--muted); margin-top:28px;}
.ec-h1 {font-family:var(--display); font-weight:750; font-size:clamp(2.4rem, 6vw, 4.6rem); line-height:1.02; letter-spacing:-.03em;
        margin:6px 0 10px;}
.ec-h2 {font-family:var(--display); font-weight:700; font-size:clamp(1.6rem, 3.4vw, 2.4rem); letter-spacing:-.02em; margin:44px 0 6px;}
.ec-lead {font-size:1.15rem; color:#3b413e; max-width:760px; line-height:1.55;}
.ec-note {color:var(--muted); font-size:.85rem;}
.ec-tag {display:inline-block; font-family:var(--mono); font-size:.72rem; letter-spacing:.08em; text-transform:uppercase;
         padding:3px 9px; border-radius:3px; background:#ecefed; color:#26332e; margin-right:6px;}
.ec-tag.fut {background:#d9f2e6; color:#0b4d36;} .ec-tag.bt {background:#e8eefc; color:#1b3a8a;}
.ec-tag.ex {background:#fff3cd; color:#5c4300; border:1px dashed #d9a400;}
.ec-demo {background:#fff4d6; color:#5c4300; border:1px dashed #d9a400; padding:10px 14px; border-radius:6px; font-weight:600; margin:14px 0;}
.ec-row {display:grid; grid-template-columns:120px 1fr 240px; gap:18px; align-items:center; padding:16px 0; border-bottom:1px solid var(--line);}
.ec-row .when {font-family:var(--mono); font-size:.8rem; color:var(--muted);}
.ec-row .teams {font-family:var(--display); font-size:1.25rem; font-weight:650;}
.ec-row .teams i {font-style:normal; color:var(--muted); font-weight:400; padding:0 8px;}
.ec-bar {display:flex; height:10px; border-radius:2px; overflow:hidden; background:#e9eeec; margin-bottom:6px;}
.ec-bar .h {background:var(--accent);} .ec-bar .d {background:#b8c4bf;} .ec-bar .a {background:var(--red);}
.ec-p {font-family:var(--mono); font-size:.82rem; color:#26332e; font-variant-numeric:tabular-nums;}
.ec-big {display:grid; grid-template-columns:repeat(auto-fit, minmax(180px, 1fr)); gap:18px; margin:26px 0;}
.ec-big div {border-top:2px solid var(--ink); padding-top:10px;}
.ec-big b {display:block; font-family:var(--mono); font-size:clamp(2.2rem, 5vw, 3.6rem); font-weight:700; letter-spacing:-.03em;
           font-variant-numeric:tabular-nums; line-height:1.05;}
.ec-big span {font-family:var(--mono); font-size:.75rem; letter-spacing:.12em; text-transform:uppercase; color:var(--muted);}
.ec-card {border:1px solid var(--line); background:#fff; border-radius:6px; padding:26px 26px 20px; margin:14px 0;}
.ec-card h3 {font-family:var(--display); font-size:2rem; font-weight:750; letter-spacing:-.02em; margin:0 0 4px;}
.ec-ad {display:flex; align-items:center; justify-content:center; max-width:100%; margin:28px auto; border:2px dashed #b9bdbb;
        background:#f1f2f0; color:#8a8f8c; font-family:var(--mono); font-size:.78rem; letter-spacing:.14em; text-transform:uppercase;}
div[data-testid="stColumn"]:has(.ec-sticky) {position:sticky; top:16px; align-self:flex-start;}
@media (max-width: 900px) {
  div[data-testid="stColumn"]:has(.ec-sticky) {display:none;}
  .ec-row {grid-template-columns:1fr; gap:6px;}
}
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


def upcoming(o: str, sp: str):
    """Dernière version « à venir » (modèle actualisé), séparée du backtest. Repli : lignes à venir du backtest."""
    d = config.origin_dir(o)
    files = sorted(d.glob(f"predictions_{sp}_upcoming_*.parquet"), key=lambda f: (f.name, f.stat().st_mtime))
    if files:
        rp = d / files[-1].name.replace("predictions_", "report_").replace(".parquet", ".json")
        return _parquet(str(files[-1]), _mt(files[-1])), (_json(str(rp), _mt(rp)) if rp.exists() else None)
    P = preds(o, sp)
    return (P[P["status"] != "final"].reset_index(drop=True) if P is not None else None), None


def up_label(UR) -> str:
    return f"version {UR['version']} · données jusqu'au {UR['date_limite_donnees']}" if UR else "modèle du backtest (non actualisé)"


def fr_date(d) -> str:
    d = pd.Timestamp(d)
    return f"{DAYS[d.weekday()]} {d.day} {MONTHS[d.month - 1]} {d.year}"


def pct(x) -> str:
    return "—" if pd.isna(x) else f"{100 * x:.1f} %"


def fr_num(x: float, fmt: str = ".3f") -> str:
    return format(x, fmt).replace(".", ",")


def html(s: str):
    st.markdown(s, unsafe_allow_html=True)


def hero(kicker: str, title: str, lead: str = ""):
    html(f'<div class="ec-kicker">{kicker}</div><div class="ec-h1">{title}</div>' + (f'<p class="ec-lead">{lead}</p>' if lead else ""))


def ad(w: int, h: int, cls: str = ""):
    html(f'<div class="ec-ad {cls}" style="width:{w}px;height:{h}px">Publicité</div>')


def big_html(items) -> str:
    return '<div class="ec-big">' + "".join(f"<div><b>{v}</b><span>{k}</span></div>" for k, v in items) + "</div>"


def pick_sport() -> str:
    """Sélecteur de ligue partagé entre écrans (valeur gardée hors widget)."""
    cur = st.session_state.get("sport", "nfl")
    v = st.segmented_control("Ligue", list(config.SPORTS), default=cur, format_func=config.SPORT_LABEL.get, label_visibility="collapsed")
    st.session_state["sport"] = v or cur
    return st.session_state["sport"]


def prob_cell(h, d, a) -> str:
    bar = (f'<div class="ec-bar"><span class="h" style="width:{h*100:.1f}%"></span><span class="d" style="width:{d*100:.1f}%"></span>'
           f'<span class="a" style="width:{a*100:.1f}%"></span></div>')
    txt = f"{pct(h)} · {pct(d)} · {pct(a)}" if d > 0.001 else f"{pct(h)} · {pct(a)}"
    return bar + f'<div class="ec-p">{txt}</div>'


def demo_strip(origin: str):
    if origin == "demo":
        html('<div class="ec-demo">Données d\'exemple — démonstration synthétique : équipes et scores fictifs, cotes « fixtures ». '
             "Sert à tester le parcours ; n'a aucune valeur sportive.</div>")


def headline(r):
    """(log loss modèle, log loss référence, IC) sur le test final, depuis le rapport."""
    ic = r["vainqueur"]["ic"] if r and "vainqueur" in r else None
    base = next((l["logloss"] for l in r["vainqueur"]["lignes"] if l["modele"] == "baseline" and l["periode"] == "test"), None) if ic else None
    return (base + ic["delta_logloss_vs_baseline"], base, ic) if base is not None else (None, None, None)


def wm_label(sport: str) -> str:
    return "1X2 (temps réglementaire)" if sport == "soccer" else "Vainqueur (prolongations incluses)"


# ================================================================= écrans
def page_today():
    origin = st.session_state["mode"]
    today = pd.Timestamp.today().normalize()
    ad(728, 90)
    main, side = st.columns([3, 1], gap="large")
    with side:
        ad(300, 600, "ec-sticky")
    with main:
        hero("Aujourd'hui", f"{LONG_DAYS[today.weekday()].capitalize()} {today.day} {LONG_MONTHS[today.month - 1]}",
             "Les prochaines prévisions de chaque ligue, avant le coup d'envoi. Des probabilités, pas des certitudes.")
        demo_strip(origin)
        for i, sp in enumerate(config.SPORTS, start=1):
            U, UR = upcoming(origin, sp)
            html(f'<div class="ec-h2">{config.SPORT_LABEL[sp]}</div>')
            nxt = U[U["game_date"] >= today].sort_values(["game_date", "game_id"]) if (U is not None and origin == "real") else None
            if nxt is None or nxt.empty:
                html('<p class="ec-note">Aucune prévision à venir pour cette ligue dans les données actuelles. '
                     "Un historique n'est jamais affiché comme match à venir.</p>")
            else:
                html(f'<span class="ec-tag fut">Prévision à venir</span><span class="ec-note">{up_label(UR)}</span>')
                first = nxt["game_date"].iloc[0]
                for r in nxt[nxt["game_date"] <= first + pd.Timedelta(days=6)].head(16).itertuples():
                    c1, c2 = st.columns([6, 1], vertical_alignment="center")
                    c1.markdown(f'<div class="ec-row"><div class="when">{fr_date(r.game_date)}</div>'
                                f'<div class="teams">{r.home_team}<i>–</i>{r.away_team}</div>'
                                f'<div>{prob_cell(r.p_home_final, r.p_draw_final, r.p_away_final)}</div></div>', unsafe_allow_html=True)
                    if c2.button("Détail →", key=f"go_{sp}_{r.game_id}"):
                        st.session_state["sport"] = sp
                        st.session_state["focus"] = (sp, r.game_id)
                        st.switch_page(PAGES["match"])
                html('<p class="ec-note">Barre : domicile · nul · extérieur.</p>')
            if i == 3:
                ad(300, 250)


def page_match():
    origin = st.session_state["mode"]
    sport = pick_sport()
    P, R, S = preds(origin, sport), report(origin, sport), sim(origin, sport)
    U, UR = upcoming(origin, sport)
    demo_strip(origin)
    if P is None or R is None:
        hero("Détail d'un match", "Aucune prévision", "Pas de prévisions disponibles pour cette ligue.")
        return
    today = pd.Timestamp.today().normalize()
    nxt = U[U["game_date"] >= today].sort_values(["game_date", "game_id"]) if (U is not None and origin == "real") else P.iloc[0:0]
    opts = {f"{r.game_date.date()} · {r.home_team} – {r.away_team} [À VENIR]": ("U", i, r.game_id) for i, r in nxt.iterrows()}
    lab = P[P["status"] == "final"].sort_values("game_date", ascending=False).head(400)
    opts.update({f"{r.game_date.date()} · {r.home_team} – {r.away_team} [BACKTEST]": ("P", i, r.game_id) for i, r in lab.iterrows()})
    keys = list(opts)
    focus = st.session_state.pop("focus", None)
    idx0 = next((k for k, key in enumerate(keys) if focus and focus[0] == sport and opts[key][2] == focus[1]), 0)
    src, idx, _ = opts[st.selectbox("Match (le prochain match à venir est sélectionné par défaut)", keys, index=idx0)]
    g = (U if src == "U" else P).loc[idx]
    hero(f"{config.SPORT_LABEL[sport]} · {fr_date(g['game_date'])}", f"{g['home_team']} – {g['away_team']}")
    if src == "U":
        html(f'<span class="ec-tag fut">Prévision à venir</span><span class="ec-note">{up_label(UR)}</span>')
    else:
        html(f'<span class="ec-tag bt">Backtest</span><span class="ec-note">modèle figé au {R["split"]["train_end"]}, '
             "prévision reconstruite avec les seules données antérieures au match</span>")
    items = [("Domicile", pct(g["p_home_final"]))] + ([("Nul", pct(g["p_draw_final"]))] if g["p_draw_final"] > 0.001 else []) \
        + [("Extérieur", pct(g["p_away_final"]))]
    html(big_html(items))
    st.caption(f"{wm_label(sport)} · modèle : {g['model_selected']}{' (calibré)' if g['calibrated'] else ' (non calibré)'} · "
               f"empreinte des données avant le match : {g['data_fp']}")
    if g["status"] == "final":
        st.success(f"Résultat : {int(g['home_score'])} - {int(g['away_score'])} (prévision rétrospective « backtest »)")
    dp = g["dp_model"] if g["total_dist_selected"] == "model" else g["dp_base"]
    dist = dist_from_params(json.loads(dp))
    html('<div class="ec-h2">Distributions</div>')
    a1, a2 = st.columns(2)
    fig = go.Figure(go.Bar(x=dist.mk, y=dist.mp, marker_color=ACCENT))
    fig.update_layout(title="Écart (domicile − extérieur)", height=300, margin=dict(l=10, r=10, t=40, b=10), plot_bgcolor="#fff")
    a1.plotly_chart(fig, use_container_width=True)
    fig = go.Figure(go.Bar(x=dist.tk, y=dist.tp, marker_color=RED))
    fig.add_vline(x=R["total"]["ligne"], line_dash="dash")
    fig.update_layout(title=f"Total (ligne de référence {R['total']['ligne']})", height=300, margin=dict(l=10, r=10, t=40, b=10), plot_bgcolor="#fff")
    a2.plotly_chart(fig, use_container_width=True)
    html('<div class="ec-h2">Ce que le modèle savait avant le match</div>')
    st.dataframe(pd.DataFrame([{"Elo dom.": round(g["elo_h"]), "Elo ext.": round(g["elo_a"]), "Repos dom. (j)": g["rest_h"],
                                "Repos ext. (j)": g["rest_a"], "Forme dom.": round(g["form_h"], 2), "Forme ext.": round(g["form_a"], 2)}]),
                 hide_index=True)
    cand = [c[2:-2] for c in P.columns if c.startswith("w_") and c.endswith("_h")]
    html('<div class="ec-h2">Comparaison des modèles</div>')
    st.dataframe(pd.DataFrame([{"Modèle": c, "Dom.": pct(g[f"w_{c}_h"]), "Nul": pct(g[f"w_{c}_d"]), "Ext.": pct(g[f"w_{c}_a"])} for c in cand]),
                 hide_index=True)
    st.caption("Probabilités avant calibration.")
    if S is not None and len(S):
        gs = S[S["game_id"] == g["game_id"]]
        with st.expander("Recherche : comparaison aux cotes du marché (démonstration)"):
            if gs.empty:
                st.info("Rendement non évaluable : aucune cote valide jointe à ce match.")
            else:
                st.dataframe(gs[["bookmaker", "market", "selection", "line", "odds", "fair_prob", "p_win", "p_push", "p_loss", "ev", "decision",
                                 "raison_abstention", "outcome"]], hide_index=True)
                st.caption("Cotes « fixtures » de démonstration. L'écart estimé n'est pas une garantie.")


def render_validation(o: str, sport: str):
    r = report(o, sport)
    if r is None or "vainqueur" not in r:
        st.info((r or {}).get("detail", "Pas de rapport pour ce sport.") if r else "Pas de rapport : lancer l'évaluation.")
        return
    demo_strip(o)
    e = r["effectifs"]
    c = st.columns(4)
    c[0].metric("Prévisions test", e["test"]); c[1].metric("Validation", e["calibration"])
    c[2].metric("Découpage", f"{r['split']['train_end']} / {r['split']['calib_end']}")
    c[3].metric("Calibration", "oui" if r["calibration"].startswith("calibré") else "non")
    st.caption(f"Modèle sélectionné sur la validation (jamais sur le test) : **{r['modele_vainqueur_selectionne_sur_validation']}** — {r['calibration']}. "
               f"Total : **{r['modele_total_selectionne_sur_validation']}**. Ajustement : {r['ajustement']}")
    st.markdown(f"**{wm_label(sport)}** — Brier multi-classes et log loss ; comparables seulement dans un même marché.")
    st.dataframe(pd.DataFrame(r["vainqueur"]["lignes"]), use_container_width=True, hide_index=True)
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
                                 text=[f"n={n}" for n in ok["n"]], textposition="top center", name="observé", marker_color=ACCENT))
        fig.update_layout(title="Calibration : P(domicile) prévue vs observée (effectifs par classe)", height=340, plot_bgcolor="#fff",
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


def page_proof():
    sport = pick_sport()
    r = report("real", sport)
    model, base, ic = headline(r)
    if model is None:
        hero("La preuve", config.SPORT_LABEL[sport], "Pas encore de rapport réel pour cette ligue.")
    else:
        hero("La preuve · données réelles · test final",
             f"{fr_num(model)} <span style='color:var(--muted);font-weight:400'>contre</span> {fr_num(base)}",
             f"Log loss du modèle contre une référence simple, sur {r['effectifs']['test']} matchs {config.SPORT_LABEL[sport]} "
             f"jamais vus pendant l'entraînement. Plus bas = meilleur. Statut : <b>{ic['statut']}</b>.")
        html(big_html([("Matchs de test", r["effectifs"]["test"]), ("Écart vs référence", fr_num(ic["delta_logloss_vs_baseline"], "+.3f")),
                       ("IC 95 %", f"[{fr_num(ic['ic95_bas'], '+.3f')} ; {fr_num(ic['ic95_haut'], '+.3f')}]")]))
        st.caption("Ne compare pas au marché (aucune cote réelle) : aucun avantage économique n'est démontré.")
    html('<div class="ec-h2">Le détail</div>')
    st.markdown("Résultats **réels** et **démonstration synthétique** sont présentés séparément et ne sont jamais mélangés.")
    v1, v2 = st.tabs(["Données réelles", "Démonstration synthétique (fictive)"])
    with v1:
        render_validation("real", sport)
    with v2:
        render_validation("demo", sport)
    ad(468, 60)


def page_leagues():
    origin = st.session_state["mode"]
    hero("Ligues", "Trois ligues, une méthode.", "Même découpage chronologique, même discipline temporelle, mêmes métriques pour chaque ligue.")
    demo_strip(origin)
    today = pd.Timestamp.today().normalize()
    for i, sp in enumerate(config.SPORTS, start=1):
        r, P = report(origin, sp), preds(origin, sp)
        U, _ = upcoming(origin, sp)
        model, base, ic = headline(r)
        n_up = int((U["game_date"] >= today).sum()) if (U is not None and origin == "real") else 0
        last = P[P["status"] == "final"]["game_date"].max() if P is not None else None
        stats = [("Matchs évalués", r["effectifs"]["matchs_finaux_evalues"] if r else "—"),
                 ("Log loss test", fr_num(model) if model else "—"), ("Référence", fr_num(base) if base else "—"), ("À venir", n_up)]
        html(f'<div class="ec-card"><span class="ec-tag">Ligue {i:02d}</span><h3>{config.SPORT_LABEL[sp]}</h3>'
             f'<div class="ec-note">Statut : {ic["statut"] if ic else "pas de rapport"} · dernier résultat : '
             f'{fr_date(last) if last is not None and pd.notna(last) else "—"}</div>' + big_html(stats) + "</div>")
        if i in (3, 6):
            ad(728, 90)


def page_live():
    hero("En direct", "Rien en direct pour l'instant.",
         "EDGECOURT publie des prévisions d'avant-match. Le suivi en direct n'est pas encore branché sur une source de données.")
    P = preds("demo", "nba")
    if P is not None and len(P):
        g = P.iloc[-1]
        html(f'<div class="ec-card"><span class="ec-tag ex">Données d\'exemple</span><span class="ec-tag">Aperçu du format</span>'
             f'<h3>{g["home_team"]} – {g["away_team"]}</h3><div class="ec-note">Équipes fictives (démonstration synthétique). '
             "Voici à quoi ressemblera une carte en direct : la prévision d'avant-match, puis son évolution.</div>"
             f'<div style="margin-top:14px">{prob_cell(g["p_home_final"], g["p_draw_final"], g["p_away_final"])}</div></div>')
    ad(728, 90)


def page_web():
    origin = st.session_state["mode"]
    sport = pick_sport()
    hero("La toile", "Qui a affronté qui.", "Chaque trait relie deux équipes qui se sont rencontrées sur la dernière saison en base ; "
         "la taille d'un point suit son Elo avant son dernier match.")
    demo_strip(origin)
    P = preds(origin, sport)
    F = P[P["status"] == "final"] if P is not None else None
    if F is None or F.empty:
        st.info("Pas de matchs terminés pour cette ligue.")
        ad(728, 90)
        return
    F = F[F["season"] == F["season"].max()]
    teams = sorted(set(F["home_team"]) | set(F["away_team"]))
    n = len(teams)
    pos = {t: (math.cos(2 * math.pi * k / n), math.sin(2 * math.pi * k / n)) for k, t in enumerate(teams)}
    xs, ys = [], []
    for h, a in F[["home_team", "away_team"]].drop_duplicates().itertuples(index=False):
        xs += [pos[h][0], pos[a][0], None]
        ys += [pos[h][1], pos[a][1], None]
    elo = {}
    for r in F.sort_values("game_date").itertuples():
        elo[r.home_team], elo[r.away_team] = r.elo_h, r.elo_a
    ev = pd.Series(elo).reindex(teams)
    size = 10 + 30 * (ev - ev.min()) / max(ev.max() - ev.min(), 1)
    fig = go.Figure([go.Scatter(x=xs, y=ys, mode="lines", line=dict(color="rgba(13,15,14,.12)", width=1), hoverinfo="skip"),
                     go.Scatter(x=[pos[t][0] for t in teams], y=[pos[t][1] for t in teams], mode="markers+text", text=teams,
                                textposition="top center", marker=dict(size=size, color=ACCENT),
                                hovertext=[f"{t} · Elo {ev[t]:.0f}" for t in teams], hoverinfo="text")])
    fig.update_layout(height=640, showlegend=False, plot_bgcolor="#fbfbf8", paper_bgcolor="#fbfbf8", margin=dict(l=10, r=10, t=10, b=10),
                      xaxis=dict(visible=False), yaxis=dict(visible=False, scaleanchor="x"))
    st.plotly_chart(fig, use_container_width=True)
    st.caption(f"Saison {F['season'].max()} · {n} équipes · {len(F)} matchs terminés.")
    ad(728, 90)


def page_player():
    hero("Fiche joueur", "Joueur Exemple", "Le moteur ne contient pas encore de données individuelles : cette fiche montre le format prévu.")
    html('<span class="ec-tag ex">Données d\'exemple</span><span class="ec-note">Chiffres fictifs, aucune prévision réelle.</span>')
    html(big_html([("Minutes / match", "31,4"), ("Points / match", "18,2"), ("Impact estimé", "+2,1")]))
    st.caption("Données d'exemple — à remplacer par une source joueurs autorisée avant toute publication.")


def page_team():
    origin = st.session_state["mode"]
    sport = pick_sport()
    demo_strip(origin)
    P = preds(origin, sport)
    if P is None:
        hero("Fiche équipe", "Aucune donnée", "Pas de prévisions pour cette ligue.")
        return
    team = st.selectbox("Équipe", sorted(set(P["home_team"]) | set(P["away_team"])))
    F = P[((P["home_team"] == team) | (P["away_team"] == team)) & (P["status"] == "final")].sort_values("game_date")
    hero(f"Fiche équipe · {config.SPORT_LABEL[sport]}", team)
    if F.empty:
        st.info("Aucun match terminé en base pour cette équipe.")
        return
    home = F["home_team"] == team
    elo = F["elo_h"].where(home, F["elo_a"])
    wins = int(((F["home_score"] > F["away_score"]) & home).sum() + ((F["away_score"] > F["home_score"]) & ~home).sum())
    html(big_html([("Elo (avant dernier match)", f"{elo.iloc[-1]:.0f}"), ("Matchs en base", len(F)), ("Victoires", wins)]))
    fig = go.Figure(go.Scatter(x=F["game_date"], y=elo, mode="lines", line_color=ACCENT))
    fig.update_layout(title="Elo avant chaque match", height=300, margin=dict(l=10, r=10, t=40, b=10), plot_bgcolor="#fff")
    st.plotly_chart(fig, use_container_width=True)
    html('<div class="ec-h2">Derniers matchs</div>')
    rec = F.tail(10).iloc[::-1]
    rh = rec["home_team"] == team
    st.dataframe(pd.DataFrame({
        "Date": rec["game_date"].dt.date, "Match": rec["home_team"] + " – " + rec["away_team"],
        "Score": rec["home_score"].astype(int).astype(str) + " - " + rec["away_score"].astype(int).astype(str),
        f"P({team}) prévue": rec["p_home_final"].where(rh, rec["p_away_final"]).map(pct), "Période": rec["segment"]}),
        use_container_width=True, hide_index=True)


# ---------------------------------------------------------------- outils (comportement existant conservé)
def page_simulation():
    origin = st.session_state["mode"]
    sport = pick_sport()
    R, S = report(origin, sport), sim(origin, sport)
    hero("Outils · simulation de recherche", "Simulation", "Test des règles de règlement à mise fixe d'une unité, sans recommandation. "
         "Ce n'est ni un conseil de mise ni une gestion de bankroll.")
    demo_strip(origin)
    if R is None or "simulation" not in R:
        st.info("Rendement non évaluable : pas de rapport.")
        return
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
        fig = go.Figure(go.Scatter(x=cv["date"], y=cv["cumul"], mode="lines", line_color=ACCENT))
        fig.update_layout(title="Profit cumulé (unités)", height=320, margin=dict(l=10, r=10, t=40, b=10), plot_bgcolor="#fff")
        st.plotly_chart(fig, use_container_width=True)
        st.caption(sm["avertissement"])
    if S is not None and len(S):
        with st.expander("Détail des cotes évaluées"):
            st.dataframe(S[S["segment"] == seg].tail(500), use_container_width=True, hide_index=True)
    cts = R.get("cotes", {})
    st.caption(f"Cotes importées : {cts.get('importees', 0)} · admissibles : {cts.get('admissibles', 0)} · "
               f"refusées (postérieures à la prévision) : {cts.get('refusees_posterieures_au_cutoff', 0)}")


def page_data():
    origin = st.session_state["mode"]
    hero("Outils", "Données", "Connecteurs, imports, licences.")
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
        return
    i1, i2 = st.columns(2)
    for col, kind, fn, sample in ((i1, "matchs", pipeline.import_games_csv, "games_example.csv"),
                                  (i2, "cotes", pipeline.import_odds_csv, "odds_example.csv")):
        with col:
            st.markdown(f"**{kind.capitalize()}** (colonnes : voir `samples/{sample}`)")
            spx = st.selectbox("Sport du fichier", list(config.SPORTS), key=f"sp_{kind}", format_func=config.SPORT_LABEL.get)
            upx = st.file_uploader(f"CSV de {kind} (données dont vous avez les droits)", type="csv", key=f"u_{kind}")
            if upx and st.button(f"Importer les {kind}"):
                with tempfile.TemporaryDirectory() as td:
                    pth = Path(td) / upx.name
                    pth.write_bytes(upx.getvalue())
                    try:
                        st.json(fn("real", spx, str(pth)))
                        st.cache_data.clear()
                    except Exception as ex:
                        st.error(f"Import refusé : {ex}")
    if st.button("Recalculer l'évaluation (réel)"):
        with st.spinner("Évaluation en cours…"):
            pipeline.run_all("real")
        st.cache_data.clear()
        st.success("Évaluation terminée.")


# ================================================================= cadre commun
PAGES = {
    "today": st.Page(page_today, title="Aujourd'hui", url_path="aujourdhui", default=True),
    "match": st.Page(page_match, title="Détail d'un match", url_path="match"),
    "proof": st.Page(page_proof, title="La preuve", url_path="preuve"),
    "leagues": st.Page(page_leagues, title="Ligues", url_path="ligues"),
    "live": st.Page(page_live, title="En direct", url_path="direct"),
    "web": st.Page(page_web, title="La toile", url_path="toile"),
    "player": st.Page(page_player, title="Fiche joueur", url_path="joueur"),
    "team": st.Page(page_team, title="Fiche équipe", url_path="equipe"),
    "sim": st.Page(page_simulation, title="Simulation", url_path="simulation"),
    "data": st.Page(page_data, title="Données", url_path="donnees"),
}
nav = st.navigation(list(PAGES.values()), position="hidden")

html(f'<div class="ec-banner">{BANNER}</div>')
h1, h2 = st.columns([3, 2], vertical_alignment="bottom")
h1.markdown('<div class="ec-brand">EDGE<span>COURT</span></div>', unsafe_allow_html=True)
with h2:
    st.radio("Données", ["real", "demo"], key="mode", horizontal=True, label_visibility="collapsed",
             format_func=lambda m: "Données réelles" if m == "real" else "Démonstration synthétique")
with st.container(horizontal=True, gap="small"):
    for p in PAGES.values():
        st.page_link(p)
st.divider()
nav.run()
