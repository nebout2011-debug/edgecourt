"""Actualités sportives : flux RSS publics et gratuits (ESPN, BBC Sport), sans clé d'API.

Rien n'est inventé : un flux injoignable est simplement omis, un article sans date est écarté,
une image n'apparaît que si le flux la fournit, et tout article qui parle de paris est exclu.
"""
from __future__ import annotations

import calendar
import re
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from html import escape

import feedparser

ESPN, BBC = "https://www.espn.com/espn/rss/", "https://feeds.bbci.co.uk/sport/football/"
FEEDS = [  # (url, source, ligue ; None = actualité générale, visible seulement sous « Toutes »)
    (ESPN + "nba/news", "ESPN", "NBA"),
    (ESPN + "nfl/news", "ESPN", "NFL"),
    (ESPN + "wnba/news", "ESPN", "WNBA"),
    (ESPN + "nhl/news", "ESPN", "NHL"),
    (ESPN + "mlb/news", "ESPN", "MLB"),
    (ESPN + "soccer/news", "ESPN", None),
    (BBC + "premier-league/rss.xml", "BBC Sport", "Premier League"),
    (BBC + "championship/rss.xml", "BBC Sport", "Championship"),
    (BBC + "spanish-la-liga/rss.xml", "BBC Sport", "La Liga"),
    (BBC + "italian-serie-a/rss.xml", "BBC Sport", "Serie A"),
    (BBC + "german-bundesliga/rss.xml", "BBC Sport", "Bundesliga"),
    (BBC + "french-ligue-one/rss.xml", "BBC Sport", "Ligue 1"),
    (BBC + "european/rss.xml", "BBC Sport", None),
]
LEAGUES = ("NBA", "Premier League", "NFL", "La Liga", "Serie A", "Bundesliga", "Ligue 1", "Championship", "WNBA", "NHL", "MLB")
ALL = "Toutes"
UNAVAILABLE = "Actualités indisponibles pour l'instant"
BETTING = re.compile(r"\b(bets?|betting|bettors?|odds|sportsbooks?|parlays?|wagers?|wagering|gambl\w*|bookmakers?|bookies?"
                     r"|paris sportifs|parieurs?|cotes?)\b", re.I)


def fetch(url: str, timeout: float = 6) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (EDGECOURT news reader)"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read(2_000_000)  # un flux RSS fait quelques dizaines de Ko : on borne la lecture


def parse(raw: bytes, source: str, league: str | None) -> list[dict]:
    out = []
    for e in feedparser.parse(raw).entries:
        title, link = (e.get("title") or "").strip(), e.get("link") or ""
        t = e.get("published_parsed") or e.get("updated_parsed")
        if not title or not link.startswith("https://") or not t or BETTING.search(f"{title} {e.get('summary') or ''}"):
            continue
        media = (e.get("media_thumbnail") or []) + (e.get("media_content") or [])
        img = next((m["url"] for m in media if str(m.get("url", "")).startswith("https://")), None)
        out.append({"title": title, "link": link, "source": source, "league": league, "ts": calendar.timegm(t), "image": img})
    return out


def load() -> list[dict]:
    """Tous les flux en parallèle, du plus récent au plus ancien, sans doublon. [] si tout est injoignable."""
    def one(feed):
        try:
            return parse(fetch(feed[0]), feed[1], feed[2])
        except Exception:  # flux injoignable ou illisible : on l'omet, jamais de remplacement inventé
            return []
    with ThreadPoolExecutor(8) as ex:
        items = [i for chunk in ex.map(one, FEEDS) for i in chunk]
    seen, out = set(), []
    for i in sorted(items, key=lambda i: (-i["ts"], i["league"] is None)):  # à égalité, l'article tagué par ligue gagne
        key = i["link"].split("?")[0]
        if key not in seen:
            seen.add(key)
            out.append(i)
    return out


def only(items: list[dict], league: str | None) -> list[dict]:
    return items if league in (None, ALL) else [i for i in items if i["league"] == league]


def ago(ts: float, now: float | None = None) -> str:
    s = max(0, int((time.time() if now is None else now) - ts))
    if s < 3600:
        return f"il y a {max(1, s // 60)} min"
    return f"il y a {s // 3600} h" if s < 86400 else f"il y a {s // 86400} j"


def meta(i: dict, now: float | None = None) -> str:
    return " · ".join(x for x in (i["source"], i["league"], ago(i["ts"], now)) if x)


def featured_html(items: list[dict], now: float | None = None) -> str:
    """Carrousel « À la une » (rendu dans un iframe : rotation 8 s, flèches, points, pause au survol/focus)."""
    slides, dots = [], []
    for k, i in enumerate(items):
        pic = f'<img src="{escape(i["image"])}" alt="">' if i["image"] else f'<span>{escape(i["league"] or i["source"])}</span>'
        slides.append(f'<a class="s{" on" if k == 0 else ""}" href="{escape(i["link"])}" target="_blank" rel="noopener noreferrer">'
                      f'<div class="img">{pic}</div><div class="t">{escape(i["title"])}</div><div class="m">{escape(meta(i, now))}</div></a>')
        dots.append(f'<button class="d" aria-label="Article {k + 1}" aria-current="{"true" if k == 0 else "false"}"></button>')
    return f"""<style>
*{{box-sizing:border-box}} body{{margin:0;font-family:"Segoe UI Variable Display","Inter","Helvetica Neue",system-ui,sans-serif;color:#0d0f0e}}
.c{{border:1px solid #e4e4de;border-radius:8px;overflow:hidden;background:#fff}}
.s{{display:none;color:inherit;text-decoration:none}} .s.on{{display:block}} .s:hover .t{{text-decoration:underline}}
a:focus-visible,button:focus-visible{{outline:2px solid #00C853;outline-offset:-2px}}
.img{{height:140px;background:#0d0f0e;display:flex;align-items:flex-end;padding:10px;position:relative}}
.img img{{position:absolute;inset:0;width:100%;height:100%;object-fit:cover}}
.img span{{font:600 .7rem ui-monospace,Consolas,monospace;letter-spacing:.12em;text-transform:uppercase;color:#00C853}}
.t{{font-weight:700;font-size:.98rem;line-height:1.3;padding:10px 12px 4px;height:4.6em;overflow:hidden;
   display:-webkit-box;-webkit-line-clamp:3;-webkit-box-orient:vertical}}
.m{{font:.72rem ui-monospace,Consolas,monospace;color:#5b615e;padding:0 12px 8px}}
.nav{{display:flex;align-items:center;justify-content:space-between;padding:4px 6px;border-top:1px solid #e4e4de}}
button{{border:0;background:none;cursor:pointer;color:#0d0f0e;font-size:1.2rem;min-width:32px;min-height:28px}}
.d{{width:9px;height:9px;min-width:0;min-height:0;border-radius:50%;background:#c9ccc9;padding:0;margin:0 3px}}
.d[aria-current=true]{{background:#00C853}}
</style>
<div class="c" id="c" role="region" aria-roledescription="carrousel" aria-label="À la une">
{''.join(slides)}
<div class="nav"><button id="p" aria-label="Article précédent">‹</button><div>{''.join(dots)}</div><button id="n" aria-label="Article suivant">›</button></div>
</div>
<script>
const S=[...document.querySelectorAll('.s')],D=[...document.querySelectorAll('.d')],c=document.getElementById('c');let i=0,hold=false;
function go(k){{i=(k+S.length)%S.length;S.forEach((s,j)=>s.classList.toggle('on',j==i));D.forEach((d,j)=>d.setAttribute('aria-current',j==i))}}
document.getElementById('p').onclick=()=>go(i-1);document.getElementById('n').onclick=()=>go(i+1);D.forEach((d,j)=>d.onclick=()=>go(j));
['mouseenter','focusin'].forEach(e=>c.addEventListener(e,()=>hold=true));['mouseleave','focusout'].forEach(e=>c.addEventListener(e,()=>hold=false));
if(S.length>1&&!matchMedia('(prefers-reduced-motion: reduce)').matches)setInterval(()=>{{if(!hold)go(i+1)}},8000);
</script>"""


def list_html(items: list[dict], now: float | None = None) -> str:
    return '<ul class="ec-news-list">' + "".join(
        f'<li><a href="{escape(i["link"])}" target="_blank" rel="noopener noreferrer"><span class="t">{escape(i["title"])}</span>'
        f'<span class="m">{escape(meta(i, now))}</span></a></li>' for i in items) + "</ul>"
