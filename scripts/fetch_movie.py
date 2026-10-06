"""Карточка фильма: Cinema City (коллекция SyncFeatures) + TMDB → data/movies/<slug>.md

Использование: python3 scripts/fetch_movie.py <MovieId> [<MovieId> ...] [--refresh]
Обычно вызывается из fetch_schedule.py.
"""

import html
import re
import sys

import cinema_city
from common import (MOVIES_DIR, http_get, load_env, parse_cc_name, today_il,
                    read_md, slugify, write_md)

TMDB = "https://api.themoviedb.org/3"
SHORT_COUNTRY = {"United States of America": "USA", "United Kingdom": "UK"}

def _tmdb_headers():
    env = load_env()
    tok = env.get("TMDB_READ_TOKEN")
    if tok:
        return {"Authorization": f"Bearer {tok}", "Accept": "application/json"}, {}
    return {}, {"api_key": env["TMDB_API_KEY"]}


def tmdb(path, **params):
    headers, auth = _tmdb_headers()
    return http_get(TMDB + path, {**params, **auth}, headers=headers)


_languages = None


def language_name(iso):
    """ISO 639-1 → английское название языка по справочнику TMDB."""
    global _languages
    if _languages is None:
        try:
            _languages = {l["iso_639_1"]: l["english_name"] for l in tmdb("/configuration/languages")}
        except Exception:
            _languages = {}
    return _languages.get(iso) or iso


# --- Cinema City -----------------------------------------------------------

def fetch_cc_movie(movie_id):
    """Фильм с нового сайта Cinema City (коллекция SyncFeatures)."""
    f = cinema_city.feature(movie_id) or {}
    synopsis = f.get("synopsis_he")
    if synopsis:
        synopsis = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", synopsis))).strip()
    return {
        "title_he": f.get("title_he") or "",
        "title_en": f.get("title_en"),
        "genre_he": f.get("genre_he"),
        "runtime_min": f.get("runtime_min"),
        "premiere_il": f.get("premiere_il"),
        "age_he": f.get("age_he"),
        "synopsis_he": synopsis or None,
    }


def age_rating(age_he):
    if not age_he:
        return None
    if "לכל" in age_he:
        return "all ages"
    m = re.search(r"\d+", age_he)
    return f"{m.group(0)}+" if m else age_he


# --- TMDB: поиск соответствия ----------------------------------------------

def _norm(s):
    return re.sub(r"[^\w]+", "", (s or "").lower())


def tmdb_match(title_en, title_he, premiere):
    """Вернуть (tmdb_id, уверенность). Уверенность: exact / fuzzy / none."""
    year = int(premiere[:4]) if premiere else None
    candidates = []
    queries = []
    if title_en:
        queries.append((title_en, "en-US"))
    if title_he:
        queries.append((title_he, "he-IL"))
    for q, lang in queries:
        try:
            res = tmdb("/search/movie", query=q, language=lang, include_adult="false")["results"]
        except Exception:
            continue
        for r in res[:10]:
            score = 0
            titles = {_norm(r.get("title")), _norm(r.get("original_title"))}
            if _norm(q) in titles:
                score += 10
            elif any(_norm(q) and (_norm(q) in t or t in _norm(q)) for t in titles if t):
                score += 3
            ry = int(r["release_date"][:4]) if r.get("release_date") else None
            if year and ry:
                score += max(0, 3 - abs(year - ry))  # свежие фильмы; переиздания без бонуса
            score += min(r.get("popularity", 0), 50) / 50
            candidates.append((score, r["id"]))
        if candidates and max(candidates)[0] >= 10:
            break
    if not candidates:
        return None, "none"
    best = max(candidates)
    return best[1], ("exact" if best[0] >= 10 else "fuzzy")


def spoken_languages(details):
    """Языки, на которых говорят в фильме; первый считается основным."""
    return [language_name(l["iso_639_1"]) for l in details.get("spoken_languages", [])]


def tmdb_details(tmdb_id):
    en = tmdb(f"/movie/{tmdb_id}", language="en-US")
    return {
        "tmdb_id": tmdb_id,
        "imdb_id": en.get("imdb_id") or None,
        "title_en": en.get("title"),
        "title_original": en.get("original_title"),
        "year": int(en["release_date"][:4]) if en.get("release_date") else None,
        "country": [SHORT_COUNTRY.get(c["name"], c["name"]) for c in en.get("production_countries", [])],
        "original_language": language_name(en.get("original_language")),
        "spoken_languages": spoken_languages(en),
        "genre": [g["name"] for g in en.get("genres", [])],
        "runtime_min": en.get("runtime") or None,
        "overview": en.get("overview") or None,
    }


# --- Файлы фильмов ---------------------------------------------------------

def load_index():
    """cc_movie_id → slug, tmdb_id → slug по существующим файлам."""
    by_cc, by_tmdb, by_he = {}, {}, {}
    for p in MOVIES_DIR.glob("*.md"):
        meta, _ = read_md(p)
        for cid in meta.get("cc_movie_id") or []:
            by_cc[int(cid)] = p.stem
        if meta.get("tmdb_id"):
            by_tmdb[int(meta["tmdb_id"])] = p.stem
        if meta.get("title_he"):
            by_he[meta["title_he"]] = p.stem
    return by_cc, by_tmdb, by_he


def _add_version(slug, movie_id, dubbed):
    path = MOVIES_DIR / f"{slug}.md"
    meta, body = read_md(path)
    ids = [int(x) for x in meta.get("cc_movie_id") or []]
    if movie_id not in ids:
        meta["cc_movie_id"] = ids + [movie_id]
    if dubbed:
        meta["dubbed_available"] = True
    write_md(path, meta, body)
    return slug


def render_body(meta, overview, synopsis_he):
    title = meta.get("title_en") or meta.get("title_he")
    head = f"# {title}"
    if meta.get("year"):
        head += f" ({meta['year']})"
    parts = [head]
    if meta.get("title_original") and meta["title_original"] != title:
        parts.append(f"*{meta['title_original']}*")
    if overview:
        parts.append(overview)
    elif synopsis_he:
        parts.append("Cinema City synopsis (Hebrew, no English overview on TMDB):\n\n" + synopsis_he)
    return "\n\n".join(parts)


def ensure_movie(movie_id, cc_name, refresh=False):
    """Создать или дополнить карточку для MovieId. Вернуть slug."""
    by_cc, by_tmdb, by_he = load_index()
    parsed = parse_cc_name(cc_name)
    dubbed = (parsed["screen_language"] or "").startswith("dubbed")

    if not refresh:
        # Уже знакомый MovieId, или другая версия того же фильма (то же название на иврите)
        slug = by_cc.get(movie_id) or by_he.get(parsed["base"])
        if slug:
            return _add_version(slug, movie_id, dubbed)

    cc = fetch_cc_movie(movie_id)
    title_he = parse_cc_name(cc["title_he"] or cc_name)["base"] or parsed["base"]
    title_en = cc["title_en"]
    if title_en and re.search(r"[\u0400-\u04FF]", title_en):
        title_en = None  # у русского дубляжа после «/» стоит русское название
    if title_en and not re.search(r"[A-Za-z]", title_en):
        title_en = None
    if title_en:
        title_en = parse_cc_name(title_en)["base"]
        title_en = re.sub(r"\s*[-–]\s*(DUBBED|ENGLISH|HEBREW|RUSSIAN)$", "", title_en, flags=re.I)
        if title_en.isupper():
            title_en = title_en.title()

    tmdb_id, confidence = tmdb_match(title_en, title_he, cc["premiere_il"])
    details = tmdb_details(tmdb_id) if tmdb_id else {}

    # Та же картина под другим MovieId (дубляж / английская версия) → дописать в карточку
    if tmdb_id and confidence == "exact" and tmdb_id in by_tmdb and not refresh:
        return _add_version(by_tmdb[tmdb_id], movie_id, dubbed)

    if confidence == "exact":
        title_en = details.get("title_en") or title_en
    slug = slugify(title_en or "")
    if slug and confidence == "exact" and details.get("year"):
        slug = f"{slug}-{details['year']}"
    if not re.search(r"[a-z]", slug):
        slug = f"cc-{movie_id}"

    path = MOVIES_DIR / f"{slug}.md"
    old = read_md(path)[0] if path.exists() else {}
    ids = sorted({int(x) for x in old.get("cc_movie_id") or []} | {movie_id})
    meta = {
        "slug": slug,
        "cc_movie_id": ids,
        "title_he": title_he,
        "title_en": title_en,
        "title_original": details.get("title_original"),
        "year": details.get("year"),
        "country": details.get("country") or [],
        "original_language": details.get("original_language"),
        "spoken_languages": details.get("spoken_languages") or [],
        "genre": details.get("genre") or [],
        "runtime_min": cc["runtime_min"] or details.get("runtime_min"),
        "age_rating": age_rating(cc["age_he"]),
        "premiere_il": cc["premiere_il"],
        "kids": parsed["kids"] or None,
        "dubbed_available": dubbed or bool(old.get("dubbed_available")),
        "tmdb_id": tmdb_id if confidence == "exact" else None,
        "tmdb_guess": tmdb_id if confidence == "fuzzy" else None,
        "imdb_id": details.get("imdb_id") if confidence == "exact" else None,
        "needs_review": confidence != "exact",
        "sources_checked": today_il().isoformat(),
    }
    if confidence != "exact":
        # Неуверенное совпадение: TMDB-поля не подставляем, только подсказка
        for k in ("title_original", "year", "original_language"):
            meta[k] = None
        meta["country"] = meta["spoken_languages"] = meta["genre"] = []
    meta = {k: v for k, v in meta.items() if v is not None or k in (
        "title_original", "year", "original_language", "tmdb_id")}
    body = render_body(meta, details.get("overview") if confidence == "exact" else None,
                       cc["synopsis_he"])
    write_md(path, meta, body)
    return slug


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    refresh = "--refresh" in sys.argv
    for a in args:
        mid = int(a)
        print(ensure_movie(mid, (cinema_city.feature(mid) or {}).get("title_he") or "", refresh=refresh))
