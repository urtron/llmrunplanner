import numpy as np

from ..domain import Activity, Samples, Threshold, Zone, ZoneBounds
from .hr_quality import sample_dt
from .params import HR_ZONE_CUTS, MOVING_MIN_SPEED_MPS, PACE_ZONE_CUTS, ZONE_PACE_MID_FACTORS
from .speed import floats, moving_speed

SEILER_ZONE: dict[Zone, int] = {Zone.Z1: 1, Zone.Z2: 1, Zone.Z3: 2, Zone.Z4: 3, Zone.Z5: 3}

_ZONES = list(Zone)


def zone_bounds(threshold: Threshold) -> list[ZoneBounds] | None:
    if threshold.hr_bpm is None or threshold.pace_s_per_km is None:
        return None
    hr = [c * threshold.hr_bpm for c in HR_ZONE_CUTS]
    pace = [c * threshold.pace_s_per_km for c in PACE_ZONE_CUTS]
    return [
        ZoneBounds(
            zone=zone,
            hr_low=hr[i - 1] if i > 0 else None,
            hr_high=hr[i] if i < 4 else None,
            pace_fast_s_per_km=pace[i] if i < 4 else None,
            pace_slow_s_per_km=pace[i - 1] if i > 0 else None,
            pace_mid_s_per_km=ZONE_PACE_MID_FACTORS[zone] * threshold.pace_s_per_km,
        )
        for i, zone in enumerate(_ZONES)
    ]


def _to_zone(idx: int | np.ndarray) -> Zone | np.ndarray:
    if np.ndim(idx) == 0:
        return _ZONES[int(idx)]
    out = np.empty(np.shape(idx), dtype=object)
    for i, z in enumerate(_ZONES):
        out[idx == i] = z
    return out


def zone_of_hr(hr: float | np.ndarray, zones: list[ZoneBounds]) -> Zone | np.ndarray:
    cuts = np.array([z.hr_high for z in zones[:4]], dtype=float)
    return _to_zone(np.sum(np.asarray(hr, dtype=float)[..., None] >= cuts, axis=-1))


def zone_of_pace(pace_s_per_km: float | np.ndarray, zones: list[ZoneBounds]) -> Zone | np.ndarray:
    cuts = np.array([z.pace_fast_s_per_km for z in zones[:4]], dtype=float)
    return _to_zone(np.sum(np.asarray(pace_s_per_km, dtype=float)[..., None] <= cuts, axis=-1))


def _seconds_by_zone(zone_arr: np.ndarray, dt: np.ndarray) -> dict[Zone, float]:
    return {z: float(dt[zone_arr == z].sum()) for z in _ZONES}


def time_in_zones_hr(samples: Samples, mask: np.ndarray, zones: list[ZoneBounds]) -> dict[Zone, float]:
    hr = floats(samples.hr)
    valid = mask & ~np.isnan(hr)
    dt = sample_dt(samples)[valid]
    return _seconds_by_zone(zone_of_hr(hr[valid], zones), dt)


def time_in_zones_pace(activity: Activity, samples: Samples, zones: list[ZoneBounds]) -> dict[Zone, float] | None:
    if not activity.counts_for_performance:
        return None
    speed = moving_speed(samples)
    with np.errstate(invalid="ignore"):
        moving = speed >= MOVING_MIN_SPEED_MPS
    dt = sample_dt(samples)[moving]
    return _seconds_by_zone(zone_of_pace(1000.0 / speed[moving], zones), dt)
