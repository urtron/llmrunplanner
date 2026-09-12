import json
import sqlite3
from collections.abc import Iterable
from datetime import UTC, date, datetime
from pathlib import Path

from ..domain import (
    Activity,
    ActivitySource,
    Athlete,
    GarminMetric,
    GarminMetricKind,
    Samples,
    Sex,
    SubSport,
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
