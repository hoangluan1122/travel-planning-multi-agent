"""TravelMate web server: `uvicorn app.main:create_app --factory`.

This file only puts the pieces together:

- app/settings.py      configuration (environment and .env)
- app/services.py      the agents and data sources, chosen from the settings
- app/api/             the routes: plans.py (places, plans), chat.py, site.py (pages, health),
                       deps.py (who is calling, daily limits)
- app/trust/accounts.py  sign-up, sign-in, trips, favourites, reviews, admin
- app/protocols/a2a.py   the A2A endpoint for other agents
"""

# Điểm khởi động máy chủ web. Lệnh chạy: uvicorn app.main:create_app --factory.
# File này không chứa logic nghiệp vụ: nó chỉ đọc cấu hình, dựng các dịch vụ (agent, nguồn dữ liệu, cơ sở dữ
# liệu) rồi gắn từng nhóm endpoint vào ứng dụng FastAPI.

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.agents.plan_jobs import PlanJobs
from app.api.chat import create_chat_router
from app.api.deps import ApiDeps
from app.api.plans import create_plans_router
from app.api.site import FRONTEND, create_site_router, security_headers
from app.core.telemetry import configure_telemetry
from app.protocols.a2a import create_a2a_router
from app.services import build_services
from app.settings import Settings
from app.tools.places.provider_wrappers import CachingProvider, HidingProvider
from app.trust.accounts import create_accounts_router

# Older code and tests import these from app.main.
# Giữ các tên cũ để code và test cũ vẫn viết được `from app.main import ...`.
__all__ = ["CachingProvider", "HidingProvider", "Settings", "build_services", "create_app"]


# Tạo ứng dụng FastAPI. Test truyền orchestrator/provider/chat/store giả để thay một phần; khi chạy thật thì
# mọi tham số đều để None và được dựng từ cấu hình.
def create_app(settings=None, orchestrator=None, provider=None, chat=None, store=None):
    """The FastAPI app. Tests pass their own orchestrator, provider, chat or store."""
    settings = settings or Settings()
    configure_telemetry(settings.travelmate_telemetry, "travelmate-api")
    # Cơ sở dữ liệu sản phẩm: PostgreSQL nếu có TRAVELMATE_DATABASE_URL, không thì một file SQLite.
    if store is None:
        from app.memory.store import Store

        store = Store(settings.travelmate_database_url or settings.travelmate_db, settings.travelmate_admin_email)
    # Dựng agent và nguồn địa điểm. hidden_ids: địa điểm admin đã ẩn; place_cache: dùng chính cơ sở dữ liệu
    # để lưu kết quả tìm 24 giờ.
    services = build_services(settings, orchestrator, provider, chat, hidden_ids=store.hidden_place_ids,
                              place_cache=store)
    # Danh sách các lịch trình đang tạo nền (nằm trong bộ nhớ của tiến trình).
    jobs = PlanJobs()

    app = FastAPI(title="TravelMate API", version="0.1.0")
    # Lưu vào app.state để test và các phần khác lấy ra được.
    app.state.services, app.state.chat, app.state.store, app.state.plan_jobs = services, services.chat, store, jobs

    # Các hàm dùng chung cho mọi endpoint: ai đang gọi, hạn mức AI mỗi ngày.
    deps = ApiDeps(services.settings, store)
    # Gắn từng nhóm endpoint. Thứ tự có ý nghĩa: /api/v1/places/photo phải đứng trước /api/v1/places/{id}
    # của nhóm tài khoản.
    app.include_router(create_plans_router(deps, services.provider, services.orchestrator, jobs, services.photos))
    app.include_router(create_chat_router(deps, services.chat))
    app.include_router(create_accounts_router(store, services.settings))
    app.include_router(create_a2a_router(services.chat, services.settings.travelmate_api_token))
    app.include_router(create_site_router(deps))

    # Thêm header bảo mật cho mọi phản hồi.
    app.middleware("http")(security_headers)
    # Phục vụ file tĩnh của giao diện (JS, CSS, ảnh, font) tại /ui/.
    app.mount("/ui", StaticFiles(directory=FRONTEND), name="ui")
    return app
