"""Пора ли собирать расписание: сроки сбора по израильскому времени.

Использование: python3 scripts/due.py   → печатает collect=true|false
(в GitHub Actions то же пишется в $GITHUB_OUTPUT).

GitHub запускает workflow по расписанию с задержкой и не гарантирует время,
поэтому он просыпается часто, а этот скрипт решает, наступил ли срок:
сбор нужен, если последний сбор был раньше последнего срока.
Сроки задаются в местном времени, так что переход на зимнее время их не сдвигает.
"""

import os
from datetime import datetime, time, timedelta

from common import AVAILABILITY_FILE, TZ, now_il, read_md

DAILY = time(7, 0)                 # каждый день в 7:00
WEEKLY = (3, time(20, 0))          # четверг (пн=0) в 20:00: расписание на выходные


def last_slot(now):
    """Последний срок сбора, не позже now."""
    today = now.date()
    daily = datetime.combine(today, DAILY, TZ)
    if daily > now:
        daily -= timedelta(days=1)
    weekday, at = WEEKLY
    weekly = datetime.combine(today - timedelta(days=(today.weekday() - weekday) % 7), at, TZ)
    if weekly > now:
        weekly -= timedelta(days=7)
    return max(daily, weekly)


def last_collected():
    if not AVAILABILITY_FILE.exists():
        return None
    ts = read_md(AVAILABILITY_FILE)[0].get("fetched_at")
    return datetime.fromisoformat(ts) if ts else None


def is_due(now=None):
    now = now or now_il()
    slot, last = last_slot(now), last_collected()
    return (last is None or last < slot), slot, last


if __name__ == "__main__":
    due, slot, last = is_due()
    print(f"last slot {slot:%a %d %b %H:%M}, last collected {last:%a %d %b %H:%M}" if last
          else f"last slot {slot:%a %d %b %H:%M}, never collected")
    print(f"collect={'true' if due else 'false'}")
    if os.environ.get("GITHUB_OUTPUT"):
        with open(os.environ["GITHUB_OUTPUT"], "a") as f:
            f.write(f"collect={'true' if due else 'false'}\n")
