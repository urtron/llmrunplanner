"""Wczytywanie danych dla ekranów: połączenie z bazą otwierane na użycie, wyniki obliczeń w cache."""

import contextlib
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import streamlit as st

from ..config import load_settings
from ..domain import Activity, Athlete, AthleteMetrics, HistorySummary, PlanRecord
from ..metrics import compute_athlete_metrics
from ..storage import (
    connect,
    get_athlete,
    last_sync_at,
    list_athletes,
    load_activities,
    load_garmin_metrics,
    load_llm_calls,
    load_plans,
    load_samples,
)
from ..summary import build_history_summary

LOCAL_TZ = ZoneInfo("Europe/Warsaw")


@dataclass(frozen=True)
class AthleteOverview:
    athlete: Athlete
    activity_count: int
    first_date: date | None
    last_date: date | None
    synced_at: datetime | None  # czas lokalny
    sync_complete: bool


def _db_path() -> str:
    return str(load_settings().db_path)


def invalidate() -> None:
    """Po zapisie profilu albo synchronizacji: zmieniają się wszystkie dane."""
    st.cache_data.clear()


def invalidate_plans() -> None:
    """Po zapisie Planu: Wskaźniki zostają w cache, odświeża się tylko lista Planów i ich koszty."""
    _plans.clear()
    _plan_costs.clear()


def _local(dt: datetime | None) -> datetime | None:
    return None if dt is None else dt.astimezone(LOCAL_TZ)


@st.cache_data(show_spinner=False)
def _athletes(db_path: str) -> list[Athlete]:
    with contextlib.closing(connect(Path(db_path))) as conn:
        return list_athletes(conn)


def athletes() -> list[Athlete]:
    return _athletes(_db_path())


@st.cache_data(show_spinner=False)
def _overview(db_path: str) -> list[AthleteOverview]:
    rows = []
    with contextlib.closing(connect(Path(db_path))) as conn:
        for a in list_athletes(conn):
            acts = load_activities(conn, a.id, date.max)
            any_sync = last_sync_at(conn, a.id)
            complete_sync = last_sync_at(conn, a.id, complete_only=True)
            rows.append(
                AthleteOverview(
                    athlete=a,
                    activity_count=len(acts),
                    first_date=min((x.local_date for x in acts), default=None),
                    last_date=max((x.local_date for x in acts), default=None),
                    synced_at=_local(any_sync),
                    sync_complete=any_sync is not None and any_sync == complete_sync,
                )
            )
    return rows


def overview() -> list[AthleteOverview]:
    return _overview(_db_path())


def default_cutoff(athlete_id: str) -> date:
    """Lokalna data ostatniej pełnej synchronizacji; bez niej dzisiaj."""
    with contextlib.closing(connect(load_settings().db_path)) as conn:
        synced = last_sync_at(conn, athlete_id, complete_only=True)
    return _local(synced).date() if synced else datetime.now(LOCAL_TZ).date()


@st.cache_data(show_spinner="Liczenie Wskaźników…")
def _athlete_metrics(
    db_path: str, athlete_id: str, cutoff_iso: str, hr_max: int | None, hr_rest: int | None, stamp: str
) -> tuple[Athlete, list[Activity], AthleteMetrics | None, HistorySummary | None]:
    # hr_max, hr_rest i stamp (ostatnia synchronizacja) tylko różnicują klucz cache.
    cutoff = date.fromisoformat(cutoff_iso)
    with contextlib.closing(connect(Path(db_path))) as conn:
        athlete = get_athlete(conn, athlete_id)
        if athlete is None:
            raise ValueError("Nie ma takiego Biegacza.")
        activities = load_activities(conn, athlete_id, cutoff)
        if not activities:
            return athlete, activities, None, None
        samples = {a.id: load_samples(conn, a.id, cutoff) for a in activities}
        garmin = load_garmin_metrics(conn, athlete_id, cutoff)
    metrics = compute_athlete_metrics(athlete, activities, samples, garmin, cutoff)
    summary = build_history_summary(athlete, activities, metrics, metrics.daily, cutoff)
    return athlete, activities, metrics, summary


def athlete_metrics(
    athlete_id: str, cutoff: date
) -> tuple[Athlete, list[Activity], AthleteMetrics | None, HistorySummary | None]:
    """(Biegacz, Aktywności sprzed Daty odcięcia, Wskaźniki, Podsumowanie historii); Wskaźniki i
    Podsumowanie to None, gdy przed Datą odcięcia nie ma Aktywności."""
    db_path = _db_path()
    with contextlib.closing(connect(load_settings().db_path)) as conn:
        athlete = get_athlete(conn, athlete_id)
        synced = last_sync_at(conn, athlete_id)
    if athlete is None:
        raise ValueError("Nie ma takiego Biegacza.")
    return _athlete_metrics(
        db_path,
        athlete_id,
        cutoff.isoformat(),
        athlete.hr_max_override,
        athlete.hr_rest_override,
        synced.isoformat() if synced else "",
    )


@st.cache_data(show_spinner=False)
def _plans(db_path: str, athlete_id: str) -> list[PlanRecord]:
    with contextlib.closing(connect(Path(db_path))) as conn:
        return load_plans(conn, athlete_id)


def plans(athlete_id: str) -> list[PlanRecord]:
    return _plans(_db_path(), athlete_id)


def _total(values: list[float | None]) -> float | None:
    return None if any(v is None for v in values) else sum(values)


@st.cache_data(show_spinner=False)
def _plan_costs(db_path: str, run_ids: tuple[str, ...]) -> dict[str, float | None]:
    with contextlib.closing(connect(Path(db_path))) as conn:
        return {run_id: _total([c.cost_usd for c in load_llm_calls(conn, run_id)]) for run_id in run_ids}


def plan_costs(run_ids: tuple[str, ...]) -> dict[str, float | None]:
    """Łączny koszt wywołań modelu dla każdego przebiegu; brak, gdy któreś wywołanie nie ma kosztu."""
    return _plan_costs(_db_path(), run_ids)
