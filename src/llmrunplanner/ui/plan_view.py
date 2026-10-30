"""Wyświetlanie Planu (świeżo utworzonego albo zapisanego): Szkielet, Tydzień 1, Interpretacja, koszt i czas."""

import json
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

import pandas as pd
import streamlit as st

from ..config import KNOWLEDGE_BASE_DIR
from ..domain import (
    CallRecord,
    Goal,
    Interpretation,
    InterpretationCheck,
    PacedSegment,
    PacedWorkout,
    PlanRecord,
    RuleKind,
    Skeleton,
    Violation,
    Week,
    WorkoutType,
    Zone,
)
from ..llm import PlanOutcome
from ..plan import calendar_weeks, load_workout_catalog, pre_plan_days
from . import charts, data
from . import format as f
from .components import model_label, show_interpretation, status_line, table, usd
from .theme import STATUS

_SHORT_Z5_M = 400
_STEP_NAMES = {"interpretation": "Interpretacja", "skeleton": "Szkielet"}
_TOKEN_COLUMNS = ("Tokeny wej.", "Tokeny wyj.", "Tokeny rozum.")


@dataclass
class PlanView:
    """Plan do wyświetlenia: świeżo utworzony albo odczytany z bazy."""

    plan_id: str
    goal: Goal
    model_key: str
    data_cutoff: date
    created_at: datetime | None
    status: str
    error: str | None
    interpretation: Interpretation | None
    check: InterpretationCheck | None
    skeleton: Skeleton | None
    skeleton_status: str | None
    skeleton_violations: list[Violation]
    skeleton_format_errors: list[str]
    week: Week | None
    week_status: str | None
    week_violations: list[Violation]
    week_format_errors: list[str]
    calls: list[CallRecord] = field(default_factory=list)


def _violations(raw: str | None) -> list[Violation]:
    return [Violation.model_validate(v) for v in json.loads(raw)] if raw else []


def _errors(raw: str | None) -> list[str]:
    return json.loads(raw) if raw else []


def view_from_record(record: PlanRecord, calls: list[CallRecord]) -> PlanView:
    def opt(model, raw):
        return model.model_validate_json(raw) if raw else None

    return PlanView(
        plan_id=record.id,
        goal=Goal.model_validate_json(record.goal_json),
        model_key=record.model_key,
        data_cutoff=record.data_cutoff,
        created_at=record.created_at,
        status=record.status,
        error=record.error,
        interpretation=opt(Interpretation, record.interpretation_json),
        check=opt(InterpretationCheck, record.interpretation_check_json),
        skeleton=opt(Skeleton, record.skeleton_json),
        skeleton_status=record.skeleton_status,
        skeleton_violations=_violations(record.skeleton_violations_json),
        skeleton_format_errors=_errors(record.skeleton_format_errors_json),
        week=opt(Week, record.week_json),
        week_status=record.week_status,
        week_violations=_violations(record.week_violations_json),
        week_format_errors=_errors(record.week_format_errors_json),
        calls=calls,
    )


def view_from_outcome(outcome: PlanOutcome, goal: Goal, model_key: str, cutoff: date) -> PlanView:
    return PlanView(
        plan_id=outcome.plan_id,
        goal=goal,
        model_key=model_key,
        data_cutoff=cutoff,
        created_at=None,
        status=outcome.status,
        error=outcome.error,
        interpretation=outcome.interpretation,
        check=outcome.interpretation_check,
        skeleton=outcome.skeleton,
        skeleton_status=outcome.skeleton_status,
        skeleton_violations=outcome.skeleton_violations,
        skeleton_format_errors=outcome.skeleton_format_errors,
        week=outcome.week,
        week_status=outcome.week_status,
        week_violations=outcome.week_violations,
        week_format_errors=outcome.week_format_errors,
        calls=outcome.calls,
    )


def goal_label(goal: Goal) -> str:
    target = f", cel {f.race_time(goal.target_time_s)}" if goal.target_time_s else ""
    return f"{goal.distance.label}, {f.date_pl(goal.race_date)}{target}"


@st.cache_data(show_spinner=False)
def _catalog_names() -> dict[WorkoutType, str]:
    catalog = load_workout_catalog(KNOWLEDGE_BASE_DIR / "workout_catalog.yaml")
    return {t: e.name for t, e in catalog.items()}


def _total(values: list):
    return None if any(v is None for v in values) else sum(values)


def _status_block(label: str, status: str | None, violations: list[Violation], errors: list[str]) -> None:
    if status is None:
        return
    st.markdown(f"**{label}:** {status_line(status)}")
    if status == "ok" and not violations and not errors:
        st.caption("Brak Naruszeń.")
    for v in sorted(violations, key=lambda v: v.kind is not RuleKind.HARD):
        s = STATUS["error" if v.kind is RuleKind.HARD else "warning"]
        st.markdown(f"- {s['icon']} **{s['label']} {v.rule_id}** ({v.location}): {v.message}")
    for e in errors:
        st.markdown(f"- {STATUS['error']['icon']} **Błąd formatu:** {e}")


# ---------------------------------------------------------------- Szkielet


def _show_skeleton(view: PlanView, pre_days: list[date]) -> None:
    skeleton = view.skeleton
    if skeleton is None:
        st.info("Brak Szkieletu.")
        _status_block("Szkielet", view.skeleton_status, view.skeleton_violations, view.skeleton_format_errors)
        return
    try:
        calendar = {c.number: c for c in calendar_weeks(view.data_cutoff, view.goal.race_date)}
    except ValueError:
        calendar = {}
    names = _catalog_names()
    table(
        pd.DataFrame(
            {
                "Tydzień": [w.number for w in skeleton.weeks],
                "Od": [f.date_pl(calendar[w.number].start) if w.number in calendar else None for w in skeleton.weeks],
                "Do": [f.date_pl(calendar[w.number].end) if w.number in calendar else None for w in skeleton.weeks],
                "Faza": [charts.PHASE_LABELS[w.phase] for w in skeleton.weeks],
                "Objętość [km]": [float(w.target_volume_km) for w in skeleton.weeks],
                "Jednostki kluczowe": [", ".join(names[t] for t in w.key_workouts) or None for w in skeleton.weeks],
            }
        )
    )
    fig = charts.skeleton_chart(skeleton, {n: c.start for n, c in calendar.items()})
    st.plotly_chart(fig, theme="streamlit", width="stretch", key="chart_skeleton")
    _status_block("Szkielet", view.skeleton_status, view.skeleton_violations, view.skeleton_format_errors)
    if pre_days:
        first, last = pre_days[0], pre_days[-1]
        span = f.date_pl(first) if first == last else f"{f.date_pl(first)}–{f.date_pl(last)}"
        st.markdown(f"**Dni przed Tygodniem 1 ({span}):** trening jak dotąd, spokojnie.")


# ---------------------------------------------------------------- Tydzień 1


def _hr_text(seg: PacedSegment) -> str:
    if seg.zone is Zone.Z5 and seg.distance_m < _SHORT_Z5_M:
        return "tętno nie nadąża"
    return f"{f.hr_range(seg.hr_low_bpm, seg.hr_high_bpm)} ud./min"


def _segment_text(seg: PacedSegment) -> str:
    pace = f.pace_range(seg.pace_fast_s_per_km, seg.pace_slow_s_per_km)
    return f"{seg.distance_m} m {seg.zone.value} {pace}, {_hr_text(seg)}"


def _block_prefix(workout: PacedWorkout, i: int) -> str:
    block = workout.blocks[i]
    easy = block.repeat == 1 and all(s.zone in (Zone.Z1, Zone.Z2) for s in block.segments)
    if len(workout.blocks) >= 2 and workout.type.is_quality and easy:
        if i == 0:
            return "Rozgrzewka: "
        if i == len(workout.blocks) - 1:
            return "Schłodzenie: "
    return ""


def _show_workout(workout: PacedWorkout, names: dict[WorkoutType, str]) -> None:
    st.markdown(
        f"**{f.date_pl(workout.date)}, {f.weekday_pl(workout.date)} · {names[workout.type]}** · "
        f"{f.km(workout.distance_km, 2)}, {workout.duration_min} min"
    )
    rows = []
    for i, block in enumerate(workout.blocks):
        inner = "; ".join(_segment_text(s) for s in block.segments)
        line = f"{block.repeat} × ({inner})" if block.repeat > 1 else inner
        st.markdown(f"- {_block_prefix(workout, i)}{line}")
        for s in block.segments:
            rows.append(
                {
                    "Powtórzenia": block.repeat,
                    "Dystans [m]": s.distance_m,
                    "Strefa": s.zone.value,
                    "Tempo": f.pace_range(s.pace_fast_s_per_km, s.pace_slow_s_per_km),
                    "Tętno [ud./min]": _hr_text(s).removesuffix(" ud./min"),
                    "Czas segmentu": f.race_time(s.duration_s),
                }
            )
    with st.expander("Segmenty"):
        table(pd.DataFrame(rows))


def _show_race(view: PlanView, week: Week) -> None:
    race = week.race
    day = race.date
    detail = ""
    if race.target_time_s is not None:
        kind = "cel" if view.goal.target_time_s else "prognoza"
        detail = f", {kind} {f.race_time(race.target_time_s)} ({f.pace(race.pace_s_per_km)})"
    st.markdown(f"**{f.date_pl(day)}, {f.weekday_pl(day)} · Start: {race.distance.label}{detail}**")


def _show_week(view: PlanView) -> None:
    week = view.week
    if week is None:
        if view.week_status == "pominięty":
            st.info(f"Tydzień 1 pominięty. {' '.join(view.week_format_errors)}".strip())
        else:
            st.info("Brak Tygodnia 1.")
            _status_block("Tydzień 1", view.week_status, view.week_violations, view.week_format_errors)
        return
    names = _catalog_names()
    by_date = {w.date: w for w in week.workouts}
    st.caption(f"{f.date_pl(week.start)}–{f.date_pl(week.end)} · Faza {charts.PHASE_LABELS[week.phase]}")
    for i in range(7):
        day = week.start + timedelta(days=i)
        if day in by_date:
            _show_workout(by_date[day], names)
        elif week.race is not None and week.race.date == day:
            _show_race(view, week)
        else:
            st.markdown(f"**{f.date_pl(day)}, {f.weekday_pl(day)} · Dzień wolny**")
    zones = [(z, round(week.zone_minutes.get(z, 0.0))) for z in Zone]
    minutes = ", ".join(f"{z.value} {m} min" for z, m in zones if m > 0)
    st.markdown(
        f"**Razem:** {f.km(week.distance_km, 2)}, {week.duration_min} min"
        + (f" · minuty w Strefach: {minutes}" if minutes else "")
    )
    _status_block("Tydzień 1", view.week_status, view.week_violations, view.week_format_errors)


# ---------------------------------------------------------------- koszt i czas


def _call_row(c: CallRecord) -> dict:
    hard = sum(v.kind is RuleKind.HARD for v in c.violations)
    errors = [*([c.parse_error] if c.parse_error else []), *c.format_errors]
    step = _STEP_NAMES.get(c.step) or (f"Tydzień {c.week_number}" if c.week_number else "Tydzień")
    return {
        "Krok": step,
        "Próba": c.attempt + 1,
        "Wersja promptu": c.prompt_version,
        "Tokeny wej.": c.input_tokens,
        "Tokeny wyj.": c.output_tokens,
        "Tokeny rozum.": c.reasoning_tokens,
        "Koszt [USD]": c.cost_usd,
        "Czas [s]": c.latency_ms / 1000,
        "Powód zakończenia": c.stop_reason,
        "Naruszenia twarde": hard,
        "Naruszenia miękkie": len(c.violations) - hard,
        "Błąd": "; ".join(errors) or None,
    }


def _show_cost(calls: list[CallRecord]) -> None:
    if not calls:
        st.info("Brak zapisanych wywołań modelu.")
        return
    cost = _total([c.cost_usd for c in calls])
    cols = st.columns(5)
    cols[0].metric("Koszt [USD]", usd(cost))
    cols[1].metric("Czas [s]", f.num(sum(c.latency_ms for c in calls) / 1000, 1))
    for col, label, attr in (
        (cols[2], "Tokeny wejścia", "input_tokens"),
        (cols[3], "Tokeny wyjścia", "output_tokens"),
        (cols[4], "Tokeny rozumowania", "reasoning_tokens"),
    ):
        col.metric(label, f.integer(_total([getattr(c, attr) for c in calls])))
    if cost is None:
        st.caption("Suma kosztu jest pusta, bo przynajmniej jedno wywołanie nie ma liczby tokenów.")
    st.caption("Próba 1 to pierwsza odpowiedź modelu, kolejne próby to Poprawki.")
    calls_df = pd.DataFrame([_call_row(c) for c in calls]).astype({c: "Int64" for c in _TOKEN_COLUMNS})
    calls_df["Koszt [USD]"] = calls_df["Koszt [USD]"].astype(float)
    table(calls_df, precision={"Koszt [USD]": 4})


# ---------------------------------------------------------------- całość


def show_plan(view: PlanView) -> None:
    st.divider()
    st.header("Plan")
    when = f" · zapisano {f.datetime_pl(view.created_at.astimezone(data.LOCAL_TZ))}" if view.created_at else ""
    st.caption(
        f"Cel: {goal_label(view.goal)} · Data odcięcia {f.date_pl(view.data_cutoff)} · "
        f"model {model_label(view.model_key)}{when}"
    )
    st.markdown(f"**Wynik:** {status_line(view.status)}")
    if view.error:
        st.error(f"Błąd dostawcy modelu: {view.error}")
    try:
        pre_days = pre_plan_days(view.data_cutoff, calendar_weeks(view.data_cutoff, view.goal.race_date))
    except ValueError:
        pre_days = []
    skeleton_tab, week_tab, interp_tab, cost_tab = st.tabs(["Szkielet", "Tydzień 1", "Interpretacja", "Koszt i czas"])
    with skeleton_tab:
        _show_skeleton(view, pre_days)
    with week_tab:
        _show_week(view)
    with interp_tab:
        if view.interpretation is None:
            st.info("Brak Interpretacji (pominięta albo nieudana).")
        else:
            show_interpretation(view.interpretation, view.check)
    with cost_tab:
        _show_cost(view.calls)
