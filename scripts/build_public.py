"""Папка публикации public/ = код страницы (web/) + данные в JSON (public/data/).

Использование: python3 scripts/build_public.py
Её отдаёт локальный сервер (serve.py) и публикует GitHub Pages. В git не хранится.
"""

import shutil

from common import ROOT
from export_json import export

WEB = ROOT / "web"
PUBLIC = ROOT / "public"


def build():
    if PUBLIC.exists():
        shutil.rmtree(PUBLIC)
    shutil.copytree(WEB, PUBLIC)
    export(PUBLIC / "data")
    return PUBLIC


if __name__ == "__main__":
    print(build())
