import numpy as np
import pandas as pd

from ..domain import Activity, Samples, Zone, ZoneBounds
from .hr_quality import sample_dt
from .params import (
    DECOUPLING_SKIP_S,
    EASY_MIN_SHARE,
    EF_MIN_DURATION_S,
    MOVING_MIN_SPEED_MPS,
    STEADY_MAX_GAIN_M_PER_KM,
    STEADY_MAX_SPEED_CV,
    STEADY_MIN_DURATION_S,
    STEADY_SMOOTH_S,
)
from .speed import floats, moving_speed
from .zones import time_in_zones_hr


def _easy_share(samples: Samples, mask: np.ndarray, zones: list[ZoneBounds]) -> float:
    seconds = time_in_zones_hr(samples, mask, zones)
    total = sum(seconds.values())
    return (seconds[Zone.Z1] + seconds[Zone.Z2]) / total if total > 0 else 0.0


def _ef(samples: Samples, mask: np.ndarray, select: np.ndarray) -> float | None:
    speed = moving_speed(samples)
    hr = floats(samples.hr)
    with np.errstate(invalid="ignore"):
        use = select & mask & (speed >= MOVING_MIN_SPEED_MPS) & ~np.isnan(hr)
    dt = sample_dt(samples)[use]
    total = dt.sum()
    if total <= 0:
        return None
    mean_speed = float(np.sum(speed[use] * dt) / total) * 60
    mean_hr = float(np.sum(hr[use] * dt) / total)
    return mean_speed / mean_hr if mean_hr > 0 else None


def efficiency_factor(
    activity: Activity, samples: Samples, mask: np.ndarray, zones: list[ZoneBounds]
) -> float | None:
    if not activity.counts_for_performance or activity.duration_s < EF_MIN_DURATION_S:
        return None
    if _easy_share(samples, mask, zones) < EASY_MIN_SHARE:
        return None
    return _ef(samples, mask, np.ones(len(samples.t_s), dtype=bool))


def is_steady(activity: Activity, samples: Samples, mask: np.ndarray, zones: list[ZoneBounds]) -> bool:
    if not activity.counts_for_performance or activity.duration_s < STEADY_MIN_DURATION_S:
        return False
    if _easy_share(samples, mask, zones) < EASY_MIN_SHARE:
        return False
    index = pd.to_timedelta(np.asarray(samples.t_s, dtype=float), unit="s")
    window = f"{STEADY_SMOOTH_S}s"

    speed = pd.Series(moving_speed(samples), index=index)
    moving = speed[speed >= MOVING_MIN_SPEED_MPS]
    if len(moving) < 2:
        return False
    smooth = moving.rolling(window).mean()
    if smooth.mean() <= 0 or smooth.std(ddof=0) / smooth.mean() > STEADY_MAX_SPEED_CV:
        return False

    altitude = pd.Series(floats(samples.altitude_m), index=index).rolling(window, min_periods=1).mean()
    steps = np.diff(altitude.to_numpy())
    gain = float(np.nansum(np.clip(steps, 0, None)))
    km = activity.distance_m / 1000
    return km > 0 and gain / km <= STEADY_MAX_GAIN_M_PER_KM


def decoupling(samples: Samples, mask: np.ndarray, steady: bool) -> float | None:
    if not steady:
        return None
    t = np.asarray(samples.t_s, dtype=float)
    keep = t >= DECOUPLING_SKIP_S
    if not keep.any():
        return None
    mid = (t[keep][0] + t[keep][-1]) / 2
    first = _ef(samples, mask, keep & (t < mid))
    second = _ef(samples, mask, keep & (t >= mid))
    if first is None or second is None:
        return None
    return (1 - second / first) * 100
