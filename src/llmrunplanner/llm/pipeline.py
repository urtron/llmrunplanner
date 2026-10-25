import json
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from sqlite3 import Connection
from typing import Any

from pydantic import BaseModel

from ..config import KNOWLEDGE_BASE_DIR, load_settings
from ..domain import (
    ActivitySource,
    AthleteMetrics,
    CallRecord,
    GateResult,
    GateStatus,
    Goal,
    HistorySummary,
    Interpretation,
    InterpretationCheck,
    PlanRecord,
    Skeleton,
    Violation,
    Week,
)
from ..metrics import compute_athlete_metrics
from ..plan import calendar_weeks, load_workout_catalog, pre_plan_days
from ..safety import run_gate
from ..storage import (
    get_athlete,
    load_activities,
    load_garmin_metrics,
    load_samples,
    save_llm_call,
    save_plan,
)
from ..summary import build_history_summary
from ..validator import load_rules
from .graph import GraphDeps, build_graph
from .models import DEFAULT_MODEL, MODELS, PROVIDER_ERRORS, make_chat_model
from .prompts import context_hash


@dataclass
class PlanOutcome:
    plan_id: str
    run_id: str
    gate: GateResult
    summary: HistorySummary
    metrics: AthleteMetrics
    status: str  # ok | niezatwierdzony | wstrzymany (Bramka bezpieczeństwa) | błąd API
    error: str | None = None
    interpretation: Interpretation | None = None
    interpretation_check: InterpretationCheck | None = None
    uncited_count: int | None = None
    skeleton: Skeleton | None = None
    skeleton_status: str | None = None
    skeleton_violations: list[Violation] = field(default_factory=list)
    skeleton_format_errors: list[str] = field(default_factory=list)
    week: Week | None = None
    week_status: str | None = None
    week_violations: list[Violation] = field(default_factory=list)
    week_format_errors: list[str] = field(default_factory=list)
    pre_plan_days: list[date] = field(default_factory=list)
    calls: list[CallRecord] = field(default_factory=list)
    # sumy są puste, gdy którekolwiek wywołanie nie ma liczby tokenów, by nie zaniżać kosztu
    total_cost_usd: float | None = 0.0
    total_tokens_in: int | None = 0
    total_tokens_out: int | None = 0
    total_latency_ms: int = 0


def _json(value: BaseModel | None) -> str | None:
    return None if value is None else value.model_dump_json()


def _violations_json(violations: list[Violation]) -> str:
    return json.dumps([v.model_dump(mode="json") for v in violations], ensure_ascii=False)


def _errors_json(errors: list[str]) -> str:
    return json.dumps(errors, ensure_ascii=False)


def _total[T: (int, float)](values: list[T | None]) -> T | None:
    return None if any(v is None for v in values) else sum(v for v in values if v is not None)


def _api_error(e: Exception) -> str:
    status = getattr(e, "status_code", None)
    prefix = f"{type(e).__name__} (HTTP {status})" if status else type(e).__name__
    return f"{prefix}: {e}"[:2000]


def create_plan(
    conn: Connection,
    athlete_id: str,
    goal: Goal,
    answers: dict[str, bool],
    data_cutoff: date,
    model_key: str = DEFAULT_MODEL,
    progress: Callable[[str], None] | None = None,
) -> PlanOutcome:
    spec = MODELS[model_key]
    athlete = get_athlete(conn, athlete_id)
    if athlete is None:
        raise ValueError(f"Nie ma Biegacza o identyfikatorze {athlete_id}.")
    if spec.provider == "openrouter" and athlete.source is not ActivitySource.GARMIN:
        raise ValueError(
            f"Model {spec.label} działa przez OpenRouter, którego darmowe punkty dostępowe mogą zapisywać prompty; "
            "można go użyć tylko dla danych autora (źródło GARMIN)."
        )
    activities = load_activities(conn, athlete_id, data_cutoff)
    samples = {a.id: load_samples(conn, a.id, data_cutoff) for a in activities}
    garmin = load_garmin_metrics(conn, athlete_id, data_cutoff)
    metrics = compute_athlete_metrics(athlete, activities, samples, garmin, data_cutoff)
    summary = build_history_summary(athlete, activities, metrics, metrics.daily, data_cutoff)
    gate = run_gate(answers, goal, summary, metrics)

    plan_id, run_id = uuid.uuid4().hex, uuid.uuid4().hex
    if gate.status is GateStatus.STOP:
        return PlanOutcome(
            plan_id=plan_id, run_id=run_id, gate=gate, summary=summary, metrics=metrics, status="wstrzymany"
        )
    if not metrics.zones:
        raise ValueError("Brak Stref: nie wyznaczono Progu, więc nie da się przeliczyć intensywności.")

    weeks = calendar_weeks(data_cutoff, goal.race_date)
    calls: list[CallRecord] = []

    def on_call(record: CallRecord) -> None:
        calls.append(record)
        save_llm_call(conn, record)

    deps = GraphDeps(
        chat=make_chat_model(spec, load_settings()),
        spec=spec,
        registry=load_rules(KNOWLEDGE_BASE_DIR / "rules.yaml"),
        catalog=load_workout_catalog(KNOWLEDGE_BASE_DIR / "workout_catalog.yaml"),
        context_hash=context_hash(),
        on_call=on_call,
        progress=progress,
    )
    state: dict[str, Any] = {
        "run_id": run_id,
        "plan_id": plan_id,
        "athlete_id": athlete_id,
        "goal": goal,
        "as_of": data_cutoff,
        "data_cutoff": data_cutoff,
        "model_key": model_key,
        "summary": summary,
        "metrics": metrics,
        "weeks": weeks,
        "gate": gate,
    }
    error: str | None = None
    try:
        # stan po każdym ukończonym węźle, by po błędzie dostawcy zachować wyniki wcześniejszych kroków
        for values in build_graph(deps).stream(state, stream_mode="values"):
            state = values
    except PROVIDER_ERRORS as e:
        error = _api_error(e)

    skeleton_status = state.get("skeleton_status")
    week_status = state.get("week_status")
    if error is not None:
        status = "błąd API"
    else:
        status = "ok" if skeleton_status == "ok" and week_status == "ok" else "niezatwierdzony"
    check = state.get("interpretation_check")
    outcome = PlanOutcome(
        plan_id=plan_id,
        run_id=run_id,
        gate=gate,
        summary=summary,
        metrics=metrics,
        status=status,
        error=error,
        interpretation=state.get("interpretation"),
        interpretation_check=check,
        uncited_count=None if check is None else len(check.uncited),
        skeleton=state.get("skeleton"),
        skeleton_status=skeleton_status,
        skeleton_violations=state.get("skeleton_violations", []),
        skeleton_format_errors=state.get("skeleton_format_errors", []),
        week=state.get("week"),
        week_status=week_status,
        week_violations=state.get("week_violations", []),
        week_format_errors=state.get("week_format_errors", []),
        pre_plan_days=pre_plan_days(data_cutoff, weeks),
        calls=calls,
        total_cost_usd=_total([c.cost_usd for c in calls]),
        total_tokens_in=_total([c.input_tokens for c in calls]),
        total_tokens_out=_total([c.output_tokens for c in calls]),
        total_latency_ms=sum(c.latency_ms for c in calls),
    )
    save_plan(
        conn,
        PlanRecord(
            id=plan_id,
            run_id=run_id,
            athlete_id=athlete_id,
            data_cutoff=data_cutoff,
            as_of=data_cutoff,
            goal_json=goal.model_dump_json(),
            model_key=model_key,
            status=status,
            error=error,
            gate_json=gate.model_dump_json(),
            interpretation_json=_json(outcome.interpretation),
            interpretation_check_json=_json(outcome.interpretation_check),
            skeleton_json=_json(outcome.skeleton),
            skeleton_status=skeleton_status,
            skeleton_violations_json=_violations_json(outcome.skeleton_violations) if skeleton_status else None,
            skeleton_format_errors_json=_errors_json(outcome.skeleton_format_errors) if skeleton_status else None,
            week_json=_json(outcome.week),
            week_status=week_status,
            week_violations_json=_violations_json(outcome.week_violations) if week_status else None,
            week_format_errors_json=_errors_json(outcome.week_format_errors) if week_status else None,
            created_at=datetime.now(UTC),
        ),
    )
    return outcome
