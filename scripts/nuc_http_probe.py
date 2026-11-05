"""Bounded real HTTP reads with separate member sessions. Passwords stay in local prompts."""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import getpass
import json
import math
from pathlib import Path
import sys
import time
from urllib.parse import urlsplit

import httpx


def percentile(values, fraction):
    return sorted(values)[max(0, math.ceil(len(values) * fraction) - 1)] if values else None


def validate_url(url):
    import ipaddress
    parsed = urlsplit(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path not in {"", "/"}:
        raise ValueError("Use an origin URL without credentials, query or path")
    if parsed.scheme == "http":
        try:
            local = ipaddress.ip_address(parsed.hostname).is_loopback
        except ValueError:
            local = parsed.hostname == "localhost"
        if not local:
            raise ValueError("Member passwords require HTTPS outside loopback")
    return url.rstrip("/")


def probe(client, login, password, label, duration, interval, article_limit):
    samples = []
    failures = []
    authenticated = False
    csrf = None
    started = time.monotonic()
    result = {"label": label, "authenticated": False, "samples": samples, "failures": failures}
    try:
        response = client.post("/api/auth/login", json={"login": login, "password": password})
        if response.status_code != 200:
            result["failure_reason"] = "login_http_" + str(response.status_code)
            return result
        csrf = response.json()["csrf"]
        authenticated = True
        result["authenticated"] = True
        listing = client.get("/api/articles?limit=20")
        if listing.status_code != 200:
            result["failure_reason"] = "project_list_http_" + str(listing.status_code)
            return result
        ids = [a["id"] for a in listing.json()["articles"][:article_limit]]
        result["visible_project_count_sampled"] = len(ids)
        routes = [("/api/articles?limit=20", "/api/articles")]
        routes.extend((f"/api/articles/{aid}", "/api/articles/:id") for aid in ids)
        deadline = time.monotonic() + duration
        index = 0
        while time.monotonic() < deadline:
            path, route = routes[index % len(routes)]
            before = time.perf_counter()
            try:
                response = client.get(path)
                elapsed = (time.perf_counter() - before) * 1000
                samples.append({"route": route, "status": response.status_code, "milliseconds": round(elapsed, 3)})
                if response.status_code != 200:
                    failures.append({"route": route, "status": response.status_code})
            except httpx.HTTPError as exc:
                failures.append({"route": route, "error_type": type(exc).__name__})
            index += 1
            if interval:
                time.sleep(interval)
    except (httpx.HTTPError, KeyError, ValueError) as exc:
        result["failure_reason"] = type(exc).__name__
    finally:
        if authenticated:
            try:
                result["logout_status"] = client.post("/api/auth/logout", headers={"X-Wenshu-CSRF": csrf}).status_code
            except httpx.HTTPError as exc:
                result["logout_error_type"] = type(exc).__name__
        result["elapsed_seconds"] = round(time.monotonic() - started, 3)
    return result


def summarize(results):
    values = [s["milliseconds"] for r in results for s in r["samples"] if s["status"] == 200]
    failures = sum(len(r["failures"]) + bool(r.get("failure_reason")) +
                   bool(r.get("logout_error_type") or (r["authenticated"] and r.get("logout_status") != 200))
                   for r in results)
    return {"successful_reads": len(values), "failed_reads_or_setup": failures,
            "all_members_authenticated": all(r["authenticated"] for r in results),
            "median_ms": percentile(values, .5), "p95_ms": percentile(values, .95),
            "max_ms": max(values) if values else None}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--logins", nargs="+", required=True)
    parser.add_argument("--duration-seconds", type=int, default=60)
    parser.add_argument("--interval-seconds", type=float, default=.5)
    parser.add_argument("--article-limit", type=int, default=5)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    try:
        url = validate_url(args.base_url)
        if not 1 <= len(args.logins) <= 3 or len(set(args.logins)) != len(args.logins) or not 1 <= args.duration_seconds <= 3600 or not .1 <= args.interval_seconds <= 10 or not 1 <= args.article_limit <= 20:
            raise ValueError("Use 1–3 members, duration 1–3600s, interval .1–10s and 1–20 projects")
        output = Path(args.output).resolve()
        if output.exists() or not output.parent.is_dir():
            raise ValueError("Output must be new and its parent must already exist")
        if not sys.stdin.isatty():
            raise ValueError("Run in an interactive local terminal for password prompts; no passwords in arguments, files or Git")
        passwords = [getpass.getpass(f"Local password for {login}: ") for login in args.logins]
        def worker(index):
            with httpx.Client(base_url=url, timeout=10, trust_env=False, follow_redirects=False) as client:
                return probe(client, args.logins[index], passwords[index], f"member-{index+1}", args.duration_seconds, args.interval_seconds, args.article_limit)
        with ThreadPoolExecutor(max_workers=len(args.logins)) as pool:
            results = list(pool.map(worker, range(len(args.logins))))
        report = {"recorded_at_utc": datetime.now(timezone.utc).isoformat(), "base_url": url,
            "scope": "Real HTTP authorized reads; login/logout modify only these test sessions. No content writes, model calls or render workload.",
            "duration_seconds_requested": args.duration_seconds, "interval_seconds": args.interval_seconds,
            "members": results, "summary": summarize(results), "pass_verdict": "requires_casebook_review"}
        output.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(json.dumps(report["summary"], indent=2))
        return 0 if report["summary"]["failed_reads_or_setup"] == 0 and report["summary"]["successful_reads"] > 0 else 1
    except (ValueError, OSError) as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
