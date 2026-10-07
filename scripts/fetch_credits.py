"""Сцены во время и после титров → поля карточки фильма.

Использование: python3 scripts/fetch_credits.py [<slug> ...]   (без аргументов: все карточки)
Обычно вызывается из fetch_schedule.py для фильмов из расписания.

Источник: aftercredits.com (открытый WordPress API, robots.txt не запрещает).
В записи о фильме два ответа: «Are There Any Extras During The Credits? Yes/No»
и «... After The Credits? Yes/No». Запасной источник: метки TMDB
duringcreditsstinger / aftercreditsstinger (только «есть», их отсутствие ничего не значит).

Поля карточки:
  credits_during, credits_after: yes / no / (нет поля = неизвестно)
  credits_source: aftercredits / tmdb / manual
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
FIELDS = ["credits_during", "credits_after", "credits_source", "credits_url", "credits_checked"]


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

    found = from_aftercredits([meta.get("title_en"), meta.get("title_original")], meta.get("year"))
    if found and (found["during"] or found["after"]):
        new = {"credits_during": found["during"], "credits_after": found["after"],
               "credits_source": "aftercredits", "credits_url": found["url"]}
    elif meta.get("tmdb_id"):
        t = from_tmdb(meta["tmdb_id"])
        new = ({"credits_during": t["during"], "credits_after": t["after"], "credits_source": "tmdb"}
               if t["during"] or t["after"] else {})
    else:
        new = {}
    new["credits_checked"] = today_il().isoformat()

    out = {k: v for k, v in meta.items() if k not in FIELDS}
    out.update({k: v for k, v in new.items() if v})
    write_md(path, out, body)
    return out


def credits_badge(meta):
    """Короткая пометка для расписания: mid / post / mid+post."""
    parts = [n for k, n in (("credits_during", "mid"), ("credits_after", "post")) if meta.get(k) == "yes"]
    return "+".join(parts)


if __name__ == "__main__":
    slugs = sys.argv[1:] or sorted(p.stem for p in MOVIES_DIR.glob("*.md"))
    for s in slugs:
        m = update_credits(s)
        print(f"{s}: during={m.get('credits_during', '?')} after={m.get('credits_after', '?')} "
              f"({m.get('credits_source', 'unknown')})")
