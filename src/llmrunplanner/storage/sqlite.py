import json
import sqlite3
import uuid
from collections.abc import Iterable
from datetime import UTC, date, datetime
from pathlib import Path

from ..domain import (
    Activity,
    ActivitySource,
    Athlete,
    CallRecord,
    GarminMetric,
    GarminMetricKind,
    PlanRecord,
    Samples,
    Sex,
    SubSport,
    Violation,
)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS athlete (
    id TEXT PRIMARY KEY,
    label TEXT NOT NULL,
    source TEXT NOT NULL,
    sex TEXT NOT NULL,
    birth_year INTEGER NOT NULL,
    hr_rest_override INTEGER,
    hr_max_override INTEGER
);
CREATE TABLE IF NOT EXISTS activity (
    id TEXT PRIMARY KEY,
    athlete_id TEXT NOT NULL REFERENCES athlete(id) ON DELETE CASCADE,
    source TEXT NOT NULL,
    start_time INTEGER NOT NULL,
    utc_offset_s INTEGER NOT NULL,
    local_date TEXT NOT NULL,
    duration_s INTEGER NOT NULL,
    distance_m REAL NOT NULL,
    sub_sport TEXT NOT NULL,
    has_hr INTEGER NOT NULL,
    has_gps INTEGER NOT NULL,
    garmin_activity_id TEXT,
    file_hash TEXT
);
CREATE INDEX IF NOT EXISTS idx_activity_start ON activity(athlete_id, start_time);
CREATE INDEX IF NOT EXISTS idx_activity_local_date ON activity(athlete_id, local_date);
CREATE TABLE IF NOT EXISTS sample (
    activity_id TEXT NOT NULL REFERENCES activity(id) ON DELETE CASCADE,
    i INTEGER NOT NULL,
    t_s INTEGER NOT NULL,
    hr INTEGER,
    speed_mps REAL,
    distance_m REAL,
    altitude_m REAL,
    cadence INTEGER,
    PRIMARY KEY (activity_id, i)
) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS garmin_metric (
    athlete_id TEXT NOT NULL REFERENCES athlete(id) ON DELETE CASCADE,
    date TEXT NOT NULL,
    kind TEXT NOT NULL,
    value REAL NOT NULL,
    PRIMARY KEY (athlete_id, date, kind)
);
CREATE TABLE IF NOT EXISTS sync_run (
    athlete_id TEXT NOT NULL REFERENCES athlete(id) ON DELETE CASCADE,
    synced_at TEXT NOT NULL,
    report_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS plan (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    athlete_id TEXT NOT NULL REFERENCES athlete(id) ON DELETE CASCADE,
    data_cutoff TEXT NOT NULL,
    as_of TEXT NOT NULL,
    goal_json TEXT NOT NULL,
    model_key TEXT NOT NULL,
    status TEXT NOT NULL,
    error TEXT,
    gate_json TEXT NOT NULL,
    interpretation_json TEXT,
    interpretation_check_json TEXT,
    skeleton_json TEXT,
    skeleton_status TEXT,
    skeleton_violations_json TEXT,
    skeleton_format_errors_json TEXT,
    week_json TEXT,
    week_status TEXT,
    week_violations_json TEXT,
    week_format_errors_json TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_plan_athlete ON plan(athlete_id, created_at);
CREATE TABLE IF NOT EXISTS llm_call (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    plan_id TEXT,
    athlete_id TEXT NOT NULL REFERENCES athlete(id) ON DELETE CASCADE,
    step TEXT NOT NULL,
    week_number INTEGER,
    attempt INTEGER NOT NULL,
    model_key TEXT NOT NULL,
    model_id TEXT NOT NULL,
    prompt_version TEXT NOT NULL,
    schema_hash TEXT NOT NULL,
    summary_hash TEXT NOT NULL,
    context_hash TEXT NOT NULL,
    as_of TEXT NOT NULL,
    input_tokens INTEGER,
    output_tokens INTEGER,
    reasoning_tokens INTEGER,
    cost_usd REAL,
    latency_ms INTEGER NOT NULL,
    stop_reason TEXT,
    output_json TEXT,
    parse_error TEXT,
    format_errors_json TEXT NOT NULL,
    violations_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_llm_call_run ON llm_call(run_id, created_at);
"""

_ACTIVITY_COLUMNS = (
    "id, athlete_id, source, start_time, utc_offset_s, duration_s, distance_m, sub_sport, "
    "has_hr, has_gps, garmin_activity_id, file_hash"
)


_ATHLETE_COLUMNS = "id, label, source, sex, birth_year, hr_rest_override, hr_max_override"


def connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript(_SCHEMA)
    return conn


def save_athlete(conn: sqlite3.Connection, athlete: Athlete) -> None:
    with conn:
        conn.execute(
            "INSERT INTO athlete (id, label, source, sex, birth_year, hr_rest_override, hr_max_override) "
            "VALUES (?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(id) DO UPDATE SET label=excluded.label, source=excluded.source, "
            "sex=excluded.sex, birth_year=excluded.birth_year, "
            "hr_rest_override=excluded.hr_rest_override, hr_max_override=excluded.hr_max_override",
            (
                athlete.id,
                athlete.label,
                athlete.source.value,
                athlete.sex.value,
                athlete.birth_year,
                athlete.hr_rest_override,
                athlete.hr_max_override,
            ),
        )


def _athlete_from_row(row: tuple) -> Athlete:
    return Athlete(
        id=row[0],
        label=row[1],
        source=ActivitySource(row[2]),
        sex=Sex(row[3]),
        birth_year=row[4],
        hr_rest_override=row[5],
        hr_max_override=row[6],
    )


def get_athlete(conn: sqlite3.Connection, athlete_id: str) -> Athlete | None:
    row = conn.execute(
        f"SELECT {_ATHLETE_COLUMNS} FROM athlete WHERE id = ?", (athlete_id,)
    ).fetchone()
    return _athlete_from_row(row) if row else None


def list_athletes(conn: sqlite3.Connection) -> list[Athlete]:
    rows = conn.execute(f"SELECT {_ATHLETE_COLUMNS} FROM athlete ORDER BY label").fetchall()
    return [_athlete_from_row(r) for r in rows]


def find_duplicate(conn: sqlite3.Connection, athlete_id: str, start_time: datetime) -> str | None:
    ts = int(start_time.timestamp())
    row = conn.execute(
        "SELECT id FROM activity WHERE athlete_id = ? AND start_time BETWEEN ? AND ? "
        "ORDER BY ABS(start_time - ?) LIMIT 1",
        (athlete_id, ts - 60, ts + 60, ts),
    ).fetchone()
    return row[0] if row else None


def save_activity(conn: sqlite3.Connection, activity: Activity, samples: Samples) -> None:
    with conn:
        conn.execute(
            f"INSERT INTO activity ({_ACTIVITY_COLUMNS}, local_date) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                activity.id,
                activity.athlete_id,
                activity.source.value,
                int(activity.start_time.timestamp()),
                activity.utc_offset_s,
                activity.duration_s,
                activity.distance_m,
                activity.sub_sport.value,
                int(activity.has_hr),
                int(activity.has_gps),
                activity.garmin_activity_id,
                activity.file_hash,
                activity.local_date.isoformat(),
            ),
        )
        conn.executemany(
            "INSERT INTO sample (activity_id, i, t_s, hr, speed_mps, distance_m, altitude_m, cadence) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                (activity.id, i, *row)
                for i, row in enumerate(
                    zip(
                        samples.t_s,
                        samples.hr,
                        samples.speed_mps,
                        samples.distance_m,
                        samples.altitude_m,
                        samples.cadence,
                    )
                )
            ),
        )


def known_garmin_activity_ids(conn: sqlite3.Connection, athlete_id: str) -> set[str]:
    rows = conn.execute(
        "SELECT garmin_activity_id FROM activity "
        "WHERE athlete_id = ? AND garmin_activity_id IS NOT NULL",
        (athlete_id,),
    ).fetchall()
    return {r[0] for r in rows}


def _activity_from_row(row: tuple) -> Activity:
    return Activity(
        id=row[0],
        athlete_id=row[1],
        source=ActivitySource(row[2]),
        start_time=datetime.fromtimestamp(row[3], UTC),
        utc_offset_s=row[4],
        duration_s=row[5],
        distance_m=row[6],
        sub_sport=SubSport(row[7]),
        has_hr=bool(row[8]),
        has_gps=bool(row[9]),
        garmin_activity_id=row[10],
        file_hash=row[11],
    )


def load_activities(
    conn: sqlite3.Connection, athlete_id: str, data_cutoff: date
) -> list[Activity]:
    rows = conn.execute(
        f"SELECT {_ACTIVITY_COLUMNS} FROM activity "
        "WHERE athlete_id = ? AND local_date < ? ORDER BY start_time",
        (athlete_id, data_cutoff.isoformat()),
    ).fetchall()
    return [_activity_from_row(r) for r in rows]


def load_samples(conn: sqlite3.Connection, activity_id: str, data_cutoff: date) -> Samples:
    row = conn.execute(
        "SELECT 1 FROM activity WHERE id = ? AND local_date < ?",
        (activity_id, data_cutoff.isoformat()),
    ).fetchone()
    if row is None:
        raise LookupError(
            f"Brak Aktywności '{activity_id}' sprzed Daty odcięcia {data_cutoff.isoformat()}."
        )
    rows = conn.execute(
        "SELECT t_s, hr, speed_mps, distance_m, altitude_m, cadence FROM sample "
        "WHERE activity_id = ? ORDER BY i",
        (activity_id,),
    ).fetchall()
    t_s, hr, speed, dist, alt, cad = (list(col) for col in zip(*rows)) if rows else ([],) * 6
    return Samples(t_s=t_s, hr=hr, speed_mps=speed, distance_m=dist, altitude_m=alt, cadence=cad)


def save_garmin_metrics(conn: sqlite3.Connection, metrics: Iterable[GarminMetric]) -> int:
    rows = [(m.athlete_id, m.date.isoformat(), m.kind.value, m.value) for m in metrics]
    with conn:
        conn.executemany(
            "INSERT INTO garmin_metric (athlete_id, date, kind, value) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(athlete_id, date, kind) DO UPDATE SET value=excluded.value",
            rows,
        )
    return len(rows)


def load_garmin_metrics(
    conn: sqlite3.Connection, athlete_id: str, data_cutoff: date
) -> list[GarminMetric]:
    rows = conn.execute(
        "SELECT athlete_id, date, kind, value FROM garmin_metric "
        "WHERE athlete_id = ? AND date < ? ORDER BY date, kind",
        (athlete_id, data_cutoff.isoformat()),
    ).fetchall()
    return [
        GarminMetric(
            athlete_id=r[0],
            date=date.fromisoformat(r[1]),
            kind=GarminMetricKind(r[2]),
            value=r[3],
        )
        for r in rows
    ]


def last_garmin_metric_date(conn: sqlite3.Connection, athlete_id: str) -> date | None:
    row = conn.execute(
        "SELECT MAX(date) FROM garmin_metric WHERE athlete_id = ?", (athlete_id,)
    ).fetchone()
    return date.fromisoformat(row[0]) if row and row[0] else None


def record_sync(
    conn: sqlite3.Connection, athlete_id: str, synced_at: datetime, report: dict
) -> None:
    with conn:
        conn.execute(
            "INSERT INTO sync_run (athlete_id, synced_at, report_json) VALUES (?, ?, ?)",
            (
                athlete_id,
                synced_at.astimezone(UTC).isoformat(timespec="microseconds"),
                json.dumps(report, ensure_ascii=False),
            ),
        )


def last_sync_at(
    conn: sqlite3.Connection, athlete_id: str, *, complete_only: bool = False
) -> datetime | None:
    query = "SELECT MAX(synced_at) FROM sync_run WHERE athlete_id = ?"
    if complete_only:
        query += " AND json_extract(report_json, '$.complete') = 1"
    row = conn.execute(query, (athlete_id,)).fetchone()
    return datetime.fromisoformat(row[0]) if row and row[0] else None


_CALL_COLUMNS = (
    "run_id, plan_id, athlete_id, step, week_number, attempt, model_key, model_id, prompt_version, schema_hash, "
    "summary_hash, context_hash, as_of, input_tokens, output_tokens, reasoning_tokens, cost_usd, latency_ms, "
    "stop_reason, output_json, parse_error, format_errors_json, violations_json, created_at"
)


def save_llm_call(conn: sqlite3.Connection, record: CallRecord) -> str:
    call_id = uuid.uuid4().hex
    with conn:
        conn.execute(
            f"INSERT INTO llm_call (id, {_CALL_COLUMNS}) VALUES (?{', ?' * 24})",
            (
                call_id,
                record.run_id,
                record.plan_id,
                record.athlete_id,
                record.step,
                record.week_number,
                record.attempt,
                record.model_key,
                record.model_id,
                record.prompt_version,
                record.schema_hash,
                record.summary_hash,
                record.context_hash,
                record.as_of.isoformat(),
                record.input_tokens,
                record.output_tokens,
                record.reasoning_tokens,
                record.cost_usd,
                record.latency_ms,
                record.stop_reason,
                record.output_json,
                record.parse_error,
                json.dumps(record.format_errors, ensure_ascii=False),
                json.dumps([v.model_dump(mode="json") for v in record.violations], ensure_ascii=False),
                record.created_at.astimezone(UTC).isoformat(timespec="microseconds"),
            ),
        )
    return call_id


def load_llm_calls(conn: sqlite3.Connection, run_id: str) -> list[CallRecord]:
    rows = conn.execute(
        f"SELECT {_CALL_COLUMNS} FROM llm_call WHERE run_id = ? ORDER BY created_at, rowid",
        (run_id,),
    ).fetchall()
    return [
        CallRecord(
            run_id=r[0],
            plan_id=r[1],
            athlete_id=r[2],
            step=r[3],
            week_number=r[4],
            attempt=r[5],
            model_key=r[6],
            model_id=r[7],
            prompt_version=r[8],
            schema_hash=r[9],
            summary_hash=r[10],
            context_hash=r[11],
            as_of=date.fromisoformat(r[12]),
            input_tokens=r[13],
            output_tokens=r[14],
            reasoning_tokens=r[15],
            cost_usd=r[16],
            latency_ms=r[17],
            stop_reason=r[18],
            output_json=r[19],
            parse_error=r[20],
            format_errors=json.loads(r[21]),
            violations=[Violation.model_validate(v) for v in json.loads(r[22])],
            created_at=datetime.fromisoformat(r[23]),
        )
        for r in rows
    ]


_PLAN_COLUMNS = (
    "id, run_id, athlete_id, data_cutoff, as_of, goal_json, model_key, status, error, gate_json, "
    "interpretation_json, interpretation_check_json, skeleton_json, skeleton_status, "
    "skeleton_violations_json, skeleton_format_errors_json, week_json, week_status, "
    "week_violations_json, week_format_errors_json, created_at"
)


def save_plan(conn: sqlite3.Connection, row: PlanRecord) -> None:
    values = (
        row.id,
        row.run_id,
        row.athlete_id,
        row.data_cutoff.isoformat(),
        row.as_of.isoformat(),
        row.goal_json,
        row.model_key,
        row.status,
        row.error,
        row.gate_json,
        row.interpretation_json,
        row.interpretation_check_json,
        row.skeleton_json,
        row.skeleton_status,
        row.skeleton_violations_json,
        row.skeleton_format_errors_json,
        row.week_json,
        row.week_status,
        row.week_violations_json,
        row.week_format_errors_json,
        row.created_at.astimezone(UTC).isoformat(timespec="microseconds"),
    )
    with conn:
        conn.execute(
            f"INSERT OR REPLACE INTO plan ({_PLAN_COLUMNS}) VALUES (?{', ?' * 20})", values
        )


def _plan_from_row(r: tuple) -> PlanRecord:
    return PlanRecord(
        id=r[0],
        run_id=r[1],
        athlete_id=r[2],
        data_cutoff=date.fromisoformat(r[3]),
        as_of=date.fromisoformat(r[4]),
        goal_json=r[5],
        model_key=r[6],
        status=r[7],
        error=r[8],
        gate_json=r[9],
        interpretation_json=r[10],
        interpretation_check_json=r[11],
        skeleton_json=r[12],
        skeleton_status=r[13],
        skeleton_violations_json=r[14],
        skeleton_format_errors_json=r[15],
        week_json=r[16],
        week_status=r[17],
        week_violations_json=r[18],
        week_format_errors_json=r[19],
        created_at=datetime.fromisoformat(r[20]),
    )


def load_plans(conn: sqlite3.Connection, athlete_id: str) -> list[PlanRecord]:
    rows = conn.execute(
        f"SELECT {_PLAN_COLUMNS} FROM plan WHERE athlete_id = ? ORDER BY created_at DESC, rowid DESC",
        (athlete_id,),
    ).fetchall()
    return [_plan_from_row(r) for r in rows]


def get_plan(conn: sqlite3.Connection, plan_id: str) -> PlanRecord | None:
    row = conn.execute(f"SELECT {_PLAN_COLUMNS} FROM plan WHERE id = ?", (plan_id,)).fetchone()
    return _plan_from_row(row) if row else None
