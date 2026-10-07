"""Расписание Cinema City Netanya → data/days/<YYYY-MM-DD>.md

Использование:
  python3 scripts/fetch_schedule.py              ближайшие выходные (пт + сб)
  python3 scripts/fetch_schedule.py 2026-09-27   конкретные даты
"""

import sys
import traceback
from datetime import date, datetime, timedelta

import cinema_city
import os

from common import (AVAILABILITY_FILE, DAYS_DIR, MOVIES_DIR, STATUS_FILE, now_il,
                    parse_cc_name, read_md, today_il, watched_slugs, write_md)
from fetch_movie import ensure_movie
from fetch_credits import stay_label, update_credits
from fetch_ratings import ratings_line, update_ratings


def weekend_dates(today=None):
    today = today or today_il()
    wd = today.weekday()  # пн=0 ... пт=4, сб=5
    if wd == 4:
        return [today, today + timedelta(days=1)]
    if wd == 5:
        return [today]
    fri = today + timedelta(days=(4 - wd) % 7)
    return [fri, fri + timedelta(days=1)]


def collect_day(d, presentations):
    """Сеансы одного дня из сеансов кинотеатра (день = businessDate сайта: ночные идут к предыдущему)."""
    sessions = []
    for p in presentations:
        if p["business_date"] != d:
            continue
        parsed = parse_cc_name(p["cc_name"])
        slug = ensure_movie(p["feature_id"], p["cc_name"])
        sessions.append({
            "time": p["start"].strftime("%H:%M"),
            "after_midnight": p["start"].date() > d,
            "movie": slug,
            "cc_name": p["cc_name"],
            "prime": p["prime"],
            # язык дубляжа сайт отдаёт отдельным полем; приписка в названии (-אנגלית) как запасной источник
            "screen_language": p["screen_language"] or parsed["screen_language"],
            "format": parsed["format"],
            "hall": p["hall"],
            "soldout": p["soldout"] or None,
            "event_id": p["event_id"],
            "ticket_url": p["ticket_url"],
            "_dt": p["start"],
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
    now = now_il().replace(tzinfo=None)  # сеансы хранятся в местном времени без пояса
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
        if stay_label(mm):
            film += f" · {stay_label(mm)}"
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
        "fetched_at": now_il().isoformat(timespec="seconds"),
        "sessions_count": len(out),
        "sessions": out,
    }
    body = (f"# {d.strftime('%A')}, {d.day} {d.strftime('%B %Y')}\n\n"
            "| Time | Movie | Hall | Language | Ratings |\n|---|---|---|---|---|\n" + "\n".join(rows))
    write_md(DAYS_DIR / f"{d.isoformat()}.md", meta, body)


def published_dates(presentations):
    """Даты, на которые Cinema City Netanya уже выложил сеансы."""
    return sorted({p["business_date"] for p in presentations})


def regular_until(published):
    """Последний день сплошного расписания от первой даты.

    Дальше идут одиночные даты (предпродажа отдельных показов), они не считаются.
    """
    if not published:
        return None
    last = published[0]
    for d in published[1:]:
        if d - last > timedelta(days=1):
            break
        last = d
    return last


def write_availability(published):
    until = regular_until(published)
    extra = [d.isoformat() for d in published if until and d > until]
    meta = {
        "cinema": "Cinema City Netanya",
        "fetched_at": now_il().isoformat(timespec="seconds"),
        "published_until": until.isoformat() if until else None,
        "published_dates": [d.isoformat() for d in published],
    }
    body = "# Published schedule\n\n" + (
        f"Cinema City Netanya has published the regular schedule up to **{until.strftime('%A, %d %B %Y')}**."
        if until else "Cinema City Netanya has no published dates.")
    if extra:
        body += "\n\nSingle later dates (pre-sales): " + ", ".join(extra) + "."
    write_md(AVAILABILITY_FILE, meta, body)
    return until


def collect():
    args = sys.argv[1:]
    wanted = [date.fromisoformat(a) for a in args] if args else weekend_dates()
    presentations = cinema_city.presentations()
    published = published_dates(presentations)
    until = write_availability(published)
    dates = [d for d in wanted if d in published]
    for d in wanted:
        if d not in published:
            print(f"{d}: Cinema City ещё не выложил расписание (сплошное расписание до {until})")
    days = [(d, merge_previous(d, collect_day(d, presentations))) for d in dates]
    slugs = sorted({s["movie"] for _, ss in days for s in ss if s["movie"]})
    print(f"Рейтинги: {len(slugs)} фильмов...")
    for slug in slugs:
        update_ratings(slug)
        try:
            update_credits(slug)
        except Exception as e:  # сведения о сценах после титров не главное: сбор не роняем, но пишем в лог
            print(f"  Сцены после титров не проверены для {slug}: {e}")
    for d, sessions in days:
        write_day(d, sessions)
        prime = sum(s["prime"] for s in sessions)
        gone = sum(1 for s in sessions if s.get("status") == "removed")
        print(f"{d}: {len(sessions)} сеансов, из них Prime {prime}" + (f", отменено {gone}" if gone else ""))
    review = [p.stem for p in MOVIES_DIR.glob("*.md") if read_md(p)[0].get("needs_review")]
    if review:
        print("Проверить руками:", ", ".join(sorted(review)))


def run_url():
    """Ссылка на запуск робота GitHub Actions (если сбор идёт там)."""
    if os.environ.get("GITHUB_RUN_ID"):
        return (f"{os.environ.get('GITHUB_SERVER_URL', 'https://github.com')}/"
                f"{os.environ['GITHUB_REPOSITORY']}/actions/runs/{os.environ['GITHUB_RUN_ID']}")
    return None


def write_status(ok, error=None):
    """Записать итог попытки сбора в data/status.md: его показывает страница."""
    old = read_md(STATUS_FILE)[0] if STATUS_FILE.exists() else {}
    now = now_il().isoformat(timespec="seconds")
    meta = {
        "last_attempt_at": now,
        "ok": ok,
        "last_success_at": now if ok else old.get("last_success_at"),
        # когда начались ошибки подряд (сбрасывается при успехе)
        "failing_since": None if ok else (old.get("failing_since") if old.get("ok") is False else now),
        "error": error,
        "run_url": run_url(),
    }
    meta = {k: v for k, v in meta.items() if v is not None or k in ("ok",)}
    body = "# Collector status\n\n" + (
        f"Last update succeeded at {now}." if ok else
        f"Last update FAILED at {now}:\n\n```\n{error}\n```")
    write_md(STATUS_FILE, meta, body)


def main():
    try:
        collect()
    except Exception as e:
        # Короткая причина для страницы; полный traceback остаётся в логе запуска
        last = traceback.extract_tb(e.__traceback__)[-1]
        write_status(False, f"{type(e).__name__}: {e} (in {os.path.basename(last.filename)}:{last.lineno})")
        raise
    write_status(True)


if __name__ == "__main__":
    main()
