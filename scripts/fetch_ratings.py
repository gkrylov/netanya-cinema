"""Рейтинги и деньги: IMDb, Rotten Tomatoes, бюджет и сборы (TMDB) → карточки фильмов.

Использование: python3 scripts/fetch_ratings.py [<slug> ...]   (без аргументов: все карточки)
Обычно вызывается из fetch_schedule.py для фильмов из расписания.
"""

import gzip
import html
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

from common import CACHE, MOVIES_DIR, UA, http_get, read_md, today_il, write_md
from fetch_movie import tmdb

IMDB_RATINGS_URL = "https://datasets.imdbws.com/title.ratings.tsv.gz"
BROWSER_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/128.0 Safari/537.36")

# Поля, которые этот скрипт перезаписывает при каждом запуске
FIELDS = ["imdb_rating", "imdb_votes", "rt_critics", "rt_audience", "rt_url",
          "budget_usd", "revenue_usd", "ratings_checked"]


# --- IMDb: официальный файл title.ratings.tsv.gz ---------------------------

_imdb = None


def imdb_ratings():
    """tconst → (рейтинг, голоса). Файл перекачивается, если старше суток."""
    global _imdb
    if _imdb is not None:
        return _imdb
    path = CACHE / "title.ratings.tsv.gz"
    if not path.exists() or time.time() - path.stat().st_mtime > 86400:
        CACHE.mkdir(parents=True, exist_ok=True)
        req = urllib.request.Request(IMDB_RATINGS_URL, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=120) as r:
            path.write_bytes(r.read())
    _imdb = {}
    with gzip.open(path, "rt") as f:
        next(f)
        for line in f:
            tconst, rating, votes = line.rstrip("\n").split("\t")
            _imdb[tconst] = (float(rating), int(votes))
    return _imdb


# --- Rotten Tomatoes -------------------------------------------------------

def _norm(s):
    return re.sub(r"[^\w]+", "", html.unescape(s or "").lower())


def _rt_get(url):
    time.sleep(0.5)
    return http_get(url, headers={"User-Agent": BROWSER_UA}, as_json=False)


def rt_find(titles, year):
    """URL страницы фильма на RT: совпадение названия и год ±1."""
    for title in titles:
        if not title:
            continue
        page = _rt_get("https://www.rottentomatoes.com/search?" +
                       urllib.parse.urlencode({"search": title}))
        for row in re.findall(r"<search-page-media-row(.*?)</search-page-media-row>", page, re.S):
            y = re.search(r'release-year="(\d*)"', row)
            url = re.search(r'href="(https://www\.rottentomatoes\.com/m/[^"]+)"', row)
            alt = re.search(r'alt="([^"]*)"', row)
            if not (y and url and alt) or not y.group(1):
                continue
            if _norm(alt.group(1)) == _norm(title) and (not year or abs(int(y.group(1)) - year) <= 1):
                return url.group(1)
    return None


def _json_after(page, key):
    i = page.find(f'"{key}":{{')
    if i < 0:
        return {}
    try:
        return json.JSONDecoder().raw_decode(page, i + len(key) + 3)[0]
    except ValueError:
        return {}


def rt_scores(url):
    page = _rt_get(url)
    critics = _json_after(page, "criticsScore").get("score")
    audience = _json_after(page, "audienceScore").get("score")
    return (int(critics) if critics else None), (int(audience) if audience else None)


# --- Сборка ----------------------------------------------------------------

def update_ratings(slug):
    path = MOVIES_DIR / f"{slug}.md"
    meta, body = read_md(path)
    new = {}

    if meta.get("tmdb_id"):
        d = tmdb(f"/movie/{meta['tmdb_id']}")
        new["budget_usd"] = d.get("budget") or None
        new["revenue_usd"] = d.get("revenue") or None
        if not meta.get("imdb_id") and d.get("imdb_id"):
            meta["imdb_id"] = d["imdb_id"]

    if meta.get("imdb_id"):
        r = imdb_ratings().get(meta["imdb_id"])
        if r:
            new["imdb_rating"], new["imdb_votes"] = r

    try:
        url = meta.get("rt_url") or rt_find(
            [meta.get("title_en"), meta.get("title_original")], meta.get("year"))
        if url:
            try:
                new["rt_critics"], new["rt_audience"] = rt_scores(url)
                new["rt_url"] = url
            except urllib.error.HTTPError as e:
                if e.code != 404:
                    raise  # 404: у RT битая страница фильма, оценок нет
    except Exception as e:
        print(f"  RT недоступен для {slug}: {e}")
        for k in ("rt_url", "rt_critics", "rt_audience"):
            new[k] = meta.get(k)  # оставить прежние значения

    new["ratings_checked"] = today_il().isoformat()

    # Поля рейтингов вставляются перед служебными полями карточки
    out = {k: v for k, v in meta.items() if k not in FIELDS and k not in ("needs_review", "sources_checked")}
    out.update({k: new.get(k) for k in FIELDS if new.get(k) is not None})
    for k in ("needs_review", "sources_checked"):
        if k in meta:
            out[k] = meta[k]
    write_md(path, out, body)
    return out


def fmt_money(v):
    if not v:
        return None
    return f"${v / 1e6:,.0f}M" if v >= 1e6 else f"${v:,}"


def ratings_line(meta):
    """Короткая строка для расписания: IMDb 7.4 · RT 88%."""
    parts = []
    if meta.get("imdb_rating"):
        parts.append(f"IMDb {meta['imdb_rating']}")
    if meta.get("rt_critics") is not None:
        parts.append(f"RT {meta['rt_critics']}%")
    return " · ".join(parts)


if __name__ == "__main__":
    slugs = sys.argv[1:] or sorted(p.stem for p in MOVIES_DIR.glob("*.md"))
    for s in slugs:
        m = update_ratings(s)
        print(f"{s}: IMDb {m.get('imdb_rating')} ({m.get('imdb_votes')}), "
              f"RT {m.get('rt_critics')}/{m.get('rt_audience')}, "
              f"budget {fmt_money(m.get('budget_usd'))}, revenue {fmt_money(m.get('revenue_usd'))}")
