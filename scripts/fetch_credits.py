"""Сцены во время и после титров → поля карточки фильма.

Использование: python3 scripts/fetch_credits.py [<slug> ...]   (без аргументов: все карточки)
Обычно вызывается из fetch_schedule.py для фильмов из расписания.

Источники по старшинству:
1. aftercredits.com (открытый WordPress API, robots.txt не запрещает): два ответа,
   «Are There Any Extras During The Credits? Yes/No» и «... After The Credits? Yes/No».
   Это окончательный ответ, в том числе «нет».
2. Википедия, «List of films with post-credits scenes (2020s)»: там только фильмы,
   где сцена есть, поэтому годится лишь для «да». Место (mid / end) берётся из текста
   описания; если оно не названо, ставится credits_extra: yes.
3. Метки TMDB duringcreditsstinger / aftercreditsstinger: тоже только «да».

Поля карточки:
  credits_during, credits_after: yes / no / (нет поля = неизвестно)
  credits_extra: yes, если сцена есть, но неизвестно, во время или после титров
  credits_source: aftercredits / wikipedia / tmdb / manual (через «+», если несколько)
  credits_url: запись на aftercredits.com (описание сцен, спойлеры)
  credits_checked: дата проверки

Ответ aftercredits.com окончательный и больше не перепроверяется; источник
manual (вписан руками) не трогается никогда. Пока ответа нет, проверка
повторяется при каждом сборе: записи о новинках появляются после премьеры в США.
Текст описаний не копируется: он принадлежит aftercredits.com, а сайт публичный.
"""

import html
import re
import sys
import time

from common import MOVIES_DIR, http_get, read_md, today_il, write_md
from fetch_movie import tmdb

API = "https://aftercredits.com/wp-json/wp/v2/posts"
WIKI_API = "https://en.wikipedia.org/w/api.php"
WIKI_PAGE = "List_of_films_with_post-credits_scenes_(2020s)"
FIELDS = ["credits_during", "credits_after", "credits_extra", "credits_source", "credits_url", "credits_checked"]


def _norm(s):
    s = html.unescape(s or "")
    # aftercredits пишет названия «по-библиотечному»: «Odyssey, The» → «The Odyssey»
    m = re.match(r"^(.*),\s*(The|A|An)$", s.strip(), re.I)
    if m:
        s = f"{m.group(2)} {m.group(1)}"
    return re.sub(r"[^\w]+", "", s.lower())


def _answer(text, where):
    m = re.search(rf"Are There Any Extras {where} The Credits\?\s*(Yes|No)\b", text, re.I)
    return m.group(1).lower() if m else None


def from_aftercredits(titles, year):
    """{'during','after','url'} по записи о фильме, или None, если записи нет."""
    for title in [t for t in titles if t]:
        time.sleep(1)  # бережно к чужому сайту
        posts = http_get(API, {"search": title, "per_page": 10, "_fields": "title,link,content"})
        for post in posts:
            raw = html.unescape(post["title"]["rendered"])
            m = re.match(r"^(.*?)\s*\((\d{4})\)", raw)
            if not m or _norm(m.group(1)) != _norm(title):
                continue
            if year and abs(int(m.group(2)) - year) > 1:
                continue
            text = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", post["content"]["rendered"])))
            return {"during": _answer(text, "During"), "after": _answer(text, "After"), "url": post["link"]}
    return None


_wiki = None


def wikipedia_entries():
    """{(название, год): текст описания} из списка Википедии; читается один раз за запуск."""
    global _wiki
    if _wiki is not None:
        return _wiki
    data = http_get(WIKI_API, {"action": "parse", "page": WIKI_PAGE, "prop": "wikitext",
                               "format": "json", "formatversion": 2})
    _wiki, year = {}, None
    for row in data["parse"]["wikitext"].split("\n|-"):
        y = re.search(r'id="(\d{4})"|rowspan="\d+"\s*\|\s*(\d{4})', row)
        if y:
            year = int(y.group(1) or y.group(2))
        t = re.search(r"''\[\[([^\]|]+)(?:\|([^\]]+))?\]\]''", row)
        if t and year:
            title = t.group(2) or re.sub(r"\s*\((?:\d{4} )?film\)$", "", t.group(1))
            _wiki[(_norm(title), year)] = row[t.end():]
    return _wiki


def from_wikipedia(titles, year):
    """{'during','after','extra'}: только «yes» или None; None целиком, если фильма в списке нет."""
    entries = wikipedia_entries()
    for title in [t for t in titles if t]:
        for y in ([year, year - 1, year + 1] if year else []):
            desc = entries.get((_norm(title), y))
            if desc is None:
                continue
            d = desc.lower()
            during = "mid-credits" in d or "during the credits" in d
            after = bool(re.search(r"post-credits|end-credits|after the (?:end )?credits", d))
            return {"during": "yes" if during else None, "after": "yes" if after else None,
                    "extra": None if during or after else "yes"}
    return None


def from_tmdb(tmdb_id):
    kws = {k["name"] for k in tmdb(f"/movie/{tmdb_id}/keywords").get("keywords", [])}
    return {"during": "yes" if "duringcreditsstinger" in kws else None,
            "after": "yes" if "aftercreditsstinger" in kws else None}


def update_credits(slug):
    path = MOVIES_DIR / f"{slug}.md"
    meta, body = read_md(path)
    if meta.get("credits_source") == "manual":
        return meta
    if meta.get("credits_source") == "aftercredits" and meta.get("credits_during") and meta.get("credits_after"):
        return meta  # окончательный ответ уже есть

    titles = [meta.get("title_en"), meta.get("title_original")]
    found = from_aftercredits(titles, meta.get("year"))
    if found and (found["during"] or found["after"]):
        new = {"credits_during": found["during"], "credits_after": found["after"],
               "credits_source": "aftercredits", "credits_url": found["url"]}
    else:
        # Только подтверждения «да» из Википедии и TMDB; их отсутствие ничего не значит
        new, sources = {}, []
        hits = [("wikipedia", from_wikipedia(titles, meta.get("year")))]
        if meta.get("tmdb_id"):
            hits.append(("tmdb", from_tmdb(meta["tmdb_id"])))
        for name, hit in hits:
            if not hit or not any(hit.values()):
                continue
            sources.append(name)
            for k in ("during", "after", "extra"):
                if hit.get(k) == "yes":
                    new[f"credits_{k}"] = "yes"
        if new.get("credits_during") or new.get("credits_after"):
            new.pop("credits_extra", None)  # место уже известно
        if sources:
            new["credits_source"] = "+".join(sources)
    new["credits_checked"] = today_il().isoformat()

    out = {k: v for k, v in meta.items() if k not in FIELDS}
    out.update({k: v for k, v in new.items() if v})
    write_md(path, out, body)
    return out


def stay_label(meta):
    """Ответ на вопрос «оставаться ли после фильма»: Stay: … / No extra scenes / None (неизвестно)."""
    mid, end = meta.get("credits_during") == "yes", meta.get("credits_after") == "yes"
    if mid and end:
        return "Stay: mid + end"
    if mid:
        return "Stay: mid-credits"
    if end:
        return "Stay: end"
    if meta.get("credits_extra") == "yes":
        return "Stay: extra scene"
    if meta.get("credits_during") == "no" and meta.get("credits_after") == "no":
        return "No extra scenes"
    return None


if __name__ == "__main__":
    slugs = sys.argv[1:] or sorted(p.stem for p in MOVIES_DIR.glob("*.md"))
    for s in slugs:
        m = update_credits(s)
        print(f"{s}: {stay_label(m) or 'unknown'} ({m.get('credits_source', '-')})")
