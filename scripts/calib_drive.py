"""流水线校准驱动：提交真实选题并跟踪/推进流水线（供真实案例校准轮复用）。

用法（服务运行中）：
  python scripts/calib_drive.py submit            # 提交 SEEDS 里的选题并自动收集
  python scripts/calib_drive.py status            # 看所有文章状态/进度
  python scripts/calib_drive.py jobs <aid>        # 看某文章的任务队列
  python scripts/calib_drive.py advance <aid> <collect|create|review>
"""
import json
import sys
import time
import urllib.request

BASE = "http://127.0.0.1:8000"

SEEDS = [
    ("https://www.qbitai.com/2026/10/505529.html", "校准样本1：OpenAI 断网训练，模型/安全要闻"),
    ("https://www.qbitai.com/2026/10/505454.html", "校准样本2：中国云生意格局，产业商业新闻"),
    ("https://www.qbitai.com/2026/10/505521.html", "校准样本3：A社联创演讲 AI 奇点，观点演讲类"),
]


def req(method: str, path: str, body: dict | None = None, timeout: int = 60):
    data = json.dumps(body).encode("utf-8") if body is not None else None
    r = urllib.request.Request(
        BASE + path, data=data, method=method,
        headers={"Content-Type": "application/json; charset=utf-8"},
    )
    with urllib.request.urlopen(r, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def main() -> None:
    cmd = sys.argv[1] if len(sys.argv) > 1 else "submit"
    if cmd == "submit":
        for url, notes in SEEDS:
            out = req("POST", "/api/articles", {"url": url, "user_notes": notes})
            print(json.dumps(out, ensure_ascii=False)[:300])
    elif cmd == "status":
        out = req("GET", "/api/articles?limit=10")
        arts = out if isinstance(out, list) else out.get("items", out.get("articles", []))
        for a in arts:
            print(a.get("id"), "|", a.get("status"), "|", a.get("ui_status"), "|",
                  (a.get("title") or "")[:40], "|", a.get("progress"))
    elif cmd == "jobs":
        aid = sys.argv[2]
        out = req("GET", f"/api/articles/{aid}/jobs" if False else f"/api/jobs?article_id={aid}&limit=20")
        jobs = out if isinstance(out, list) else out.get("items", out.get("jobs", []))
        for j in jobs:
            print(j.get("id"), j.get("type"), j.get("status"), "attempts=", j.get("attempts"),
                  "err=", (j.get("error") or "")[:80])
    elif cmd == "advance":
        aid, stage = sys.argv[2], sys.argv[3]
        out = req("POST", f"/api/articles/{aid}/advance", {"stage": stage})
        print(json.dumps(out, ensure_ascii=False)[:300])


if __name__ == "__main__":
    main()
