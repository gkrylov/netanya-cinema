"""Собрать public/ и открыть страницу на локальном сервере.

Использование: python3 scripts/serve.py [порт] [--no-open]   (по умолчанию 8000)
Страницу с диска (file://) браузер не пускает к файлам с данными, поэтому нужен сервер.
"""

import functools
import http.server
import sys
import webbrowser

from build_public import PUBLIC, build

args = [a for a in sys.argv[1:] if not a.startswith("--")]
port = int(args[0]) if args else 8000
build()
handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(PUBLIC))
with http.server.ThreadingHTTPServer(("127.0.0.1", port), handler) as httpd:
    url = f"http://localhost:{port}/"
    print(f"Страница: {url}  (Ctrl+C, чтобы остановить)")
    if "--no-open" not in sys.argv:
        webbrowser.open(url)
    httpd.serve_forever()
