"""Общие вещи: пути, HTTP, чтение/запись Markdown с YAML-шапкой, разбор названий."""

import json
import re
import time
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
MOVIES_DIR = DATA / "movies"
DAYS_DIR = DATA / "days"
WATCHED_FILE = DATA / "watched.md"

CC_BASE = "https://www.cinema-city.co.il"
NETANYA_ID = 5            # ID кинотеатра на сайте (обычные залы)
NETANYA_TIX_ID = 1176     # TixTheatreId, общий для обычных и Prime
VENUE_ALL = 1             # «רגיל»: на деле отдаёт все сеансы, включая Prime
VENUE_PRIME = 4

UA = "Mozilla/5.0 (personal cinema schedule tracker)"


def load_env():
    env = {}
    path = ROOT / ".env"
    if path.exists():
        for line in path.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip()
    return env


def http_get(url, params=None, headers=None, as_json=True, retries=3):
    if params:
        url += "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": UA, **(headers or {})})
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                body = r.read().decode("utf-8")
            return json.loads(body) if as_json else body
        except Exception:
            if attempt == retries - 1:
                raise
            time.sleep(1 + attempt * 2)


# --- Markdown с YAML-шапкой ------------------------------------------------
# Пишем подмножество YAML: скаляры, списки скаляров в одну строку
# и списки словарей построчно (каждый словарь в JSON-виде, это тоже YAML).

_PLAIN = re.compile(r"^[\w֐-׿Ѐ-ӿ][\w֐-׿Ѐ-ӿ .,'()!?&+-]*$")


def _scalar(v):
    if v is None:
        return ""
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return str(v)
    s = str(v)
    if _PLAIN.match(s) and s not in ("true", "false", "null") and not re.fullmatch(r"[\d.]+", s):
        return s
    return json.dumps(s, ensure_ascii=False)


def dump_frontmatter(meta):
    lines = ["---"]
    for k, v in meta.items():
        if isinstance(v, list) and v and isinstance(v[0], dict):
            lines.append(f"{k}:")
            for item in v:
                lines.append("  - " + json.dumps(item, ensure_ascii=False))
        elif isinstance(v, list):
            lines.append(f"{k}: [" + ", ".join(_scalar(x) for x in v) + "]")
        else:
            lines.append(f"{k}: {_scalar(v)}".rstrip())
    lines.append("---")
    return "\n".join(lines) + "\n"


def _parse_scalar(s):
    s = s.strip()
    if s == "":
        return None
    if s in ("true", "false"):
        return s == "true"
    if s.startswith("[") and s.endswith("]"):
        inner = s[1:-1].strip()
        if not inner:
            return []
        try:
            return json.loads(s)
        except ValueError:
            return [_parse_scalar(x) for x in inner.split(",")]
    try:
        return json.loads(s)
    except ValueError:
        return s


def read_md(path):
    """Вернуть (meta, body). meta пустой, если шапки нет."""
    text = Path(path).read_text()
    if not text.startswith("---\n"):
        return {}, text
    head, body = text[4:].split("\n---\n", 1)
    meta, key = {}, None
    for line in head.splitlines():
        if line.startswith("  - ") and key:
            if meta.get(key) is None:
                meta[key] = []
            meta[key].append(_parse_scalar(line[4:]))
            continue
        k, _, v = line.partition(":")
        key = k.strip()
        v = v.split(" #")[0] if not v.strip().startswith('"') else v
        meta[key] = _parse_scalar(v) if v.strip() else None
    return meta, body.lstrip("\n")


def write_md(path, meta, body):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(dump_frontmatter(meta) + "\n" + body.rstrip() + "\n")


# --- Разбор названий Cinema City -------------------------------------------

# Суффикс в названии → язык показа (None = язык оригинала фильма)
LANG_SUFFIXES = [
    ("-מדובב לרוסית", "dubbed (Russian)"),
    ("-מדובב", "dubbed"),  # дубляж на иврит
    ("-אנגלית", "English"),
    ("-עברית", "Hebrew"),
]
FORMAT_SUFFIXES = ["-Infinity Vision"]


def parse_cc_name(name):
    """«G Kids - האי הנעלם-מדובב» → base, screen_language, format, kids."""
    n = name.strip()
    kids = False
    m = re.match(r"^G\s*kids\s*[-–]\s*", n, re.I)
    if m:
        kids, n = True, n[m.end():]
    fmt = None
    for s in FORMAT_SUFFIXES:
        if n.endswith(s):
            fmt, n = s[1:], n[: -len(s)]
    lang = None
    for s, l in LANG_SUFFIXES:
        if n.endswith(s):
            lang, n = l, n[: -len(s)]
            break
    return {"base": n.strip(), "screen_language": lang, "format": fmt, "kids": kids}


def slugify(text):
    s = text.lower().replace("&", " and ")
    s = re.sub(r"[^a-z0-9]+", "-", s)
    return s.strip("-")


def watched_slugs():
    """Фильмы из data/watched.md (строки вида «movie: <slug>»)."""
    if not WATCHED_FILE.exists():
        return set()
    return set(re.findall(r"^movie:\s*(\S+)", WATCHED_FILE.read_text(), re.M))
