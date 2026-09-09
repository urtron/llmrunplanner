import hashlib
import io
import zipfile
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from garmin_fit_sdk import Decoder, Stream
from pydantic import ValidationError

from ..domain.activity import Activity, Samples
from ..domain.enums import ActivitySource, SubSport

# SDK zwraca local_timestamp jako liczbę sekund od epoki FIT, a timestamp jako datetime
_FIT_EPOCH = datetime(1989, 12, 31, tzinfo=UTC)

_SUB_SPORTS = {
    "generic": SubSport.STREET,
    "street": SubSport.STREET,
    "treadmill": SubSport.TREADMILL,
    "indoor_running": SubSport.TREADMILL,
    "trail": SubSport.TRAIL,
    "track": SubSport.TRACK,
}


class FitParseError(ValueError):
    """Plik FIT nie daje się zdekodować albo nie zawiera wiadomości session."""


def extract_fit_from_zip(data: bytes) -> bytes:
    """Zwraca jedyny plik .fit z archiwum ZIP pobranego z Garmin Connect (ORIGINAL)."""
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            names = [n for n in zf.namelist() if n.lower().endswith(".fit")]
            if not names:
                raise FitParseError("Archiwum ZIP nie zawiera pliku .fit.")
            return zf.read(names[0])
    except zipfile.BadZipFile as exc:
        raise FitParseError("Nieprawidłowe archiwum ZIP.") from exc


def _utc_offset_s(activity_mesgs: list[dict], start_time: datetime) -> int:
    if activity_mesgs:
        ts = activity_mesgs[0].get("timestamp")
        local = activity_mesgs[0].get("local_timestamp")
        if isinstance(ts, datetime) and isinstance(local, (int, float)):
            local_dt = _FIT_EPOCH + timedelta(seconds=local)
            return round((local_dt - ts).total_seconds() / 900) * 900
    offset = ZoneInfo("Europe/Warsaw").utcoffset(start_time)
    assert offset is not None
    return int(offset.total_seconds())


def parse_fit(
    data: bytes,
    *,
    activity_id: str,
    athlete_id: str,
    source: ActivitySource,
    garmin_activity_id: str | None = None,
) -> tuple[Activity, Samples] | None:
    """Zamienia bajty pliku FIT na Aktywność i próbki; zwraca None dla sportów innych niż bieg."""
    try:
        messages, errors = Decoder(Stream.from_byte_array(bytearray(data))).read()
    except Exception as exc:
        raise FitParseError(f"Nie udało się zdekodować pliku FIT: {exc}") from exc
    if errors:
        raise FitParseError(f"Błędy dekodowania pliku FIT: {errors}")
    sessions = messages.get("session_mesgs")
    if not sessions:
        raise FitParseError("Plik FIT nie zawiera wiadomości session.")
    session = sessions[0]
    if session.get("sport") != "running":
        return None

    start_time = session.get("start_time")
    if not isinstance(start_time, datetime):
        raise FitParseError("Wiadomość session nie zawiera czasu startu.")
    records = sorted(
        (r for r in messages.get("record_mesgs", []) if isinstance(r.get("timestamp"), datetime)),
        key=lambda r: r["timestamp"],
    )
    has_gps = any(r.get("position_lat") is not None for r in records)

    def pick(r: dict, *keys: str):
        for k in keys:
            if r.get(k) is not None:
                return r[k]
        return None

    t_s, hr, speed, dist, alt, cad = [], [], [], [], [], []
    for r in records:
        t_s.append(int((r["timestamp"] - start_time).total_seconds()))
        hr.append(r.get("heart_rate") or None)
        speed.append(pick(r, "enhanced_speed", "speed"))
        dist.append(r.get("distance"))
        alt.append(pick(r, "enhanced_altitude", "altitude"))
        cad.append(r.get("cadence"))

    sub_sport = _SUB_SPORTS.get(session.get("sub_sport"))
    if sub_sport is None:
        sub_sport = SubSport.STREET if has_gps else SubSport.TREADMILL

    try:
        activity = Activity(
            id=activity_id,
            athlete_id=athlete_id,
            source=source,
            start_time=start_time,
            utc_offset_s=_utc_offset_s(messages.get("activity_mesgs", []), start_time),
            duration_s=max(1, round(session.get("total_timer_time") or 0)),
            distance_m=session.get("total_distance") or 0,
            sub_sport=sub_sport,
            has_hr=any(h is not None for h in hr),
            has_gps=has_gps,
            garmin_activity_id=garmin_activity_id,
            file_hash=hashlib.sha256(data).hexdigest(),
        )
        samples = Samples(t_s=t_s, hr=hr, speed_mps=speed, distance_m=dist, altitude_m=alt, cadence=cad)
    except ValidationError as exc:
        raise FitParseError(f"Nieprawidłowe dane w pliku FIT: {exc}") from exc
    return activity, samples
