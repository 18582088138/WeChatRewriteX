"""Measure process launch -> /ready and SPA (isolated data, no model calls)."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--exe", type=Path)
    parser.add_argument("--samples", type=int, default=3)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    results = []
    for _ in range(args.samples):
        with tempfile.TemporaryDirectory(prefix="wenshu-profile-") as tmp:
            root = Path(tmp)
            env = dict(os.environ, WENSHU_DATA_DIR=str(root / "data"),
                       WENSHU_LOG_DIR=str(root / "logs"), APP_ACCESS_TOKEN="")
            for key in ("DEEPSEEK_API_KEY", "ARK_API_KEY", "OPENAI_API_KEY", "TAVILY_API_KEY",
                        "PEXELS_API_KEY", "PIXABAY_API_KEY"):
                env[key] = ""
            with socket.socket() as sock:
                sock.bind(("127.0.0.1", 0))
                port = sock.getsockname()[1]
            command = [str(args.exe.resolve())] if args.exe else [sys.executable, "-X", "utf8", "-m", "app"]
            command += ["--no-browser", "--port", str(port)]
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
            with (root / "startup.log").open("wb") as log:
                started = time.perf_counter()
                process = subprocess.Popen(command, env=env, stdout=log, stderr=log)
                try:
                    while True:
                        try:
                            with opener.open(f"http://127.0.0.1:{port}/api/ready", timeout=.2) as response:
                                if response.status == 200:
                                    break
                        except OSError:
                            pass
                        if process.poll() is not None or time.perf_counter() - started > 90:
                            raise RuntimeError((root / "startup.log").read_text(encoding="utf-8", errors="replace"))
                        time.sleep(.02)
                    ready = time.perf_counter() - started
                    with opener.open(f"http://127.0.0.1:{port}/", timeout=5) as response:
                        assert b"<html" in response.read().lower()
                    results.append({"ready_seconds": round(ready, 3), "spa_seconds": round(time.perf_counter() - started, 3)})
                finally:
                    if os.name == "nt":
                        # venv redirector / onefile bootloader may own a server child.
                        subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"], capture_output=True)
                    else:
                        process.terminate()
                    process.wait(timeout=10)
                    # Windows closes child handles asynchronously after taskkill.
                    if os.name == "nt":
                        time.sleep(.5)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(json.dumps(results))


if __name__ == "__main__":
    main()
