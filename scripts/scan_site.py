#!/usr/bin/env python3
"""Safe site check — GET/HEAD only, no password guessing, no login brute force.
Only run this on a site you own, or have permission to test.

Usage:
    python3 scripts/scan_site.py example.com
    python3 scripts/scan_site.py shgora.com

What it does (same logic as the shgora.com scan, ~/workspace/shgora-scan/out/REPORT.md):
  1. subfinder, if installed, else skip
  2. curl -I / HEAD live check for https://domain and https://www.domain
  3. Download homepage, find JS files, download them, grep /api/* and hosts
  4. List video/mp4 links if present, HEAD-test each file
  5. Check /.env, /.git/HEAD, /robots.txt, /admin (status only)
  6. Check security headers
Prints a human summary + JSON report. Saves report to scan-output/<domain>.json
"""
import json
import os
import re
import shutil
import subprocess
import sys
import urllib.request
import urllib.error

UA = {"User-Agent": "KG-Terminal-Agent scan (GET-only, owner check)"}
TIMEOUT = 15


def head(url):
    """HEAD via urllib, return (status, headers dict, final_url) or (None, {}, url)."""
    req = urllib.request.Request(url, headers=UA, method="HEAD")
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            return r.status, dict(r.headers), r.geturl()
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers or {}), url
    except Exception:
        return None, {}, url


def get(url):
    req = urllib.request.Request(url, headers=UA, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            body = r.read().decode("utf-8", "ignore")
            return r.status, dict(r.headers), body, r.geturl()
    except urllib.error.HTTPError as e:
        try:
            body = e.read().decode("utf-8", "ignore")
        except Exception:
            body = ""
        return e.code, dict(e.headers or {}), body, url
    except Exception as e:
        return None, {}, f"error: {e}", url


def curl_head(url):
    """Prefer curl -I when available (matches the original scan); else urllib."""
    if shutil.which("curl"):
        try:
            p = subprocess.run(
                ["curl", "-sI", "--max-time", "15", url],
                capture_output=True, text=True, timeout=20,
            )
            m = re.search(r"HTTP/\S+\s+(\d+)", p.stdout or "")
            ctype = ""
            cm = re.search(r"(?im)^content-type:\s*(.+)$", p.stdout or "")
            if cm:
                ctype = cm.group(1).strip()
            return (int(m.group(1)) if m else None), {"Content-Type": ctype}
        except Exception:
            pass
    status, headers, _ = head(url)
    return status, headers


def main():
    if len(sys.argv) < 2:
        print("Usage: python3 scripts/scan_site.py example.com")
        print("Only run on a site you own or have permission to test.")
        return 2
    domain = sys.argv[1].strip().lower()
    domain = re.sub(r"^https?://", "", domain).split("/")[0].split(":")[0]
    if not re.fullmatch(r"[a-z0-9.-]+\.[a-z]{2,}", domain):
        print(f"Bad domain: {domain!r}")
        return 2

    report = {"domain": domain, "subdomains": [], "live": {}, "js_files": [],
              "api_routes": [], "hosts": [], "video_files": [], "exposure": {},
              "headers": {}}
    print(f"== Scan {domain} (GET/HEAD only) ==")

    # 1. Subdomains
    if shutil.which("subfinder"):
        try:
            p = subprocess.run(
                ["subfinder", "-d", domain, "-all", "-silent"],
                capture_output=True, text=True, timeout=60,
            )
            report["subdomains"] = sorted(set(p.stdout.split()))
        except Exception as e:
            print(f"subfinder failed: {e}")
    else:
        print("subfinder not installed, skipping subdomain step")
    print(f"Subdomains: {len(report['subdomains'])} {report['subdomains']}")

    # 2. Live check
    for host in (domain, "www." + domain):
        url = f"https://{host}"
        status, headers, final = head(url)
        report["live"][host] = {"status": status, "final_url": final}
        print(f"Live {url} -> {status} (final: {final})")

    # 3. Homepage + JS
    base = None
    homepage = ""
    for host in ("www." + domain, domain):
        status, headers, body, final = get(f"https://{host}")
        if status == 200 and body:
            base, homepage = host, body
            break
    if not homepage:
        print("Could not download homepage. Stopping here.")
        print(json.dumps(report, indent=2))
        return 0

    js_files = sorted(set(re.findall(r'["\']([^"\']*\.js[^"\']*)["\']', homepage)))
    # Keep relative _app/immutable style paths and absolute /...js paths
    js_files = [j for j in js_files if not j.startswith("http") or domain in j][:20]
    report["js_files"] = js_files
    print(f"JS files in homepage: {len(js_files)}")

    api_routes, hosts, js_bodies = set(), set(), []
    for js in js_files:
        if js.startswith("http"):
            url = js
        elif js.startswith("/"):
            url = f"https://{base}{js}"
        else:
            url = f"https://{base}/{js}"
        status, _, body, _ = get(url)
        if status == 200 and body:
            js_bodies.append(body)
    joined = "\n".join(js_bodies) + "\n" + homepage
    api_routes = sorted(set(re.findall(r'"/api/[^"\s]*', joined)))
    api_routes = [a.strip('"') for a in api_routes]
    hosts = sorted(set(re.findall(r"https://[a-zA-Z0-9.-]+", joined)))
    report["api_routes"] = api_routes
    report["hosts"] = hosts
    print(f"API routes in JS: {api_routes}")
    print(f"Hosts in JS: {hosts}")

    # 4. Video / mp4 links
    candidates = set(re.findall(r'https?://[^\s"\'<>]+\.mp4', joined))
    candidates |= set(re.findall(r'"video"\s*:\s*"([^"]+\.mp4)"', joined))
    # Relative uploads/xxx.mp4 -> resolve against hosts found, else www host
    rel = set(re.findall(r'["\'](?:/uploads/|uploads/)([^"\']+\.mp4)["\']', joined))
    for h in hosts:
        for f in rel:
            candidates.add(f"{h.rstrip('/')}/uploads/{f}")
    if not candidates and rel:
        for f in rel:
            candidates.add(f"https://{base}/uploads/{f}")
    candidates = sorted(candidates)[:100]
    print(f"Video/mp4 links found: {len(candidates)}")
    real = missing = html = other = 0
    for url in candidates:
        status, headers, _ = head(url)
        ctype = (headers.get("Content-Type") or headers.get("content-type") or "").lower()
        entry = {"url": url, "status": status, "content_type": ctype}
        report["video_files"].append(entry)
        if status == 200 and "video" in ctype:
            real += 1
        elif status == 200 and "html" in ctype:
            html += 1
        elif status == 404:
            missing += 1
        else:
            other += 1
    print(f"Video test: {real} real mp4, {html} return 200 but HTML, "
          f"{missing} missing (404), {other} other")

    # 5. Exposure checks (status only)
    for path in ("/.env", "/.git/HEAD", "/robots.txt", "/admin", "/api"):
        status, _, _ = head(f"https://{base}{path}")
        report["exposure"][path] = status
        print(f"Exposure {path} -> {status}")

    # 6. Headers
    status, headers, _ = head(f"https://{base}")
    report["headers"] = headers
    wanted = ["Strict-Transport-Security", "X-Content-Type-Options",
              "X-Frame-Options", "Content-Security-Policy", "Referrer-Policy"]
    present = [h for h in wanted if h in headers or h.lower() in {k.lower() for k in headers}]
    print(f"Security headers present: {present or ['none except maybe HSTS']}")
    print(f"Missing: {[h for h in wanted if h not in present]}")

    outdir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                          "scan-output")
    os.makedirs(outdir, exist_ok=True)
    outpath = os.path.join(outdir, f"{domain}.json")
    with open(outpath, "w") as f:
        json.dump(report, f, indent=2)
    print(f"\nReport saved: {outpath}")
    print(f"Summary: subdomains={len(report['subdomains'])} "
          f"api_routes={len(api_routes)} hosts={len(hosts)} "
          f"videos={len(candidates)} real_mp4={real} html200={html} missing404={missing}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
