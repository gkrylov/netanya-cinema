"""Источник данных Cinema City (новый сайт на Wix, с 06.10.2026).

Сайт сам загружает данные из коллекций Wix Data; читаем их так же, как браузер
анонимного посетителя: берём публичный токен посетителя и делаем запрос
к /_api/cloud-data/v2/items/query.

- SyncPresentations: сеансы всей сети (время, фильм, зал, тип зала, язык).
- SyncFeatures: фильмы (название на иврите и английском, премьера, описание).
"""

import json
import urllib.request
from datetime import date, datetime

from common import UA, http_get

BASE = "https://www.cinema-city.co.il"
WIX_CODE_APP = "675bbcef-18d8-41f5-800e-131ec9e08762"   # приложение Wix Code (Velo) сайта
NETANYA = "סינמה סיטי נתניה"
TICKET_URL = "https://tickets.cinema-city.co.il/order/{event_id}"

_token = None


def _auth():
    global _token
    if _token is None:
        apps = http_get(f"{BASE}/_api/v1/access-tokens")["apps"]
        _token = apps[WIX_CODE_APP]["instance"]
    return _token


def _query(collection, filter_=None):
    """Все записи коллекции, подходящие под фильтр (с постраничной выдачей)."""
    items, cursor = [], None
    while True:
        query = {"cursorPaging": {"limit": 1000, **({"cursor": cursor} if cursor else {})}}
        if filter_ and not cursor:
            query["filter"] = filter_
        body = json.dumps({"dataCollectionId": collection, "query": query}).encode()
        req = urllib.request.Request(f"{BASE}/_api/cloud-data/v2/items/query", body, {
            "User-Agent": UA, "Authorization": _auth(), "Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=60) as r:
            page = json.loads(r.read())
        items += [x["data"] for x in page.get("dataItems", [])]
        cursor = (page.get("pagingMetadata") or {}).get("cursors", {}).get("next")
        if not cursor:
            return items


def _payload(item):
    p = item.get("payloadJson")
    return json.loads(p) if isinstance(p, str) else (p or {})


# Язык показа: дубляж определяется полем dubbedLanguageISO
DUB = {"he": "dubbed", "ru": "dubbed (Russian)", "fr": "dubbed (French)"}


def screen_language(p):
    """dubbed / dubbed (Russian) / English / Hebrew, или None = язык оригинала фильма."""
    dub = p.get("dubbedLanguageISO")
    if dub:
        return DUB.get(dub, f"dubbed ({dub})")
    return None


def presentations(location=NETANYA):
    """Сеансы кинотеатра: список словарей в формате файла дня."""
    out = []
    for item in _query("SyncPresentations", {"locationName": location}):
        p = _payload(item)
        start = datetime.strptime(item["dateTime"], "%Y-%m-%d %H:%M")
        business = date.fromisoformat(str(p.get("businessDate") or item["dateTime"][:10]))
        out.append({
            "business_date": business,
            "start": start,
            "feature_id": int(item["featureId"]),
            "cc_name": item["featureName"],
            "title_en": item.get("featureAdditionalName"),
            "prime": item.get("venueTypeName") == "Prime",
            "venue_type": item.get("venueTypeName"),
            "hall": p.get("venueTinyName") or item.get("venueName"),
            "screen_language": screen_language(p),
            "language_iso": p.get("languageISO"),
            "runtime_min": p.get("durationInMinutes"),
            "soldout": bool(item.get("soldout")),
            "event_id": str(item["externalId"]),
            "ticket_url": TICKET_URL.format(event_id=item["externalId"]),
        })
    return out


def feature(feature_id):
    """Фильм по номеру (тот же номер в адресе /movie/<номер>), или None."""
    items = _query("SyncFeatures", {"externalId": str(feature_id)})
    if not items:
        return None
    item = items[0]
    p = _payload(item)
    return {
        "title_he": item.get("name") or p.get("name"),
        "title_en": p.get("additionalName") or None,
        "genre_he": p.get("categoryName"),
        "runtime_min": int(p["duration"]) if p.get("duration") else None,
        "premiere_il": p.get("dateStarted"),
        "age_he": item.get("ratingName") or p.get("ratingName"),
        "synopsis_he": p.get("synopsis"),
        "original_language_iso": p.get("originalLanguageISO"),
    }
