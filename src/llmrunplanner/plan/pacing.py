from collections.abc import Iterable
from datetime import timedelta

from ..domain import (
    CalendarWeek,
    Goal,
    PacedBlock,
    PacedSegment,
    PacedWorkout,
    Phase,
    RaceDay,
    Segment,
    Week,
    WeekDraft,
    Workout,
    Zone,
    ZoneBounds,
)
from .expand import expand_segments


def _by_zone(zones: list[ZoneBounds]) -> dict[Zone, ZoneBounds]:
    return {z.zone: z for z in zones}


def segment_duration_s(segment: Segment, bounds: ZoneBounds) -> int:
    """Czas Segmentu przy tempie reprezentatywnym jego Strefy (`bounds` to granice tej Strefy)."""
    return round(segment.distance_m / 1000 * bounds.pace_mid_s_per_km)


def workout_duration_s(workout: Workout, zones: list[ZoneBounds]) -> int:
    by_zone = _by_zone(zones)
    return sum(segment_duration_s(s, by_zone[s.zone]) for s in expand_segments(workout))


def zone_minutes(workouts: Iterable[Workout], zones: list[ZoneBounds]) -> dict[Zone, float]:
    by_zone = _by_zone(zones)
    seconds = {z: 0 for z in Zone}
    for w in workouts:
        for s in expand_segments(w):
            seconds[s.zone] += segment_duration_s(s, by_zone[s.zone])
    return {z: sec / 60 for z, sec in seconds.items()}


def race_day(goal: Goal, predicted_time_s: int | None) -> RaceDay:
    """Start z Celu; czas docelowy, a bez niego Prognoza czasu."""
    time_s = goal.target_time_s if goal.target_time_s is not None else predicted_time_s
    return RaceDay(
        date=goal.race_date,
        distance=goal.distance,
        target_time_s=time_s,
        pace_s_per_km=None if time_s is None else time_s / goal.distance.km,
    )


def _round_or_none(value: float | None) -> int | None:
    return None if value is None else round(value)


def _paced_segment(segment: Segment, bounds: ZoneBounds) -> PacedSegment:
    return PacedSegment(
        zone=segment.zone,
        distance_m=segment.distance_m,
        duration_s=segment_duration_s(segment, bounds),
        pace_fast_s_per_km=bounds.pace_fast_s_per_km,
        pace_slow_s_per_km=bounds.pace_slow_s_per_km,
        pace_mid_s_per_km=bounds.pace_mid_s_per_km,
        hr_low_bpm=_round_or_none(bounds.hr_low),
        hr_high_bpm=_round_or_none(bounds.hr_high),
    )


def pace_week(
    draft: WeekDraft,
    number: int,
    phase: Phase,
    week: CalendarWeek,
    zones: list[ZoneBounds],
    race: RaceDay | None = None,
) -> Week:
    if race is not None and not week.start <= race.date <= week.end:
        raise ValueError(f"Start {race.date} nie przypada w Tygodniu {number} ({week.start}–{week.end}).")
    by_zone = _by_zone(zones)
    workouts = []
    for w in sorted(draft.workouts, key=lambda w: w.day):
        blocks = [
            PacedBlock(repeat=b.repeat, segments=[_paced_segment(s, by_zone[s.zone]) for s in b.segments])
            for b in w.blocks
        ]
        seconds = sum(b.repeat * sum(s.duration_s for s in b.segments) for b in blocks)
        workouts.append(
            PacedWorkout(
                day=w.day,
                date=week.start + timedelta(days=w.day - 1),
                type=w.type,
                blocks=blocks,
                distance_km=round(sum(s.distance_m for s in expand_segments(w)) / 1000, 2),
                duration_min=round(seconds / 60),
            )
        )
    minutes = zone_minutes(draft.workouts, zones)
    return Week(
        number=number,
        phase=phase,
        start=week.start,
        end=week.end,
        workouts=workouts,
        distance_km=round(sum(w.distance_km for w in workouts), 2),
        duration_min=round(sum(minutes.values())),
        zone_minutes=minutes,
        race=race,
    )
