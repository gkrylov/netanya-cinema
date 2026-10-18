"""Футбольные матчи на стадионе Нетании (рядом с кинотеатром) → data/stadium.md

Использование: python3 scripts/fetch_stadium.py   (вызывается и из общего сбора)

Источник: открытый API TheSportsDB (бесплатный ключ, на деле не больше ~12 запросов в минуту).
Матчи берутся по турам: у каждого указан стадион. Файл помнит, с какого тура
смотреть, так что за сбор уходит несколько запросов на лигу.
"""

import json
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

from common import STADIUM_FILE, TZ, UA, now_il, read_md, write_md

API = "https://www.thesportsdb.com/api/v1/json/123"
VENUE = "Netanya Stadium"
LEAGUES = {"4644": "Israeli Premier League", "4966": "Liga Leumit"}
HORIZON_DAYS = 42      # насколько вперёд смотреть
KEEP_PAST_DAYS = 30    # прошедшие матчи храним недолго
PAUSE = 5.5            # между запросами: при ~27 в минуту бесплатный ключ получает «429», 12 в минуту проходят
MAX_ROUNDS = 12        # за один сбор на лигу


def _get(path, params):
    url = f"{API}/{path}?" + "&".join(f"{k}={v}" for k, v in params.items())
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    for attempt in range(3):
        time.sleep(PAUSE)
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.loads(r.read().decode("utf-8") or "{}")
        except urllib.error.HTTPError as e:
            if e.code != 429 or attempt == 2:
                raise
            # частые повторы продлевают блокировку: ждать столько, сколько просит сервер, и с запасом
            time.sleep(max(int(e.headers.get("Retry-After") or 20), 20) * 2 + 10)


def season_of(d):
    """Израильский сезон идёт с августа по май: «2026-2027»."""
    y = d.year if d.month >= 7 else d.year - 1
    return f"{y}-{y + 1}"


def _match(e, league, tentative):
    ts = e.get("strTimestamp") or f"{e['dateEvent']}T{e.get('strTime') or '00:00:00'}"
    start = datetime.fromisoformat(ts[:19]).replace(tzinfo=timezone.utc).astimezone(TZ)
    return {
        "id": e["idEvent"],
        "date": start.date().isoformat(),
        "time": start.strftime("%H:%M"),
        "start": start.isoformat(),
        "home": e.get("strHomeTeam"),
        "away": e.get("strAwayTeam"),
        "league": LEAGUES[league],
        "league_id": league,
        "round": int(e["intRound"]) if e.get("intRound") else None,
        # тур ещё не расписан: у всех матчей одно и то же условное время
        "tentative": tentative or None,
        "postponed": (e.get("strPostponed") == "yes") or None,
    }


def scan_league(league, season, first_round, today):
    """Туры от first_round до горизонта → (матчи на стадионе, просмотренные туры, новый first_round)."""
    found, seen = [], set()
    r = first_round
    for _ in range(MAX_ROUNDS):
        events = _get("eventsround.php", {"id": league, "r": r, "s": season}).get("events") or []
        if not events:
            break
        dates = sorted(e["dateEvent"] for e in events if e.get("dateEvent"))
        seen.add(r)
        if dates and dates[0] > (today + timedelta(days=HORIZON_DAYS)).isoformat():
            break
        tentative = len(events) > 2 and len({e.get("strTimestamp") for e in events}) == 1
        found += [_match(e, league, tentative) for e in events if e.get("strVenue") == VENUE]
        if dates and dates[-1] < today.isoformat() and r == first_round:
            first_round = r + 1   # тур целиком прошёл: в следующий раз начинать со следующего
        r += 1
    return found, seen, first_round


def update_stadium():
    today = now_il().date()
    season = season_of(today)
    old = read_md(STADIUM_FILE)[0] if STADIUM_FILE.exists() else {}
    rounds = (old.get("next_round") or {}) if old.get("season") == season else {}
    if isinstance(rounds, str):  # шапка хранит словарь одной JSON-строкой
        rounds = json.loads(rounds)
    fresh, seen = [], set()
    for league in LEAGUES:
        found, rs, rounds[league] = scan_league(league, season, int(rounds.get(league) or 1), today)
        fresh += found
        seen |= {(league, r) for r in rs}
    # Прежние матчи из непросмотренных туров (прошедшие) оставляем ненадолго
    keep_from = (today - timedelta(days=KEEP_PAST_DAYS)).isoformat()
    kept = [m for m in old.get("matches") or []
            if (m.get("league_id"), m.get("round")) not in seen and m["date"] >= keep_from]
    matches = sorted(kept + fresh, key=lambda m: m["start"])
    write_stadium(season, rounds, matches)
    return matches


def write_stadium(season, rounds, matches):
    meta = {
        "venue": VENUE,
        "source": "TheSportsDB",
        "fetched_at": now_il().isoformat(timespec="seconds"),
        "season": season,
        "next_round": json.dumps(rounds),
        "matches": [{k: v for k, v in m.items() if v is not None} for m in matches],
    }
    rows = [f"| {m['date']} | {m['time']}{' (TBC)' if m.get('tentative') else ''}"
            f"{' (postponed)' if m.get('postponed') else ''} | {m['home']} vs {m['away']} | {m['league']} |"
            for m in matches]
    body = ("# Matches at Netanya Stadium\n\nNext to the cinema: parking is hard on match days.\n"
            "Times are Israel time; TBC means the league has not fixed the date and time yet.\n\n"
            "| Date | Time | Match | League |\n|---|---|---|---|\n" + "\n".join(rows))
    write_md(STADIUM_FILE, meta, body)


if __name__ == "__main__":
    for m in update_stadium():
        print(m["date"], m["time"], "TBC" if m.get("tentative") else "", f"{m['home']} vs {m['away']}", "·", m["league"])
