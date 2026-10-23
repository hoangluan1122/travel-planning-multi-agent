"""Render a saved RoadReport as a self-contained HTML road-line preview."""

import argparse
import math
from html import escape
from pathlib import Path

from .specialists.routing import RouteReport


def clock(seconds):
    total = math.ceil(seconds)
    return f"{total // 3600:02}:{total % 3600 // 60:02}:{total % 60:02}"


def render(report):
    if report.path is None:
        raise ValueError("Preview requires validated road geometry")
    points = report.path.geometry.coordinates

    def mercator(lon, lat):
        lat = max(-85.0, min(85.0, lat))
        return math.radians(lon), math.log(math.tan(math.pi / 4 + math.radians(lat) / 2))

    projected = [mercator(lon, lat) for lon, lat in points]
    xs, ys = zip(*projected, strict=True)
    left, bottom = min(xs), min(ys)
    scale = min(760 / max(max(xs) - left, 1e-9), 580 / max(max(ys) - bottom, 1e-9))

    def xy(lon, lat):
        x, y = mercator(lon, lat)
        return 60 + (x - left) * scale, 640 - (y - bottom) * scale

    polyline = " ".join(f"{x:.2f},{y:.2f}" for x, y in (xy(lon, lat) for lon, lat in points))
    order = list(dict.fromkeys(report.path.point_ids))
    snaps = {p.point_id: p for p in report.matrix.snapped_points}
    markers = []
    for index, identity in enumerate(order):
        point = snaps.get(identity)
        if point is None:
            continue
        x, y = xy(point.longitude, point.latitude)
        markers.append(
            f'<g><circle cx="{x:.2f}" cy="{y:.2f}" r="16"/><text x="{x:.2f}" y="{y + 5:.2f}">{index}</text><title>{escape(identity)}</title></g>'
        )
    rows = "".join(
        f"<tr><td>{index + 1}</td><td>{escape(v.place_id)}</td><td>{clock(v.arrival_second)}</td>"
        f"<td>{clock(v.start_second)}–{clock(v.end_second)}</td><td>{v.waiting_seconds / 60:.1f} phút</td></tr>"
        for index, v in enumerate(report.schedule)
    )
    distance = report.path.distance_m / 1000
    return f'''<!doctype html><html lang="vi"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>TravelMate — Kết quả tuyến đường</title><style>
body{{font:16px system-ui;background:#f1f5f9;color:#182437;margin:0;padding:32px}}main{{max-width:1200px;margin:auto}}
h1{{font-size:28px}}.cards{{display:flex;flex-wrap:wrap;gap:12px}}.card,section{{background:white;border-radius:16px;padding:20px;margin:12px 0}}
.card strong{{display:block;font-size:25px;margin-top:6px}}svg{{width:100%;max-height:680px;background:#f8fafc}}polyline{{fill:none;stroke:#2867db;stroke-width:4;stroke-linejoin:round}}
circle{{fill:#172c4d;stroke:white;stroke-width:3}}text{{font:600 14px system-ui;text-anchor:middle;fill:white}}table{{width:100%;border-collapse:collapse}}
td,th{{text-align:left;padding:12px;border-bottom:1px solid #ddd}}.scroll{{overflow-x:auto}}p{{line-height:1.6}}small{{color:#53627a}}
</style><main><h1>TravelMate · Tuyến đường sau tối ưu</h1>
<p>{escape(" → ".join(report.path.point_ids))}</p><div class="cards">
<div class="card">Quãng đường<strong>{distance:.2f} km</strong></div>
<div class="card">Lái xe theo ma trận<strong>{report.travel_seconds / 60:.2f} phút</strong></div>
<div class="card">Đệm di chuyển<strong>{report.buffer_seconds / 60:.1f} phút</strong></div>
<div class="card">Chờ lịch hẹn<strong>{report.waiting_seconds / 60:.1f} phút</strong></div>
<div class="card">Kết thúc ngày<strong>{clock(report.finish_second)}</strong></div></div>
<section><svg viewBox="0 0 880 700" role="img" aria-label="Đường xe theo GeoJSON OSRM">
<polyline points="{polyline}"/>{"".join(markers)}</svg>
<small>Sơ đồ đường xe theo tọa độ, không có nền bản đồ. Số 0 là nơi xuất phát. Dữ liệu OSRM / © OpenStreetMap contributors, ODbL.</small></section>
<section class="scroll"><h2>Lịch sau khi tính di chuyển</h2><table><thead><tr><th>#</th><th>Điểm</th><th>Đến sau đệm</th><th>Hoạt động</th><th>Chờ</th></tr></thead><tbody>{rows}</tbody></table></section>
<p>Vị trí, thời lượng dừng và lịch hẹn do đầu vào cung cấp; cần kiểm tra vị trí vào cửa và giờ hoạt động thực tế.
Thời gian lái xe chưa có giao thông realtime. Thời điểm lấy ma trận: {escape(report.matrix.fetched_at.isoformat())}.</p>
</main></html>'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = RouteReport.model_validate_json(args.input.read_text(encoding="utf-8"))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(render(report), encoding="utf-8")
    print(args.output.resolve())


if __name__ == "__main__":
    main()
