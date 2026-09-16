"""Synchronizacja historii biegowej autora z Garmin Connect: pliki FIT i wartości wyliczone przez Garmina."""

import os
import sqlite3
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from uuid import uuid4

from garminconnect import Garmin
from garminconnect.exceptions import (
    GarminConnectAuthenticationError,
    GarminConnectConnectionError,
    GarminConnectNotFoundError,
    GarminConnectTooManyRequestsError,
)
from pydantic import BaseModel, Field

from ..domain import ActivitySource, GarminMetric, GarminMetricKind
from ..storage import (
    find_duplicate,
    get_athlete,
    known_garmin_activity_ids,
    last_garmin_metric_date,
    record_sync,
    save_activity,
    save_garmin_metrics,
)
from .fit import FitParseError, extract_fit_from_zip, parse_fit

TOKENSTORE = "~/.garminconnect"

RUNNING_TYPE_KEYS = frozenset(
    {"running", "street_running", "track_running", "treadmill_running", "trail_running", "indoor_running"}
)

# Zapytanie o przewidywania wyścigowe obejmuje najwyżej rok.
_CHUNK = timedelta(days=364)

_MIN_DURATION_S = 60
_MIN_DISTANCE_M = 100

_RACE_FIELDS = {
    "time5K": GarminMetricKind.RACE_PRED_5K,
    "time10K": GarminMetricKind.RACE_PRED_10K,
    "timeHalfMarathon": GarminMetricKind.RACE_PRED_HM,
    "timeMarathon": GarminMetricKind.RACE_PRED_M,
}


class GarminSyncError(RuntimeError):
    """Synchronizacja z Garmin Connect nie mogła się rozpocząć."""


class GarminAuthError(GarminSyncError):
    """Logowanie tokenami do Garmin Connect nie powiodło się."""

    def __init__(self) -> None:
        super().__init__(
            "Nie udało się zalogować do Garmin Connect zapisanymi tokenami. "
            "Uruchom w terminalu: poetry run python -m llmrunplanner.ingest.garmin_login"
        )


class SyncReport(BaseModel):
    new: int = Field(default=0, description="Liczba nowo zapisanych Aktywności.")
    duplicates: int = Field(default=0, description="Liczba Aktywności pominiętych jako duplikaty.")
    skipped_too_short: int = Field(default=0, description="Liczba pominiętych Aktywności prawie pustych.")
    skipped_not_running: int = Field(default=0, description="Liczba pominiętych Aktywności niebędących biegiem.")
    broken: int = Field(default=0, description="Liczba uszkodzonych plików FIT.")
    without_hr: int = Field(default=0, description="Liczba zapisanych Aktywności bez tętna.")
    garmin_metrics: int = Field(default=0, description="Liczba zapisanych wartości wyliczonych przez Garmina.")
    errors: list[str] = Field(default_factory=list, description="Komunikaty o błędach.")
    complete: bool = Field(default=False, description="Czy synchronizacja objęła całą historię i wszystkie wartości.")


def sync_garmin(
    conn: sqlite3.Connection,
    athlete_id: str,
    fit_dir: Path,
    *,
    progress: Callable[[int, int], None] | None = None,
    max_new: int | None = None,
) -> SyncReport:
    """Pobiera nowe biegi (oryginalne pliki FIT) i wartości Garmina do bazy; zwraca raport."""
    athlete = get_athlete(conn, athlete_id)
    if athlete is None or athlete.source != ActivitySource.GARMIN:
        raise ValueError(f"Biegacz '{athlete_id}' nie istnieje albo nie pochodzi z Garmin Connect.")

    api = Garmin()
    try:
        api.login(tokenstore=TOKENSTORE)
        items = api.get_activities_by_date("2000-01-01", None, None, "asc")
    except GarminConnectAuthenticationError as exc:
        raise GarminAuthError() from exc
    except GarminConnectTooManyRequestsError as exc:
        raise GarminSyncError("Garmin ograniczył liczbę zapytań, spróbuj później.") from exc
    except GarminConnectConnectionError as exc:
        raise GarminSyncError("Brak połączenia z Garmin Connect.") from exc

    report = SyncReport()
    runs = []
    for item in items:
        is_run = (item.get("activityType") or {}).get("typeKey") in RUNNING_TYPE_KEYS
        if is_run and not item.get("manualActivity"):
            runs.append(item)
        else:
            report.skipped_not_running += 1

    known = known_garmin_activity_ids(conn, athlete_id)
    todo = [r for r in runs if str(r["activityId"]) not in known]
    todo.sort(key=lambda r: r["startTimeLocal"])
    downloaded_all = _download_activities(api, conn, athlete_id, fit_dir, todo, report, progress, max_new)

    metrics_ok = True
    if runs:
        first_day = date.fromisoformat(min(r["startTimeLocal"] for r in runs)[:10])
        metrics_ok = _sync_metrics(api, conn, athlete_id, first_day, report)
    report.complete = downloaded_all and metrics_ok

    record_sync(conn, athlete_id, datetime.now(UTC), report.model_dump())
    return report


def _download_activities(
    api: Garmin,
    conn: sqlite3.Connection,
    athlete_id: str,
    fit_dir: Path,
    todo: list[dict],
    report: SyncReport,
    progress: Callable[[int, int], None] | None,
    max_new: int | None,
) -> bool:
    """Zwraca True, gdy przetworzono wszystkie Aktywności z listy."""
    fit_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    total = len(todo) if max_new is None else min(len(todo), max_new)
    for done, item in enumerate(todo, start=1):
        if max_new is not None and report.new >= max_new:
            return False
        garmin_id = str(item["activityId"])
        path = fit_dir / f"{garmin_id}.fit"
        try:
            if path.exists():
                data = path.read_bytes()
            else:
                raw = api.download_activity(garmin_id, dl_fmt=Garmin.ActivityDownloadFormat.ORIGINAL)
                data = extract_fit_from_zip(raw)
                _write_atomic(path, data)
            parsed = parse_fit(
                data,
                activity_id=uuid4().hex,
                athlete_id=athlete_id,
                source=ActivitySource.GARMIN,
                garmin_activity_id=garmin_id,
            )
        except GarminConnectTooManyRequestsError:
            report.errors.append("Garmin zwrócił błąd 429 (zbyt wiele zapytań); synchronizację przerwano.")
            return False
        except GarminConnectNotFoundError as exc:
            report.errors.append(f"Aktywność {garmin_id}: nie znaleziono w Garmin Connect ({exc})")
        except GarminConnectConnectionError:
            report.errors.append(f"Aktywność {garmin_id}: brak połączenia z Garmin Connect; synchronizację przerwano.")
            return False
        except FitParseError as exc:
            report.broken += 1
            report.errors.append(f"Aktywność {garmin_id}: uszkodzony plik FIT ({exc})")
        except Exception as exc:
            report.errors.append(f"Aktywność {garmin_id}: pobieranie nie powiodło się ({exc})")
        else:
            if parsed is None:
                report.skipped_not_running += 1
            elif parsed[0].duration_s < _MIN_DURATION_S or parsed[0].distance_m < _MIN_DISTANCE_M:
                report.skipped_too_short += 1
            else:
                activity, samples = parsed
                if find_duplicate(conn, athlete_id, activity.start_time) is not None:
                    report.duplicates += 1
                else:
                    save_activity(conn, activity, samples)
                    report.new += 1
                    if not activity.has_hr:
                        report.without_hr += 1
        if progress is not None:
            progress(min(done, total), total)
    return True


def _sync_metrics(
    api: Garmin, conn: sqlite3.Connection, athlete_id: str, first_day: date, report: SyncReport
) -> bool:
    """Zapisuje wartości Garmina po kompletnych porcjach; zwraca True, gdy doszło do dziś bez błędu."""
    last = last_garmin_metric_date(conn, athlete_id)
    # Zakładka 30 dni: wartości bywają dopisywane z opóźnieniem, a zapis jest idempotentny (upsert).
    start = max(first_day, last - timedelta(days=30)) if last else first_day
    today = date.today()
    families = {
        "VO2max": _vo2max,
        "próg mleczanowy": _lactate_threshold,
        "prognozy czasów": _race_predictions,
        "tętno spoczynkowe": _resting_hr,
    }
    chunk_start = start
    while chunk_start <= today:
        chunk_end = min(chunk_start + _CHUNK, today)
        metrics: list[GarminMetric] = []
        for name, fetch in families.items():
            try:
                metrics += fetch(api, athlete_id, chunk_start.isoformat(), chunk_end.isoformat())
            except GarminConnectTooManyRequestsError:
                report.errors.append(f"{name}: błąd 429 (zbyt wiele zapytań); wartości Garmina niekompletne.")
                return False
            except Exception as exc:
                report.errors.append(f"{name} {chunk_start}..{chunk_end}: {exc}")
                return False
        report.garmin_metrics += save_garmin_metrics(conn, metrics)
        chunk_start = chunk_end + timedelta(days=1)
    return True


def _write_atomic(path: Path, data: bytes) -> None:
    tmp = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        os.replace(tmp, path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


def _vo2max(api: Garmin, athlete_id: str, start: str, end: str) -> list[GarminMetric]:
    out = []
    for row in api.get_max_metrics_range(start, end, "daily") or []:
        generic = row.get("generic") or {}
        value = generic.get("vo2MaxPreciseValue")
        if value is not None and generic.get("calendarDate"):
            out.append(_metric(athlete_id, generic["calendarDate"], GarminMetricKind.VO2MAX, value))
    return out


def _lactate_threshold(api: Garmin, athlete_id: str, start: str, end: str) -> list[GarminMetric]:
    data = api.get_lactate_threshold(latest=False, start_date=start, end_date=end) or {}
    out = []
    for key, kind in (("heart_rate", GarminMetricKind.LT_HR), ("speed", GarminMetricKind.LT_SPEED)):
        for row in data.get(key) or []:
            if row.get("value") is not None and row.get("from"):
                out.append(_metric(athlete_id, row["from"], kind, row["value"]))
    return out


def _race_predictions(api: Garmin, athlete_id: str, start: str, end: str) -> list[GarminMetric]:
    out = []
    for row in api.get_race_predictions(start, end, "daily") or []:
        for field, kind in _RACE_FIELDS.items():
            if row.get(field) is not None and row.get("calendarDate"):
                out.append(_metric(athlete_id, row["calendarDate"], kind, row[field]))
    return out


def _resting_hr(api: Garmin, athlete_id: str, start: str, end: str) -> list[GarminMetric]:
    return [
        _metric(athlete_id, row["calendarDate"], GarminMetricKind.RESTING_HR, row["value"])
        for row in api.get_rhr_daily(start, end)
        if row.get("calendarDate")
    ]


def _metric(athlete_id: str, day: str, kind: GarminMetricKind, value: float) -> GarminMetric:
    return GarminMetric(athlete_id=athlete_id, date=date.fromisoformat(day[:10]), kind=kind, value=float(value))
