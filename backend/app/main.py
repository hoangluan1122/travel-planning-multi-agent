from fastapi import FastAPI
from app.agents import PlannerAgent
from app.schemas import TripPlan, TripRequest

app = FastAPI(title="Travel Planning Multi-Agent API", version="0.1.0")
planner = PlannerAgent()


@app.get("/health")
def health_check() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/v1/trips/plan", response_model=TripPlan, tags=["trip-planning"])
def create_trip_plan(request: TripRequest) -> TripPlan:
    return planner.plan(request)

