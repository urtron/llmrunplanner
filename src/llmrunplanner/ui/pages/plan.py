"""Ekran „Cel i Plan”: Cel, Ankieta zdrowotna, Bramka bezpieczeństwa, wybór modelu, Plan i jego historia."""

import contextlib
import traceback
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import streamlit as st
from pydantic import ValidationError

from llmrunplanner.config import load_settings
from llmrunplanner.domain import ActivitySource, Distance, GateProposal, GateResult, GateStatus, Goal, weeks_until_race
from llmrunplanner.llm import DEFAULT_MODEL, MODELS, create_plan
from llmrunplanner.plan import calendar_weeks, pre_plan_days
from llmrunplanner.safety import HEALTH_QUESTIONS, MEDICAL_DISCLAIMER, run_gate
from llmrunplanner.safety.params import PLAN_MAX_WEEKS, PLAN_MIN_WEEKS
from llmrunplanner.storage import connect, get_plan, load_llm_calls
from llmrunplanner.ui import data, state
from llmrunplanner.ui import format as f
from llmrunplanner.ui.components import model_label, status_label, status_line, table
from llmrunplanner.ui.plan_view import goal_label, show_plan, view_from_outcome, view_from_record
from llmrunplanner.ui.theme import STATUS

_DISTANCE = state.PLAN_DISTANCE_KEY
_RACE_DATE = state.PLAN_RACE_DATE_KEY
_TARGET = state.PLAN_TARGET_KEY
_MODEL = state.PLAN_MODEL_KEY
_HISTORY_PICK = state.PLAN_HISTORY_PICK_KEY
_GATE = "plan_gate"
_RERUN_GATE = "plan_rerun_gate"
_DEFAULTS_FOR = "plan_defaults_for"
_VIEW = "plan_view"
_HISTORY_ERROR = "plan_history_error"
_DEFAULT_WEEKS = 12
_YES, _NO = "Tak", "Nie"


def _price(key: str) -> str:
    spec = MODELS[key]
    return f"{f.num(spec.price_in_usd_per_mtok, 2)}/{f.num(spec.price_out_usd_per_mtok, 2)} USD za 1 mln tokenów"


# ---------------------------------------------------------------- formularz Celu


def _reset_defaults(athlete_id: str, cutoff: date) -> None:
    """Wartości początkowe formularza; po zmianie Daty odcięcia wybrana data startu zostaje, jeśli nadal daje
    Plan o dopuszczalnej długości."""
    if _DISTANCE not in st.session_state:
        st.session_state[_DISTANCE] = Distance.K10
    previous = st.session_state.get(_DEFAULTS_FOR)
    if previous == (athlete_id, cutoff) and _RACE_DATE in st.session_state:
        return
    if previous is None or previous[0] != athlete_id:
        st.session_state.pop(_VIEW, None)
        st.session_state.pop(_HISTORY_PICK, None)
        for q in HEALTH_QUESTIONS:
            st.session_state[state.question_key(q.id)] = None
    race_date = st.session_state.get(_RACE_DATE)
    if race_date is None or not PLAN_MIN_WEEKS <= weeks_until_race(cutoff, race_date) <= PLAN_MAX_WEEKS:
        st.session_state[_RACE_DATE] = cutoff + timedelta(days=7 * _DEFAULT_WEEKS - 1)
    st.session_state[_DEFAULTS_FOR] = (athlete_id, cutoff)
    st.session_state.pop(_GATE, None)


def _accept(proposal: GateProposal) -> None:
    if proposal.kind == "target_time" and proposal.target_time_s is not None:
        st.session_state[_TARGET] = f.race_time(proposal.target_time_s)
    elif proposal.race_date is not None:
        st.session_state[_RACE_DATE] = proposal.race_date
    st.session_state[_RERUN_GATE] = True


def _goal_form(cutoff: date) -> Goal | None:
    st.subheader("Cel")
    c1, c2, c3 = st.columns(3)
    distance = c1.selectbox("Dystans", list(Distance), format_func=lambda d: d.label[0].upper() + d.label[1:], key=_DISTANCE)
    race_date = c2.date_input("Data startu", min_value=cutoff + timedelta(days=1), format="DD.MM.YYYY", key=_RACE_DATE)
    target_text = c3.text_input("Czas docelowy (opcjonalnie)", placeholder="np. 44:00 albo 1:45:00", key=_TARGET)

    target_s = None
    if target_text.strip():
        try:
            target_s = f.parse_time(target_text)
        except ValueError as e:
            st.error(str(e))
            return None
    goal = Goal(distance=distance, race_date=race_date, target_time_s=target_s)

    weeks = goal.weeks_from(cutoff)
    if weeks >= 1:
        skipped = len(pre_plan_days(cutoff, calendar_weeks(cutoff, race_date)))
        extra = f" Dni przed Tygodniem 1: {skipped}." if skipped else ""
        st.caption(f"Do startu: {f.weeks(weeks)} od Daty odcięcia ({f.date_pl(cutoff)}).{extra}")
    else:
        st.caption("Między Datą odcięcia a startem nie mieści się pełny Tydzień.")
    return goal


# ---------------------------------------------------------------- Ankieta i Bramka


def _questionnaire() -> dict[str, bool] | None:
    st.subheader("Ankieta zdrowotna")
    st.caption(MEDICAL_DISCLAIMER)
    answers: dict[str, bool] = {}
    for q in HEALTH_QUESTIONS:
        choice = st.radio(q.text, [_YES, _NO], index=None, horizontal=True, key=state.question_key(q.id))
        if choice is not None:
            answers[q.id] = choice == _YES
    if len(answers) < len(HEALTH_QUESTIONS):
        st.caption("Odpowiedz na wszystkie pytania, aby sprawdzić Bramkę bezpieczeństwa.")
        return None
    return answers


def _signature(athlete_id: str, cutoff: date, goal: Goal, answers: dict[str, bool]) -> tuple:
    return (athlete_id, cutoff, goal.distance, goal.race_date, goal.target_time_s, tuple(sorted(answers.items())))


def _gate_section(athlete_id, cutoff, goal, answers, metrics, summary) -> GateResult | None:
    """Wynik Bramki dla bieżących danych wejściowych albo None, gdy jeszcze jej nie sprawdzono."""
    st.subheader("Bramka bezpieczeństwa")
    ready = goal is not None and answers is not None
    rerun = st.session_state.pop(_RERUN_GATE, False)
    clicked = st.button("Sprawdź Bramkę", disabled=not ready)
    if ready and (clicked or rerun):
        st.session_state[_GATE] = {
            "sig": _signature(athlete_id, cutoff, goal, answers),
            "result": run_gate(answers, goal, summary, metrics),
        }
    stored = st.session_state.get(_GATE)
    if not ready or stored is None:
        return None
    if stored["sig"] != _signature(athlete_id, cutoff, goal, answers):
        st.info("Dane wejściowe zmieniły się od ostatniego sprawdzenia: sprawdź Bramkę ponownie.")
        return None
    gate: GateResult = stored["result"]
    _show_gate(gate, goal)
    return gate


_GATE_STYLE = {
    GateStatus.OK: (STATUS["ok"], "Plan można tworzyć"),
    GateStatus.WARN: (STATUS["warning"], "Plan można tworzyć, ale są ostrzeżenia"),
    GateStatus.STOP: (STATUS["error"], "Plan nie powstanie"),
}


def _show_gate(gate: GateResult, goal: Goal) -> None:
    style, verdict = _GATE_STYLE[gate.status]
    st.markdown(f"{style['icon']} **{style['label']}: {verdict}** · {f.weeks(gate.weeks)}")
    if gate.predicted_time_s is not None:
        pace = gate.predicted_time_s / goal.distance.km
        st.markdown(f"Prognoza czasu na {goal.distance.label}: **{f.race_time(gate.predicted_time_s)}** ({f.pace(pace)})")
    else:
        st.caption("Prognozy czasu nie da się policzyć.")
    for reason in gate.reasons:
        st.markdown(f"- {STATUS['error']['icon']} {reason}")
    for warning in gate.warnings:
        st.markdown(f"- {STATUS['warning']['icon']} {warning}")
    for i, proposal in enumerate(gate.proposals):
        st.markdown(f"Propozycja: {proposal.text}")
        st.button("Przyjmij propozycję", key=f"plan_proposal_{i}", on_click=_accept, args=(proposal,))


# ---------------------------------------------------------------- tworzenie Planu


def _model_section(is_author: bool) -> str:
    st.subheader("Model")
    keys = [k for k, s in MODELS.items() if s.provider == "anthropic"]
    if st.session_state.get(_MODEL) not in keys:
        st.session_state[_MODEL] = DEFAULT_MODEL
    model = st.selectbox("Model językowy", keys, format_func=lambda k: f"{MODELS[k].label} ({_price(k)})", key=_MODEL)
    blocked = ", ".join(s.label for s in MODELS.values() if s.provider == "openrouter")
    if blocked:
        reasons = [
            "OpenRouter niedostępny w tej konfiguracji"
            if load_settings().openrouter_api_key
            else "brak klucza OpenRouter w pliku .env"
        ]
        if not is_author:
            reasons.append("modele przez OpenRouter są dopuszczone tylko dla danych autora")
        st.caption(f"Niedostępne: {blocked}. Powód: {'; '.join(reasons)}.")
    return model


def _create(athlete_id: str, cutoff: date, goal: Goal, answers: dict[str, bool], model_key: str) -> None:
    st.session_state.pop(_HISTORY_PICK, None)  # wybór z historii nie może wskazywać poprzedniego Planu
    message, details = None, None
    with st.status("Tworzenie Planu…", expanded=True) as status:

        def progress(text: str) -> None:
            status.update(label=f"Tworzenie Planu: {text}")
            status.write(text)

        try:
            with contextlib.closing(connect(load_settings().db_path)) as conn:
                outcome = create_plan(conn, athlete_id, goal, answers, cutoff, model_key, progress)
        except ValueError as e:
            message = str(e)
        except Exception as e:
            message, details = f"Nieoczekiwany błąd: {e}", traceback.format_exc()
        if message is None:
            data.invalidate_plans()
            status.update(
                label=f"Plan: {status_label(outcome.status)}",
                state="complete" if outcome.status == "ok" else "error",
                expanded=False,
            )
        else:
            status.update(label="Plan nie powstał", state="error")
    if message is not None:
        st.error(message)
        if details:
            with st.expander("Szczegóły błędu"):
                st.code(details, language=None)
        return
    st.session_state[_VIEW] = view_from_outcome(outcome, goal, model_key, cutoff)


# ---------------------------------------------------------------- historia


def _load_saved(db_path: str, ids_by_label: dict[str, str]) -> None:
    plan_id = ids_by_label.get(st.session_state.get(_HISTORY_PICK))
    if plan_id is None:
        return
    try:
        with contextlib.closing(connect(Path(db_path))) as conn:
            record = get_plan(conn, plan_id)
            if record is None:
                return
            st.session_state[_VIEW] = view_from_record(record, load_llm_calls(conn, record.run_id))
    except (ValidationError, ValueError):
        st.session_state.pop(_VIEW, None)
        st.session_state[_HISTORY_ERROR] = True


def _history(athlete_id: str) -> None:
    st.divider()
    st.subheader("Historia Planów")
    records = data.plans(athlete_id)
    if not records:
        st.caption("Ten Biegacz nie ma jeszcze zapisanych Planów.")
        return
    db_path = str(load_settings().db_path)
    costs = data.plan_costs(tuple(r.run_id for r in records))
    rows, ids_by_label = [], {}
    for r in records:
        try:
            goal_text = goal_label(Goal.model_validate_json(r.goal_json))
        except ValidationError:
            goal_text = "–"
        created = r.created_at.astimezone(data.LOCAL_TZ)
        label = f"{f.date_pl(created)} {created:%H:%M:%S} · {goal_text} · {model_label(r.model_key)} · {status_label(r.status)}"
        base, n = label, 2
        while label in ids_by_label:  # dwa Plany zapisane w tej samej sekundzie
            label, n = f"{base} ({n})", n + 1
        ids_by_label[label] = r.id
        rows.append(
            {
                "Utworzono": f"{f.date_pl(created)} {created:%H:%M:%S}",
                "Cel": goal_text,
                "Model": model_label(r.model_key),
                "Status": status_line(r.status),
                "Koszt [USD]": costs.get(r.run_id),
            }
        )
    history = pd.DataFrame(rows)
    history["Koszt [USD]"] = history["Koszt [USD]"].astype(float)
    table(history, precision={"Koszt [USD]": 4})
    st.selectbox(
        "Pokaż zapisany Plan",
        list(ids_by_label),
        index=None,
        placeholder="Wybierz Plan",
        key=_HISTORY_PICK,
        on_change=_load_saved,
        args=(db_path, ids_by_label),
    )
    if st.session_state.pop(_HISTORY_ERROR, False):
        st.warning("Zapisany Plan ma nieczytelny format.")


# ---------------------------------------------------------------- strona


def main() -> None:
    st.title("Cel i Plan")
    athlete_id, cutoff = state.athlete_id(), state.cutoff()
    if athlete_id is None or cutoff is None:
        st.info("Wybierz Biegacza w panelu bocznym albo dodaj profil na ekranie „Biegacz”.")
        return
    athlete, _, metrics, summary = data.athlete_metrics(athlete_id, cutoff)
    if metrics is None or summary is None:
        st.info("Przed Datą odcięcia nie ma Aktywności tego Biegacza, więc nie da się utworzyć Planu.")
        return

    _reset_defaults(athlete_id, cutoff)
    goal = _goal_form(cutoff)
    answers = _questionnaire()
    gate = _gate_section(athlete_id, cutoff, goal, answers, metrics, summary)
    model = _model_section(athlete.source is ActivitySource.GARMIN)

    can_create = gate is not None and gate.status is not GateStatus.STOP
    if st.button("Utwórz Plan", type="primary", disabled=not can_create) and can_create:
        _create(athlete_id, cutoff, goal, answers, model)
    if (view := st.session_state.get(_VIEW)) is not None:
        show_plan(view)
    _history(athlete_id)


main()
