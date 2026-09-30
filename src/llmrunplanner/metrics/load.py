from collections import defaultdict
from collections.abc import Sequence
from datetime import date, timedelta

import numpy as np

from ..domain import Activity, ActivityMetrics, DailyLoad, HeartRateProfile, LoadPoint, Samples, Sex, Zone
from .hr_quality import sample_dt
from .params import ATL_DAYS, CTL_DAYS, LOAD_INIT_DAYS, TRIMP_COEFFS
from .speed import floats


def trimp(samples: Samples, mask: np.ndarray, profile: HeartRateProfile, sex: Sex) -> float:
    a, b = TRIMP_COEFFS[sex]
    hr = floats(samples.hr)[mask]
    dt = sample_dt(samples)[mask]
    x = np.clip((hr - profile.hr_rest) / (profile.hr_max - profile.hr_rest), 0, 1)
    return float(np.sum(dt / 60 * x * a * np.exp(b * x)))


def hrtss(samples: Samples, mask: np.ndarray, hr_rest: int, threshold_hr: int) -> float:
    hr = floats(samples.hr)[mask]
    dt = sample_dt(samples)[mask]
    y = np.maximum(0, (hr - hr_rest) / (threshold_hr - hr_rest))
    return float(np.sum(dt / 3600 * 100 * y**2))


def daily_load(
    activities: list[Activity], metrics: dict[str, ActivityMetrics], start: date, end: date
) -> list[DailyLoad]:
    by_day: dict[date, list[Activity]] = defaultdict(list)
    for a in activities:
        by_day[a.local_date].append(a)
    days: list[DailyLoad] = []
    day = start
    while day < end:
        acts = by_day.get(day, [])
        zone_minutes: dict[Zone, float] = {}
        for a in acts:
            for zone, seconds in metrics[a.id].zone_seconds_hr.items():
                zone_minutes[zone] = zone_minutes.get(zone, 0.0) + seconds / 60
        days.append(
            DailyLoad(
                date=day,
                km=sum(a.distance_m for a in acts) / 1000,
                minutes=sum(a.duration_s for a in acts) / 60,
                trimp=sum(metrics[a.id].trimp for a in acts),
                zone_minutes={z: m for z, m in zone_minutes.items() if m > 0},
                trained=bool(acts),
            )
        )
        day += timedelta(days=1)
    return days


def fitness(daily: list[DailyLoad]) -> list[LoadPoint]:
    if not daily:
        return []
    head = [d.trimp for d in daily[:LOAD_INIT_DAYS]]
    ctl = atl = sum(head) / len(head)
    points = []
    for d in daily:
        ctl += (d.trimp - ctl) / CTL_DAYS
        atl += (d.trimp - atl) / ATL_DAYS
        points.append(LoadPoint(date=d.date, ctl=ctl, atl=atl, tsb=ctl - atl))
    return points


def monotony(daily_trimp: Sequence[float]) -> tuple[float | None, float | None]:
    if len(daily_trimp) != 7:
        raise ValueError("Monotonia wymaga dokładnie 7 dni.")
    values = np.asarray(daily_trimp, dtype=float)
    std = float(values.std())
    if std == 0:
        return None, None
    mono = float(values.mean()) / std
    return mono, float(values.sum()) * mono
