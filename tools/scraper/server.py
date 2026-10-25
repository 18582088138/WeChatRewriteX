"""media-scraper 独立 GUI 服务（零依赖，标准库 http.server）。

python tools/scraper/server.py [--port 8765]  →  http://127.0.0.1:8765
路由：GET / 界面 · POST /scrape {url} · GET /out/<文件> · POST /reveal {path}
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).parent))

from scraper import DEFAULT_OUT, scrape  # noqa: E402

WEB = Path(__file__).parent / "web"


class Handler(BaseHTTPRequestHandler):
    def _send(self, code: int, body: bytes, ctype: str = "application/json; charset=utf-8"):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj, code: int = 200):
        self._send(code, json.dumps(obj, ensure_ascii=False).encode("utf-8"))

    def log_message(self, fmt, *args):  # 静音请求日志
        pass

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            f = WEB / "index.html"
            self._send(200, f.read_bytes(), "text/html; charset=utf-8")
            return
        if self.path.startswith("/out/"):
            rel = unquote(self.path[len("/out/"):])
            p = (DEFAULT_OUT / rel).resolve()
            if not str(p).startswith(str(DEFAULT_OUT.resolve())) or not p.is_file():
                self._json({"error": "not found"}, 404)
                return
            ctype = ("image/jpeg" if p.suffix.lower() in (".jpg", ".jpeg") else
                     "image/png" if p.suffix.lower() == ".png" else
                     "image/gif" if p.suffix.lower() == ".gif" else
                     "image/webp" if p.suffix.lower() == ".webp" else
                     "video/mp4" if p.suffix.lower() == ".mp4" else
                     "text/markdown; charset=utf-8" if p.suffix.lower() == ".md" else
                     "application/octet-stream")
            self._send(200, p.read_bytes(), ctype)
            return
        self._json({"error": "not found"}, 404)

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length) if length else b"{}"
        try:
            payload = json.loads(body.decode("utf-8"))
        except json.JSONDecodeError:
            payload = {}
        if self.path == "/scrape":
            url = (payload.get("url") or "").strip()
            if not url.startswith("http"):
                self._json({"error": "请输入有效链接"}, 400)
                return
            logs: list[str] = []
            try:
                summary = scrape(url, log=lambda m: logs.append(m))
                summary["logs"] = logs
                # 给文件补可访问 URL
                summary["file_urls"] = [f"/out/{Path(summary['out_dir']).name}/{f}"
                                        for f in summary["files"]]
                self._json(summary)
            except Exception as e:
                self._json({"error": str(e), "logs": logs}, 502)
            return
        if self.path == "/reveal":
            p = Path(payload.get("path") or "")
            try:
                if sys.platform == "win32":
                    subprocess.Popen(["explorer", str(p)])
                elif sys.platform == "darwin":
                    subprocess.Popen(["open", str(p)])
                else:
                    subprocess.Popen(["xdg-open", str(p)])
                self._json({"ok": True})
            except OSError as e:
                self._json({"error": str(e)}, 500)
            return
        self._json({"error": "not found"}, 404)


def main() -> None:
    parser = argparse.ArgumentParser(description="media-scraper GUI 服务")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    DEFAULT_OUT.mkdir(parents=True, exist_ok=True)
    print(f"media-scraper GUI → http://127.0.0.1:{args.port}  (Ctrl+C 停止)")
    ThreadingHTTPServer(("127.0.0.1", args.port), Handler).serve_forever()


if __name__ == "__main__":
    main()
