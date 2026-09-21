"""Поддельный «GitHub» для тестов обновлений: локальный HTTP-сервер с заданными ответами."""

import threading
import time
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ASSET_NAMES = {
    "windows": "GMAGC-desktop-windows-{v}.zip",
    "macos": "GMAGC-desktop-macos-{v}.zip",
    "android": "GMAGC-android-{v}.apk",
}


def release_json(version, base, platforms=("windows", "macos", "android"), **flags):
    """Ответ GitHub API /releases/latest; файлы лежат по адресам base/<имя>, рядом .sha256."""
    assets = []
    for platform in platforms:
        name = ASSET_NAMES[platform].format(v=version)
        assets.append({"name": name, "browser_download_url": f"{base}/{name}", "size": 1000})
        assets.append({"name": name + ".sha256", "browser_download_url": f"{base}/{name}.sha256", "size": 100})
    return {
        "tag_name": f"v{version}",
        "name": f"GMAGC {version}",
        "html_url": f"{base}/releases/tag/v{version}",
        "body": f"Что нового в {version}",
        "draft": flags.get("draft", False),
        "prerelease": flags.get("prerelease", False),
        "assets": assets,
    }


@contextmanager
def stub_server(routes):
    """routes: путь -> {"body": bytes, "status": 200, "headers": {}, "declared_length": int, "delay": float}."""

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            route = routes.get(self.path)
            if route is None:
                self.send_response(404)
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            time.sleep(route.get("delay", 0))
            body = route.get("body", b"")
            self.send_response(route.get("status", 200))
            self.send_header("Content-Length", str(route.get("declared_length", len(body))))
            for name, value in route.get("headers", {}).items():
                self.send_header(name, value)
            self.end_headers()
            try:
                self.wfile.write(body)
            except OSError:
                pass

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.daemon_threads = True
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()
