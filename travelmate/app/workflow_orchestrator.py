"""Microsoft Agent Framework Workflow version of Orchestrator.

Same registry agents and the same step rules (checked_places, checked_weather,
validate_draft, plan_response), expressed as an explicit executor graph:

    memory ──► place ───┐
          └──► weather ─┴─► recommendation ─► planner ─► validate ─► budget ─► PlanResponse

place and weather run in the same superstep (fan-out) and recommendation waits for
both (fan-in). A new Workflow is built per request: workflow instances keep run
state and are not meant to be shared by concurrent requests.
"""

from dataclasses import dataclass, replace

from .agents import AgentError
from .models import (
    BudgetInput,
    BudgetResult,
    Context,
    Draft,
    PlaceResult,
    PlannerInput,
    Preferences,
    RecommendationInput,
    TripRequest,
    WeatherResult,
)
from .orchestrator import checked_places, checked_weather, plan_response, validate_draft


@dataclass
class PlanState:
    """Message passed along the graph; each step fills in its own field."""

    trip: TripRequest
    memory: Preferences | None = None
    places: PlaceResult | None = None
    weather: WeatherResult | None = None
    ranked: PlaceResult | None = None
    draft: Draft | None = None
    budget: BudgetResult | None = None


class WorkflowOrchestrator:
    def __init__(self, registry, mode="demo", timeout=45, checkpoint_storage=None):
        self.registry, self.mode, self.timeout = registry, mode, timeout
        self.checkpoint_storage = checkpoint_storage

    def build(self, context):
        from typing import Never

        from agent_framework import WorkflowBuilder, WorkflowContext, executor

        async def run(name, data):
            return await self.registry.get(name).run(data, context, self.timeout)

        @executor(id="memory")
        async def memory(trip: TripRequest, ctx: WorkflowContext[PlanState]) -> None:
            await ctx.send_message(PlanState(trip=trip, memory=await run("memory", trip)))

        @executor(id="place")
        async def place(state: PlanState, ctx: WorkflowContext[PlanState]) -> None:
            try:
                result = await run("place", state.trip)
            except BaseException as exc:  # classified by the shared rule, incl. cancellation
                result = exc
            await ctx.send_message(replace(state, places=checked_places(result)))

        @executor(id="weather")
        async def weather(state: PlanState, ctx: WorkflowContext[PlanState]) -> None:
            try:
                result = await run("weather", state.trip)
            except BaseException as exc:
                result = exc
            await ctx.send_message(replace(state, weather=checked_weather(result)))

        @executor(id="recommendation")
        async def recommendation(branches: list[PlanState], ctx: WorkflowContext[PlanState]) -> None:
            places = next((b.places for b in branches if b.places is not None), None)
            forecast = next((b.weather for b in branches if b.weather is not None), None)
            if places is None or forecast is None:
                raise AgentError("Workflow fan-in is missing place or weather results")
            state = replace(branches[0], places=places, weather=forecast)
            ranked = await run("recommendation", RecommendationInput(places=places, preferences=state.memory))
            await ctx.send_message(replace(state, ranked=ranked))

        @executor(id="planner")
        async def planner(state: PlanState, ctx: WorkflowContext[PlanState]) -> None:
            draft = await run(
                "planner",
                PlannerInput(
                    trip=state.trip, places=state.ranked, weather=state.weather, preferences=state.memory
                ),
            )
            await ctx.send_message(replace(state, draft=draft))

        @executor(id="validate")
        async def validate(state: PlanState, ctx: WorkflowContext[PlanState]) -> None:
            validate_draft(state.trip, state.draft, state.ranked)
            await ctx.send_message(state)

        @executor(id="budget")
        async def budget(state: PlanState, ctx: WorkflowContext[Never, object]) -> None:
            result = await run("budget", BudgetInput(trip=state.trip, draft=state.draft, places=state.ranked))
            await ctx.yield_output(
                plan_response(
                    context, self.mode, state.draft, state.ranked, state.weather, result, state.memory
                )
            )

        return (
            WorkflowBuilder(
                name="travelmate_plan",
                start_executor=memory,
                checkpoint_storage=self.checkpoint_storage,
            )
            .add_fan_out_edges(memory, [place, weather])
            .add_fan_in_edges([place, weather], recommendation)
            .add_chain([recommendation, planner, validate, budget])
            .build()
        )

    async def plan(self, trip):
        context = Context()
        result = await self.build(context).run(trip)
        outputs = result.get_outputs()
        if len(outputs) != 1:
            raise AgentError("Planning workflow ended without a plan")
        return outputs[0]
