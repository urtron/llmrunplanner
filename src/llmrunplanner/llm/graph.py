from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import TypedDict

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage
from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel

from ..domain import (
    AthleteMetrics,
    CalendarWeek,
    CallRecord,
    GateResult,
    GateStatus,
    Goal,
    HistorySummary,
    Interpretation,
    InterpretationCheck,
    ModelSpec,
    Skeleton,
    Violation,
    Week,
    WeekDraft,
    WorkoutType,
)
from ..plan import CatalogEntry, pace_week, race_day
from ..validator import RuleRegistry, SkeletonContext, WeekContext, skeleton_format_errors
from .citations import check_citations
from .generate import GenerationResult, generate_validated
from .models import CallOutcome, call_structured, cost_usd
from .prompts import (
    load_prompt,
    render_catalog,
    render_days,
    render_goal,
    render_interpretation,
    render_key_workouts,
    render_neighbours,
    render_race_note,
    render_target,
    render_weeks,
    schema_hash,
    summary_hash,
    summary_legend,
)

_NO_INTERPRETATION = "Interpretacja niedostępna: oprzyj się wyłącznie na Podsumowaniu historii."
_WEEK_SKIPPED = "Tydzień 1 pominięty: Szkielet nie ma poprawnej ostatniej odpowiedzi (błędy formatu)."


def _errors(result: GenerationResult) -> list[str]:
    return [*result.format_errors, *([result.last_error] if result.last_error else [])]


class PlanState(TypedDict, total=False):
    run_id: str
    plan_id: str
    athlete_id: str
    goal: Goal
    as_of: date
    summary: HistorySummary
    metrics: AthleteMetrics
    weeks: list[CalendarWeek]
    gate: GateResult
    interpretation: Interpretation | None
    interpretation_check: InterpretationCheck | None
    skeleton: Skeleton | None
    skeleton_status: str
    skeleton_violations: list[Violation]
    skeleton_format_errors: list[str]
    week_draft: WeekDraft | None
    week_status: str
    week_violations: list[Violation]
    week_format_errors: list[str]
    week: Week | None


@dataclass(frozen=True)
class GraphDeps:
    chat: BaseChatModel
    spec: ModelSpec
    registry: RuleRegistry
    catalog: dict[WorkoutType, CatalogEntry]
    context_hash: str
    on_call: Callable[[CallRecord], None]
    progress: Callable[[str], None] | None = None


def build_graph(deps: GraphDeps):
    def say(text: str) -> None:
        if deps.progress is not None:
            deps.progress(text)

    def record(
        state: PlanState,
        step: str,
        week_number: int | None,
        attempt: int,
        template: str,
        schema: type[BaseModel],
        outcome: CallOutcome,
        violations: list[Violation],
        format_errors: list[str],
    ) -> None:
        version = load_prompt(template).version
        if attempt > 0:
            version += f"+repair:{load_prompt('repair').version}"
        parse_error = outcome.parse_error
        if parse_error and outcome.reply_text:
            parse_error += f" Odpowiedź tekstowa: {outcome.reply_text}"
        deps.on_call(
            CallRecord(
                run_id=state["run_id"],
                plan_id=state["plan_id"],
                athlete_id=state["athlete_id"],
                step=step,
                week_number=week_number,
                attempt=attempt,
                model_key=deps.spec.key,
                model_id=deps.spec.model_id,
                prompt_version=version,
                schema_hash=schema_hash(schema),
                summary_hash=summary_hash(state["summary"]),
                context_hash=deps.context_hash,
                as_of=state["as_of"],
                input_tokens=outcome.input_tokens,
                output_tokens=outcome.output_tokens,
                reasoning_tokens=outcome.reasoning_tokens,
                cost_usd=cost_usd(deps.spec, outcome.input_tokens, outcome.output_tokens),
                latency_ms=outcome.latency_ms,
                stop_reason=outcome.stop_reason,
                output_json=outcome.raw_json,
                parse_error=parse_error,
                format_errors=format_errors,
                violations=violations,
                created_at=datetime.now(UTC),
            )
        )

    def common(state: PlanState) -> dict[str, str]:
        return {
            "goal": render_goal(state["goal"]),
            "legend": summary_legend(HistorySummary),
            "summary": state["summary"].model_dump_json(),
        }

    def interpretation_text(state: PlanState) -> str:
        interpretation = state.get("interpretation")
        return _NO_INTERPRETATION if interpretation is None else render_interpretation(interpretation)

    def gate_node(state: PlanState) -> dict:
        return {}

    def after_gate(state: PlanState) -> str:
        if state["gate"].status is GateStatus.STOP:
            return END
        return "interpretation"

    def interpretation_node(state: PlanState) -> dict:
        say("Interpretacja…")
        prompt = load_prompt("interpretation").render(n_weeks=len(state["weeks"]), **common(state))
        outcome = call_structured(deps.chat, Interpretation, [HumanMessage(content=prompt)])
        record(state, "interpretation", None, 0, "interpretation", Interpretation, outcome, [], [])
        interpretation = outcome.parsed if isinstance(outcome.parsed, Interpretation) else None
        check = (
            None
            if interpretation is None
            else check_citations(interpretation, state["summary"], state["goal"].distance)
        )
        return {"interpretation": interpretation, "interpretation_check": check}

    def skeleton_node(state: PlanState) -> dict:
        say("Szkielet…")
        goal, weeks, summary = state["goal"], state["weeks"], state["summary"]
        prompt = load_prompt("skeleton").render(
            n_weeks=len(weeks),
            weeks=render_weeks(weeks),
            catalog=render_catalog(deps.catalog),
            interpretation=interpretation_text(state),
            **common(state),
        )

        def validate(value: BaseModel) -> tuple[list[Violation], list[str]]:
            assert isinstance(value, Skeleton)
            errors = skeleton_format_errors(value, len(weeks))
            ctx = SkeletonContext(skeleton=value, goal=goal, summary=summary, n_weeks=len(weeks))
            return deps.registry.validate_skeleton(ctx), errors

        def on_attempt(i: int, o: CallOutcome, v: list[Violation], f: list[str]) -> None:
            record(state, "skeleton", None, i, "skeleton", Skeleton, o, v, f)

        result = generate_validated(
            lambda messages: call_structured(deps.chat, Skeleton, messages),
            validate,
            [HumanMessage(content=prompt)],
            deps.registry,
            on_attempt,
        )
        return {
            "skeleton": result.value,
            "skeleton_status": result.status,
            "skeleton_violations": result.violations,
            "skeleton_format_errors": _errors(result),
        }

    def after_skeleton(state: PlanState) -> str:
        skeleton = state.get("skeleton")
        if skeleton is not None and not state.get("skeleton_format_errors"):
            return "week1"
        return "week_skipped"

    def week1_node(state: PlanState) -> dict:
        say("Tydzień 1…")
        goal, metrics = state["goal"], state["metrics"]
        skeleton = state["skeleton"]
        assert skeleton is not None
        calendar = state["weeks"][0]
        skeleton_week = skeleton.weeks[0]
        prompt = load_prompt("week").render(
            number=calendar.number,
            phase=skeleton_week.phase.value,
            days=render_days(calendar),
            target=render_target(skeleton_week.target_volume_km, deps.registry),
            key_workouts=render_key_workouts(skeleton_week, deps.catalog),
            race_note=render_race_note(goal, calendar),
            neighbours=render_neighbours(skeleton, calendar.number),
            interpretation=interpretation_text(state),
            catalog=render_catalog(deps.catalog),
            **common(state),
        )

        def validate(value: BaseModel) -> tuple[list[Violation], list[str]]:
            assert isinstance(value, WeekDraft)
            ctx = WeekContext(
                draft=value,
                phase=skeleton_week.phase,
                week=calendar,
                goal=goal,
                target_volume_km=skeleton_week.target_volume_km,
                zones=metrics.zones,
            )
            return deps.registry.validate_week(ctx), []

        def on_attempt(i: int, o: CallOutcome, v: list[Violation], f: list[str]) -> None:
            record(state, "week", calendar.number, i, "week", WeekDraft, o, v, f)

        result = generate_validated(
            lambda messages: call_structured(deps.chat, WeekDraft, messages),
            validate,
            [HumanMessage(content=prompt)],
            deps.registry,
            on_attempt,
        )
        draft = result.value
        paced = None
        if isinstance(draft, WeekDraft) and not _errors(result):
            race = race_day(goal, state["gate"].predicted_time_s) if calendar.end == goal.race_date else None
            paced = pace_week(draft, calendar.number, skeleton_week.phase, calendar, metrics.zones, race)
        return {
            "week_draft": draft if isinstance(draft, WeekDraft) else None,
            "week_status": result.status,
            "week_violations": result.violations,
            "week_format_errors": _errors(result),
            "week": paced,
        }

    def week_skipped_node(state: PlanState) -> dict:
        return {
            "week_draft": None,
            "week_status": "pominięty",
            "week_violations": [],
            "week_format_errors": [_WEEK_SKIPPED],
            "week": None,
        }

    graph = StateGraph(PlanState)
    graph.add_node("gate", gate_node)
    graph.add_node("interpretation", interpretation_node)
    graph.add_node("skeleton", skeleton_node)
    graph.add_node("week1", week1_node)
    graph.add_node("week_skipped", week_skipped_node)
    graph.add_edge(START, "gate")
    graph.add_conditional_edges("gate", after_gate, {"interpretation": "interpretation", END: END})
    graph.add_edge("interpretation", "skeleton")
    graph.add_conditional_edges("skeleton", after_skeleton, {"week1": "week1", "week_skipped": "week_skipped"})
    graph.add_edge("week1", END)
    graph.add_edge("week_skipped", END)
    return graph.compile()
