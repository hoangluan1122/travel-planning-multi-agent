"""Routes for places and plans.

POST /api/v1/places/search      places for a stated wish ("mì Quảng ở Đà Nẵng")
GET  /api/v1/places/photo       Google photo redirect (only names this server handed out)
POST /api/v1/plans/jobs         start a plan in the background (what the web page uses)
GET  /api/v1/plans/jobs/{id}    its stage, then its result
POST /api/v1/plans/preview      a plan in one request (kept for scripts and the live check)
"""

import asyncio
import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse

from app.api.deps import ApiDeps, Credentials, log_plan_failure
from app.core.base import AgentError
from app.core.models import PlaceResult, PlaceSearchRequest, PlanResponse, TripRequest

logger = logging.getLogger(__name__)


def create_plans_router(deps: ApiDeps, provider, orchestrator, jobs, photos=None):
    router = APIRouter()
    authorized = [Depends(deps.authorize)]
    store = deps.store

    @router.get("/api/v1/places/photo", include_in_schema=False)
    async def place_photo(ref: str):
        # No bearer token: <img> tags cannot send one. Only photo names this server returned
        # in a search are resolved, so the key cannot be spent on arbitrary requests.
        if photos is None:
            raise HTTPException(404, "Photos are not enabled")
        try:
            uri = await photos.resolve(ref)
        except Exception:
            raise HTTPException(502, "Photo unavailable") from None
        if uri is None:
            raise HTTPException(404, "Unknown photo")
        return RedirectResponse(uri, status_code=302, headers={"Cache-Control": "private, max-age=3000"})

    @router.post("/api/v1/places/search", response_model=PlaceResult, dependencies=authorized)
    async def search_places(query: PlaceSearchRequest):
        try:
            result = await provider.search_places(query)
            result = result.model_copy(update={"places": await deps.visible(result.places)})
            await deps.remember(result.places)
            return result
        except TimeoutError:
            raise HTTPException(504, "Place lookup timed out") from None
        except AgentError as exc:
            raise HTTPException(502, str(exc)) from None
        except Exception:
            raise HTTPException(502, "Place lookup failed") from None

    @router.post("/api/v1/plans/preview", response_model=PlanResponse, dependencies=authorized)
    async def preview(trip: TripRequest, request: Request, credentials: Credentials):
        owner = await deps.quota_owner(request, credentials, "plan")
        try:
            plan = await orchestrator.plan(trip)
            await deps.remember(plan.places + plan.stays)
            await deps.charge(owner, "plan")
            return plan
        except TimeoutError:
            raise HTTPException(504, "Agent processing timed out") from None
        except AgentError as exc:
            raise HTTPException(502, str(exc)) from None
        except Exception as exc:
            log_plan_failure("plan_preview", exc)
            raise HTTPException(502, "Planning failed; check provider configuration and retry") from None

    @router.post("/api/v1/plans/jobs", status_code=202, dependencies=authorized)
    async def start_plan(trip: TripRequest, request: Request, credentials: Credentials):
        """Start a plan in the background; poll GET /api/v1/plans/jobs/{job_id} for its stage and result.

        A signed-in user's plan is saved to their trips when it is ready, so closing the page
        loses nothing. One plan at a time per account: a second start returns 409 with the
        running job's id.
        """
        owner, user = await deps.job_owner(request, credentials)
        running = jobs.running_for(owner)
        if running is not None:
            raise HTTPException(409, {"message": "Bạn đang có một lịch trình đang được tạo. Đợi xong rồi tạo tiếp.",
                                      "job_id": running.id})
        quota = await deps.quota_owner(request, credentials, "plan")

        async def work(job):
            try:
                plan = await orchestrator.plan(trip)
                await deps.remember(plan.places + plan.stays)
                await deps.charge(quota, "plan")
                result = plan.model_dump(mode="json")
                if user is not None:
                    job.update("saving", {})
                    try:
                        saved = await asyncio.to_thread(
                            store.save_trip, user["id"], trip.model_dump(mode="json"), result,
                            f"{trip.destination} · {len(plan.draft.days)} ngày")
                        job.trip_id = saved["id"]
                    except Exception as exc:  # the plan is still shown; the page can save it again
                        logger.warning("plan_job save outcome=failed error_type=%s", type(exc).__name__)
                job.result = result
            except TimeoutError:
                job.fail(504, "Quá thời gian xử lý. Vui lòng thử lại.")
            except AgentError as exc:
                job.fail(502, str(exc))
            except Exception as exc:
                log_plan_failure("plan_job", exc)
                job.fail(502, "Chưa tạo được lịch trình. Vui lòng thử lại sau ít phút.")

        return jobs.start(owner, work).view()

    @router.get("/api/v1/plans/jobs/{job_id}", dependencies=authorized)
    async def plan_job(job_id: str, request: Request, credentials: Credentials):
        owner, _ = await deps.job_owner(request, credentials)
        job = jobs.get(job_id, owner)
        if job is None:
            raise HTTPException(404, "Không tìm thấy yêu cầu tạo lịch trình này (có thể máy chủ vừa khởi động lại).")
        return job.view()

    return router
