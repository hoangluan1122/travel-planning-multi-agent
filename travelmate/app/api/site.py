"""The public website: the page itself, search-engine files, status and site info.

The web app is one HTML page (frontend/travelmate-v2/index.html) that shows a view per
`?view=`. Public views get their own title, description and share preview filled in on the
server, so links shared in chat apps and search results look right without JavaScript.
"""

# Trang web công khai. Cả trang là một file index.html; mỗi màn hình là một ?view=. Máy chủ điền sẵn tiêu
# đề, mô tả và thẻ chia sẻ (Open Graph) cho từng trang công khai, để Google và Facebook/Zalo hiển thị đúng
# mà không cần chạy JavaScript.

import asyncio
import html
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, PlainTextResponse, RedirectResponse, Response

from app.api.deps import ApiDeps, Credentials

# Thư mục frontend/ nằm cạnh thư mục app/.
FRONTEND = Path(__file__).resolve().parent.parent.parent / "frontend"
INDEX = FRONTEND / "travelmate-v2" / "index.html"
# Pages anyone can read; search engines index these and nothing else.
# Trang được phép xuất hiện trên Google: (tiêu đề, mô tả).
PUBLIC_PAGES = {
    "home": ("TravelMate — Lên kế hoạch du lịch cùng AI",
             "Lập lịch trình du lịch Việt Nam theo từng ngày, ước tính chi phí so với ngân sách, xem thời tiết "
             "và hỏi Trợ lý AI."),
    "explore": ("Khám phá địa điểm — TravelMate", "Tìm điểm tham quan, quán ăn và khách sạn ở các điểm đến Việt Nam."),
    "chat": ("Trợ lý AI du lịch — TravelMate", "Hỏi quán ăn, giá vé, thời tiết hoặc nhờ lập lịch trình bằng tiếng Việt."),
    "create": ("Tạo chuyến đi — TravelMate", "Nhập điểm đến, ngày đi, số người và ngân sách để nhận lịch trình từng ngày."),
    "about": ("Giới thiệu — TravelMate", "TravelMate là gì, làm được gì và dữ liệu đến từ đâu."),
    "pricing": ("Bảng giá — TravelMate", "TravelMate miễn phí. Hạn mức sử dụng AI mỗi ngày và câu hỏi thường gặp."),
    "contact": ("Liên hệ — TravelMate", "Gửi câu hỏi, góp ý hoặc đề nghị hợp tác cho TravelMate."),
    "terms": ("Điều khoản sử dụng — TravelMate", "Điều khoản sử dụng dịch vụ TravelMate."),
    "privacy": ("Chính sách bảo mật — TravelMate", "TravelMate thu thập dữ liệu gì, dùng vào việc gì và quyền của bạn."),
}


# Thay chỗ đánh dấu <!--SEO--> trong index.html bằng thẻ meta của trang. html.escape chống chèn mã HTML.
def page_html(view, base):
    """index.html with the title, description, canonical link and share preview of one page."""
    text = INDEX.read_text("utf-8")
    page = PUBLIC_PAGES.get(view)
    if page is None:  # private or unknown pages: keep them out of search results
        return text.replace("<!--SEO-->", '<meta name="robots" content="noindex">')
    title, description = (html.escape(x) for x in page)
    url = html.escape(f"{base}/" + ("" if view == "home" else f"?view={view}"))
    image = html.escape(f"{base}/ui/travelmate-ui/assets/beach.jpg")
    seo = "\n".join([
        f'<link rel="canonical" href="{url}">',
        '<meta property="og:type" content="website">', '<meta property="og:site_name" content="TravelMate">',
        '<meta property="og:locale" content="vi_VN">',
        f'<meta property="og:title" content="{title}">', f'<meta property="og:description" content="{description}">',
        f'<meta property="og:url" content="{url}">', f'<meta property="og:image" content="{image}">',
        '<meta name="twitter:card" content="summary_large_image">',
    ])
    text = text.replace("<!--SEO-->", seo)
    start, end = text.index("<title>"), text.index("</title>") + len("</title>")
    text = text[:start] + f"<title>{title}</title>" + text[end:]
    start = text.index('<meta name="description" content="')
    end = text.index('">', start) + 2
    return text[:start] + f'<meta name="description" content="{description}">' + text[end:]


# Nhóm endpoint của trang web.
def create_site_router(deps: ApiDeps):
    router = APIRouter()
    settings, store = deps.settings, deps.store

    # Dùng cho Render và kiểm tra trang thật: máy chủ còn sống và đang chạy cấu hình nào (không có bí mật).
    @router.get("/health")
    async def health():
        """Liveness plus the configuration the live check verifies (no secrets)."""
        return {
            "status": "ok",
            "mode": settings.travelmate_mode,
            "token_required": bool(settings.travelmate_api_token),
            "place_provider": None if settings.travelmate_mode == "demo" else settings.travelmate_place_provider,
            "agent_engine": settings.agent_engine,
            "orchestrator": settings.travelmate_orchestrator,
            "accounts": True,
            "database": store.backend,
            "signup_open": settings.travelmate_signup_open,
        }

    # Thông tin hiển thị ở trang Liên hệ, Bảng giá, Điều khoản.
    @router.get("/api/v1/site")
    async def site():
        """What the public pages show: who runs the site, how to reach them, the daily limits."""
        return {
            "operator_name": settings.travelmate_operator_name,
            "contact_email": settings.travelmate_contact_email,
            "daily_plans": settings.travelmate_daily_plans,
            "daily_chats": settings.travelmate_daily_chats,
            "signup_open": settings.travelmate_signup_open,
        }

    # Số lượt AI đã dùng hôm nay; admin không bị giới hạn (limit None).
    @router.get("/api/v1/me/usage")
    async def my_usage(request: Request, credentials: Credentials):
        """Today's AI uses of the signed-in user and their limits (None: not limited)."""
        user = await deps.user(request, credentials)
        if user is None:
            raise HTTPException(401, "Bạn cần đăng nhập, hoặc phiên đăng nhập đã hết hạn.")
        used = await asyncio.to_thread(store.usage_today, user["id"])
        admin = user["role"] == "admin"
        return {kind: {"used": used.get(kind, 0),
                       "limit": None if admin or not deps.daily_limit(kind) else deps.daily_limit(kind)}
                for kind in ("plan", "chat")}

    # Trang chủ và mọi màn hình: cùng một file HTML, khác phần SEO.
    @router.get("/", include_in_schema=False)
    async def frontend(request: Request, view: str = "home"):
        return HTMLResponse(page_html(view, deps.public_base(request)), headers={"Cache-Control": "no-cache"})

    # Chuyển hướng vĩnh viễn (301) từ địa chỉ cũ.
    @router.get("/ui/travelmate-v2/index.html", include_in_schema=False)
    async def old_address(request: Request):
        # The site lives at /; old links and bookmarks keep working.
        query = request.url.query
        return RedirectResponse("/" + (f"?{query}" if query else ""), status_code=301)

    # Cho phép máy tìm kiếm đọc trang, cấm đọc /api/.
    @router.get("/robots.txt", include_in_schema=False)
    async def robots(request: Request):
        return PlainTextResponse(f"User-agent: *\nDisallow: /api/\nSitemap: {deps.public_base(request)}/sitemap.xml\n")

    # Danh sách trang công khai cho máy tìm kiếm.
    @router.get("/sitemap.xml", include_in_schema=False)
    async def sitemap(request: Request):
        base = html.escape(deps.public_base(request))
        urls = "".join(f"<url><loc>{base}/{'' if view == 'home' else '?view=' + view}</loc></url>"
                       for view in PUBLIC_PAGES)
        return Response('<?xml version="1.0" encoding="UTF-8"?>'
                        f'<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{urls}</urlset>',
                        media_type="application/xml")

    return router


# Middleware: chạy cho MỌI phản hồi. nosniff, chống nhúng trang vào iframe (DENY), tắt camera/micro/vị trí,
# bắt buộc HTTPS (HSTS).
async def security_headers(request, call_next):
    """HTTP middleware: hardening headers for a public site, and no stale UI files."""
    response = await call_next(request)
    # Make browsers revalidate UI files (ETag) so a restarted server never runs stale JS.
    if request.url.path.startswith("/ui/"):
        response.headers["Cache-Control"] = "no-cache"
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
    if request.url.scheme == "https":
        response.headers.setdefault("Strict-Transport-Security", "max-age=31536000")
    return response
