"""Расписание Cinema City Netanya → data/days/<YYYY-MM-DD>.md

Использование:
  python3 scripts/fetch_schedule.py              ближайшие выходные (пт + сб)
  python3 scripts/fetch_schedule.py 2026-09-27   конкретные даты
"""

import sys
from datetime import date, datetime, timedelta

from common import (CC_BASE, DAYS_DIR, MOVIES_DIR, NETANYA_TIX_ID, VENUE_ALL,
                    VENUE_PRIME, http_get, parse_cc_name, read_md, watched_slugs,
                    write_md)
from fetch_movie import ensure_movie
from build_site import build
from fetch_ratings import ratings_line, update_ratings


def weekend_dates(today=None):
    today = today or date.today()
    wd = today.weekday()  # пн=0 ... пт=4, сб=5
    if wd == 4:
        return [today, today + timedelta(days=1)]
    if wd == 5:
        return [today]
    fri = today + timedelta(days=(4 - wd) % 7)
    return [fri, fri + timedelta(days=1)]


def fetch_events(d, venue):
    return http_get(f"{CC_BASE}/tickets/Events", {
        "TheatreId": NETANYA_TIX_ID, "VenueTypeId": venue, "MovieId": 0,
        "Date": d.strftime("%d/%m/%Y"),
    })


def collect_day(d, movie_ids):
    prime_ids = {x["EventId"] for m in fetch_events(d, VENUE_PRIME) for x in m["Dates"]}
    sessions = []
    for m in fetch_events(d, VENUE_ALL):
        parsed = parse_cc_name(m["Name"])
        mid = movie_ids.get(m["ExportCode"]) or movie_ids.get(m["Name"])
        slug = ensure_movie(mid, m["Name"]) if mid else None
        for x in m["Dates"]:
            dt = datetime.strptime(x["Date"], "%d/%m/%Y %H:%M")
            sessions.append({
                "time": x["Hour"],
                "after_midnight": dt.date() > d,
                "movie": slug,
                "cc_name": m["Name"],
                "prime": x["EventId"] in prime_ids,
                "screen_language": parsed["screen_language"],
                "format": parsed["format"],
                "event_id": x["EventId"],
                "ticket_url": f"{CC_BASE}/order/?eventID={x['EventId']}&theaterId={x['TheaterId']}",
                "_dt": dt,
            })
    sessions.sort(key=lambda s: (s["_dt"], s["cc_name"]))
    return sessions


def merge_previous(d, sessions):
    """Добавить сеансы из прежнего файла дня, которых больше нет на сайте.

    Сайт убирает сеанс, как только он начался. Такие сеансы просто остаются
    в файле. Если сеанс пропал до начала, это отмена: status = removed.
    """
    path = DAYS_DIR / f"{d.isoformat()}.md"
    if not path.exists():
        return sessions
    current = {s["event_id"] for s in sessions}
    now = datetime.now()
    for old in read_md(path)[0].get("sessions") or []:
        if old.get("event_id") in current:
            continue
        old = dict(old)
        day = d + timedelta(days=1) if old.get("after_midnight") else d
        old["_dt"] = datetime.combine(day, datetime.strptime(old["time"], "%H:%M").time())
        old.setdefault("after_midnight", False)
        old.setdefault("format", None)
        if old["_dt"] > now:
            old["status"] = "removed"
        sessions.append(old)
    sessions.sort(key=lambda s: (s["_dt"], s["cc_name"]))
    return sessions


def movie_meta(slug):
    if not slug:
        return {}
    return read_md(MOVIES_DIR / f"{slug}.md")[0]


def write_day(d, sessions):
    rows = []
    out = []
    watched = watched_slugs()
    for s in sessions:
        mm = movie_meta(s["movie"])
        spoken = mm.get("spoken_languages") or []
        lang = s["screen_language"] or (spoken[0] if spoken else mm.get("original_language")) or "?"
        if not s["screen_language"] and len(spoken) > 1:
            # остальные языки в зале идут с субтитрами на иврите
            lang += " (+" + ", ".join(spoken[1:]) + ")"
        s = {k: v for k, v in s.items() if not k.startswith("_")}
        s["screen_language"] = lang
        out.append({k: v for k, v in s.items() if v is not None and v is not False or k == "prime"})

        title = mm.get("title_en") or parse_cc_name(s["cc_name"])["base"]
        if s.get("format"):
            title += f" ({s['format']})"
        film = f"[{title}](../movies/{s['movie']}.md)" if s["movie"] else title
        extra = ", ".join(str(x) for x in [mm.get("year"), ", ".join(mm.get("country") or [])] if x)
        if extra:
            film += f" · {extra}"
        if s["movie"] in watched:
            film += " · ✓ watched"
        t = f"[{s['time']}]({s['ticket_url']})" if s.get("ticket_url") else s["time"]
        t += " (night)" if s["after_midnight"] else ""
        if s.get("status") == "removed":
            t += " (removed)"
        cells = [t, film, "Prime" if s["prime"] else "", lang, ratings_line(mm)]
        if s["movie"] in watched:
            # Посмотренное приглушаем; где стили не поддерживаются, остаётся «✓ watched»
            cells = [f'<span style="color:gray">{c}</span>' if c else c for c in cells]
        rows.append("| " + " | ".join(cells) + " |")

    meta = {
        "date": d.isoformat(),
        "weekday": d.strftime("%A"),
        "cinema": "Cinema City Netanya",
        "fetched_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "sessions_count": len(out),
        "sessions": out,
    }
    body = (f"# {d.strftime('%A')}, {d.day} {d.strftime('%B %Y')}\n\n"
            "| Time | Movie | Hall | Language | Ratings |\n|---|---|---|---|---|\n" + "\n".join(rows))
    write_md(DAYS_DIR / f"{d.isoformat()}.md", meta, body)


def main():
    args = sys.argv[1:]
    dates = [date.fromisoformat(a) for a in args] if args else weekend_dates()
    movies = http_get(f"{CC_BASE}/tickets/Movies")
    movie_ids = {m["ExportCode"]: m["MovieId"] for m in movies}
    movie_ids.update({m["Name"]: m["MovieId"] for m in movies})
    days = [(d, merge_previous(d, collect_day(d, movie_ids))) for d in dates]
    slugs = sorted({s["movie"] for _, ss in days for s in ss if s["movie"]})
    print(f"Рейтинги: {len(slugs)} фильмов...")
    for slug in slugs:
        update_ratings(slug)
    for d, sessions in days:
        write_day(d, sessions)
        prime = sum(s["prime"] for s in sessions)
        gone = sum(1 for s in sessions if s.get("status") == "removed")
        print(f"{d}: {len(sessions)} сеансов, из них Prime {prime}" + (f", отменено {gone}" if gone else ""))
    print("Сайт:", build())
    review = [p.stem for p in MOVIES_DIR.glob("*.md") if read_md(p)[0].get("needs_review")]
    if review:
        print("Проверить руками:", ", ".join(sorted(review)))


if __name__ == "__main__":
    main()
