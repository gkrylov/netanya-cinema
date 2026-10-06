"""Данные (Markdown) → JSON для страницы.

Использование: python3 scripts/export_json.py [<папка>]   (по умолчанию public/data)

Пишет index.json, movies.json, watched.json и days/<date>.json.
JSON производный: не хранится в git, делается заново при каждой сборке.
"""

import json
import re
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

from common import AVAILABILITY_FILE, STATUS_FILE, DAYS_DIR, MOVIES_DIR, ROOT, TZ, WATCHED_FILE, now_il, read_md


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
    """Разделы «## Title» в watched.md → slug: {title, watched, rating, note}."""
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


def load_day(path):
    meta, _ = read_md(path)
    d = date.fromisoformat(str(meta["date"]))
    sessions = []
    for s in meta.get("sessions") or []:
        day = d + timedelta(days=1) if s.get("after_midnight") else d
        start = datetime.combine(day, datetime.strptime(s["time"], "%H:%M").time(), TZ)
        sessions.append({**s, "start": start.isoformat()})  # с поясом: браузер в любой стране поймёт верно
    offset = datetime.combine(d, datetime.min.time(), TZ).strftime("%z")
    return {"date": d.isoformat(), "weekday": meta.get("weekday"), "fetched_at": meta.get("fetched_at"),
            "utc_offset": f"{offset[:3]}:{offset[3:]}", "sessions": sessions}


def dump(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=1))


def export(out):
    out = Path(out)
    # пустые дни (Cinema City ещё ничего не выложил) не показываем как расписание
    days = [d for d in (load_day(p) for p in sorted(DAYS_DIR.glob("*.md"))) if d["sessions"]]
    avail = read_md(AVAILABILITY_FILE)[0] if AVAILABILITY_FILE.exists() else {}
    status = read_md(STATUS_FILE)[0] if STATUS_FILE.exists() else {}
    for day in days:
        dump(out / "days" / f"{day['date']}.json", day)
    dump(out / "movies.json", load_movies())
    dump(out / "watched.json", load_watched())
    dump(out / "index.json", {
        "generated": now_il().isoformat(timespec="seconds"),
        "dates": [d["date"] for d in days],
        "collected_at": avail.get("fetched_at"),
        "published_until": avail.get("published_until"),
        "published_dates": avail.get("published_dates") or [],
        "status": status,
    })
    return out


if __name__ == "__main__":
    print(export(sys.argv[1] if len(sys.argv) > 1 else ROOT / "public" / "data"))
