"""Папка публикации public/ = код страницы (web/) + данные в JSON (public/data/).

Использование: python3 scripts/build_public.py
Её отдаёт локальный сервер (serve.py) и публикует GitHub Pages. В git не хранится.
"""

import hashlib
import shutil

from common import ROOT
from export_json import export

WEB = ROOT / "web"
PUBLIC = ROOT / "public"


def build():
    if PUBLIC.exists():
        shutil.rmtree(PUBLIC)
    shutil.copytree(WEB, PUBLIC)
    # Метка версии в адресах стилей и скрипта: изменился файл, браузер не возьмёт старый из кэша
    index = PUBLIC / "index.html"
    page = index.read_text()
    for name in ("style.css", "app.js"):
        v = hashlib.sha256((WEB / name).read_bytes()).hexdigest()[:10]
        page = page.replace(f'"{name}"', f'"{name}?v={v}"')
    index.write_text(page)
    export(PUBLIC / "data")
    return PUBLIC


if __name__ == "__main__":
    print(build())
