"""Сборка site/index.html из data/: дни, карточки фильмов, заметки.

Использование: python3 scripts/build_site.py
Вызывается в конце fetch_schedule.py. Данные встраиваются в страницу JSON-ом,
поэтому она открывается прямо из файла, без сервера.
"""

import json
import re
from datetime import date, datetime, timedelta

from common import DAYS_DIR, MOVIES_DIR, ROOT, WATCHED_FILE, read_md

TEMPLATE = ROOT / "scripts" / "site_template.html"
OUT = ROOT / "site" / "index.html"


def movie_overview(body):
    """Текст описания из тела карточки: без заголовка и строки с оригинальным названием."""
    lines = [l for l in body.strip().splitlines()
             if not l.startswith("# ") and not re.fullmatch(r"\*[^*]+\*", l.strip())]
    text = "\n".join(lines).strip()
    return re.sub(r"\n{2,}", "\n\n", text) or None


def load_movies():
    movies = {}
    for p in sorted(MOVIES_DIR.glob("*.md")):
        meta, body = read_md(p)
        meta["overview"] = movie_overview(body)
        movies[p.stem] = meta
    return movies


def load_watched():
    """Разделы «## Title» в watched.md → slug: {watched, rating, note}."""
    if not WATCHED_FILE.exists():
        return {}
    out = {}
    for section in re.split(r"^## ", WATCHED_FILE.read_text(), flags=re.M)[1:]:
        title, _, rest = section.partition("\n")
        fields, note = {}, []
        for line in rest.strip().splitlines():
            m = re.match(r"^(movie|watched|rating):\s*(.*)$", line)
            if m:
                fields[m.group(1)] = m.group(2).strip() or None
            else:
                note.append(line)
        if fields.get("movie"):
            out[fields["movie"]] = {
                "title": title.strip(),
                "watched": fields.get("watched"),
                "rating": fields.get("rating"),
                "note": "\n".join(note).strip() or None,
            }
    return out


def load_days():
    days = []
    for p in sorted(DAYS_DIR.glob("*.md")):
        meta, _ = read_md(p)
        d = date.fromisoformat(str(meta["date"]))
        sessions = []
        for s in meta.get("sessions") or []:
            day = d + timedelta(days=1) if s.get("after_midnight") else d
            s = dict(s)
            s["start"] = f"{day.isoformat()}T{s['time']}"
            sessions.append(s)
        days.append({"date": d.isoformat(), "weekday": meta.get("weekday"),
                     "fetched_at": meta.get("fetched_at"), "sessions": sessions})
    return days


def build():
    data = {
        "generated": datetime.now().astimezone().isoformat(timespec="seconds"),
        "days": load_days(),
        "movies": load_movies(),
        "watched": load_watched(),
    }
    payload = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    html = TEMPLATE.read_text().replace("/*__DATA__*/null", payload)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(html)
    return OUT


if __name__ == "__main__":
    print(build())
