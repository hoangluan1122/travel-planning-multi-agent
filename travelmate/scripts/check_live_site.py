"""Checks a running TravelMate site the way a visitor would, and the free sources it needs.

    python scripts/check_live_site.py https://your-site.onrender.com
    python scripts/check_live_site.py https://your-site.onrender.com --plan   # also one real plan

Run by .github/workflows/live-check.yml every few hours. Standard library only, so it needs
no install. Exit code 1 when a check fails; warnings (a source that has a fallback) do not
fail. --plan needs TRAVELMATE_API_TOKEN (the operator token, never printed) and spends a few
Gemini calls. A markdown table goes to $GITHUB_STEP_SUMMARY when that is set.
"""

import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, timedelta

USER_AGENT = "TravelMate-live-check/1.0 (+https://github.com/hoangluan1122/travel-planning-multi-agent)"
OK, WARN, FAIL = "ok", "warn", "fail"
MARK = {OK: "✓", WARN: "!", FAIL: "✗"}


class Response:
    def __init__(self, status, headers, body):
        self.status, self.headers, self.body = status, headers, body

    def json(self):
        return json.loads(self.body)


def request(url, data=None, token=None, timeout=30):
    headers = {"User-Agent": USER_AGENT, "Accept": "application/json, text/html"}
    body = None
    if data is not None:
        body = json.dumps(data).encode()
        headers["Content-Type"] = "application/json"
        headers["X-Requested-With"] = "travelmate"
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, data=body, headers=headers, method="POST" if data is not None else "GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as res:
            return Response(res.status, {k.lower(): v for k, v in res.headers.items()}, res.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as err:
        return Response(err.code, {k.lower(): v for k, v in err.headers.items()}, err.read().decode("utf-8", "replace"))


class Checker:
    def __init__(self, base, token=None, wake_s=180):
        self.base, self.token, self.wake_s = base.rstrip("/") + "/", token, wake_s
        self.results = []

    def record(self, name, status, detail):
        self.results.append((name, status, detail))
        print(f"{MARK[status]} {name}: {detail}", flush=True)

    def check(self, name, fn):
        try:
            status, detail = fn()
        except Exception as exc:  # a check that crashes is a failed check, not a crashed run
            status, detail = FAIL, f"{type(exc).__name__}: {str(exc)[:200]}"
        self.record(name, status, detail)

    def url(self, path):
        return urllib.parse.urljoin(self.base, path.lstrip("/"))

    # The site

    def wake(self):
        """A free Render service sleeps after 15 minutes idle; the first request wakes it (~1 min)."""
        started, last = time.monotonic(), "no answer"
        while time.monotonic() - started < self.wake_s:
            try:
                res = request(self.url("/health"), timeout=60)
                if res.status == 200 and res.json().get("status") == "ok":
                    self.health = res.json()
                    return OK, f"trả lời sau {time.monotonic() - started:.0f} giây"
                last = f"HTTP {res.status}"
            except (urllib.error.URLError, TimeoutError, ValueError, OSError) as exc:
                last = type(exc).__name__
            time.sleep(10)
        raise RuntimeError(f"/health không trả lời trong {self.wake_s} giây ({last})")

    def configuration(self):
        h = self.health
        problems = []
        if h.get("mode") != "live":
            problems.append(f"mode={h.get('mode')} (cần live)")
        if not h.get("token_required"):
            problems.append("chưa có TRAVELMATE_API_TOKEN")
        if problems:
            return FAIL, "; ".join(problems)
        if h.get("database") != "postgresql":
            return WARN, "đang dùng SQLite: tài khoản và chuyến đi mất sau mỗi lần deploy"
        return OK, f"live, {h.get('orchestrator')}, {h.get('place_provider')}, {h.get('database')}"

    def home(self):
        res = request(self.url("/"))
        if res.status != 200 or "TravelMate" not in res.body:
            return FAIL, f"HTTP {res.status}"
        assets = sorted(set(re.findall(r'(?:src|href)="(/ui/[^"#?]+)"', res.body)))
        broken = [a for a in assets if request(self.url(a)).status != 200]
        if broken:
            return FAIL, "không tải được: " + ", ".join(broken)
        missing = [h for h in ("x-content-type-options", "x-frame-options") if h not in res.headers]
        if self.base.startswith("https://") and "strict-transport-security" not in res.headers:
            missing.append("strict-transport-security")
        if missing:
            return FAIL, "thiếu header bảo mật: " + ", ".join(missing)
        return OK, f"trang chủ và {len(assets)} tệp giao diện tải được"

    def pages(self):
        bad = []
        for path in ("/?view=explore", "/?view=about", "/?view=pricing", "/?view=privacy", "/robots.txt",
                     "/sitemap.xml", "/api/v1/site"):
            res = request(self.url(path))
            if res.status != 200:
                bad.append(f"{path} → {res.status}")
        return (FAIL, "; ".join(bad)) if bad else (OK, "các trang công khai, robots.txt, sitemap.xml")

    def guard(self):
        res = request(self.url("/api/v1/plans/preview"), data={})
        if res.status != 401:
            return FAIL, f"tạo lịch trình khi chưa đăng nhập trả về HTTP {res.status} (cần 401)"
        return OK, "API AI yêu cầu đăng nhập"

    # The free sources a plan needs (checked from here, which is close enough to the server)

    def open_meteo(self):
        res = request("https://geocoding-api.open-meteo.com/v1/search?name=Hue&count=1&language=vi", timeout=15)
        if res.status != 200 or not res.json().get("results"):
            return FAIL, f"HTTP {res.status}: không tìm được điểm đến, không có thời tiết"
        return OK, "tìm điểm đến và thời tiết"

    def place_sources(self):
        photon = wiki = False
        try:
            photon = request("https://photon.komoot.io/api/?q=Hu%E1%BA%BF&limit=1", timeout=15).status == 200
        except (urllib.error.URLError, TimeoutError, OSError):
            pass
        try:
            wiki = request("https://vi.wikipedia.org/w/api.php?action=query&list=geosearch&format=json"
                           "&gscoord=16.4637%7C107.5909&gsradius=5000&gslimit=5", timeout=15).status == 200
        except (urllib.error.URLError, TimeoutError, OSError):
            pass
        if photon and wiki:
            return OK, "Photon (OpenStreetMap) và Wikipedia"
        if wiki:
            return WARN, "Photon không trả lời: lịch trình lấy điểm tham quan từ Wikipedia, thiếu quán ăn và nơi ở"
        if photon:
            return OK, "Photon trả lời; Wikipedia (dự phòng) không trả lời"
        return FAIL, "cả Photon lẫn Wikipedia đều không trả lời: không tạo được lịch trình"

    # One real plan, end to end (Gemini included)

    def plan(self):
        start = date.today() + timedelta(days=14)
        trip = {"destination": "Huế", "start_date": start.isoformat(), "end_date": (start + timedelta(days=1)).isoformat(),
                "travelers": 2, "budget_vnd": 5_000_000, "interests": ["di tích"]}
        started = time.monotonic()
        res = request(self.url("/api/v1/plans/preview"), data=trip, token=self.token, timeout=300)
        seconds = time.monotonic() - started
        if res.status != 200:
            detail = ""
            try:
                detail = str(res.json().get("detail", ""))[:150]
            except ValueError:
                pass
            return FAIL, f"HTTP {res.status} sau {seconds:.0f} giây {detail}".strip()
        plan = res.json()
        days, places = plan.get("draft", {}).get("days", []), plan.get("places", [])
        if not days or not places:
            return FAIL, f"lịch trình rỗng ({len(days)} ngày, {len(places)} địa điểm)"
        by = (plan.get("self_check") or {}).get("scheduled_by", "?")
        detail = f"{len(days)} ngày, {len(places)} địa điểm, xếp bởi {by}, {seconds:.0f} giây"
        if by == "rules":
            return WARN, detail + " (Gemini không trả lời, đã xếp theo quy tắc)"
        if seconds > 240:
            return WARN, detail + " (gần giới hạn chờ 300 giây của trang)"
        return OK, detail

    def run(self, plan=False):
        self.check("Máy chủ thức dậy", self.wake)
        if any(status == FAIL for _, status, _ in self.results):
            return self.results
        for name, fn in [("Cấu hình", self.configuration), ("Trang chủ", self.home), ("Các trang", self.pages),
                         ("Bảo vệ API", self.guard), ("Open-Meteo", self.open_meteo),
                         ("Nguồn địa điểm", self.place_sources)]:
            self.check(name, fn)
        if plan:
            if self.token:
                self.check("Tạo lịch trình thật", self.plan)
            else:
                self.record("Tạo lịch trình thật", WARN, "bỏ qua: chưa có TRAVELMATE_API_TOKEN")
        return self.results


def summary(base, results):
    lines = [f"### Kiểm tra {base}", "", "| | Kiểm tra | Kết quả |", "|---|---|---|"]
    lines += [f"| {MARK[s]} | {name} | {detail.replace('|', '/')} |" for name, s, detail in results]
    return "\n".join(lines) + "\n"


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("url", help="địa chỉ trang, ví dụ https://travelmate.onrender.com")
    parser.add_argument("--plan", action="store_true", help="tạo thêm một lịch trình thật (tốn vài lượt Gemini)")
    parser.add_argument("--wake-seconds", type=int, default=180)
    args = parser.parse_args(argv)
    if not args.url.startswith(("https://", "http://")):
        parser.error("url phải bắt đầu bằng https:// hoặc http://")
    checker = Checker(args.url, os.environ.get("TRAVELMATE_API_TOKEN") or None, args.wake_seconds)
    results = checker.run(plan=args.plan)
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as out:
            out.write(summary(args.url, results))
    failed = [name for name, status, _ in results if status == FAIL]
    print(("HỎNG: " + ", ".join(failed)) if failed else "Tất cả kiểm tra bắt buộc đều qua.")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
