from collections.abc import Iterable
from datetime import date, timedelta
from statistics import median

import numpy as np
import pandas as pd

from ..domain import Athlete, GarminMetric, GarminMetricKind, HeartRateProfile, Samples
from .params import (
    CADENCE_LOCK_DIFF_S,
    CADENCE_LOCK_EXACT_BPM,
    CADENCE_LOCK_MIN_CADENCE,
    CADENCE_LOCK_MIN_CORR,
    CADENCE_LOCK_MIN_DIFFS,
    CADENCE_LOCK_MIN_S,
    CADENCE_LOCK_TOLERANCE_BPM,
    HR_MAX_SMOOTH_WINDOW,
    HR_REST_DEFAULT,
    HR_REST_WINDOW_DAYS,
    HR_SPIKE_BPM,
    HR_SPIKE_WINDOW,
    HR_VALID_MAX,
    HR_VALID_MIN,
    MAX_SAMPLE_GAP_S,
)
from .speed import floats


def sample_dt(samples: Samples) -> np.ndarray:
    t = np.asarray(samples.t_s, dtype=float)
    dt = np.zeros(len(t))
    if len(t) > 1:
        dt[1:] = np.clip(np.diff(t), 0, MAX_SAMPLE_GAP_S)
    return dt


def _tracks_cadence(t: np.ndarray, hr: np.ndarray, twice_cadence: np.ndarray) -> bool:
    """Czy w ciągu tętno idzie za kadencją: korelacja różnic lub dokładne śledzenie przy zbyt małej zmienności."""
    if np.max(np.abs(hr - twice_cadence)) <= CADENCE_LOCK_EXACT_BPM:
        return True
    j = np.searchsorted(t, t + CADENCE_LOCK_DIFF_S, side="left")
    ok = j < len(t)
    ok[ok] = (t[j[ok]] - t[ok]) <= CADENCE_LOCK_DIFF_S + 1
    if ok.sum() < CADENCE_LOCK_MIN_DIFFS:
        return False
    dh = hr[j[ok]] - hr[ok]
    dc = twice_cadence[j[ok]] - twice_cadence[ok]
    if dh.std() == 0 or dc.std() == 0:
        return False
    return bool(np.corrcoef(dh, dc)[0, 1] >= CADENCE_LOCK_MIN_CORR)


def _cadence_lock(t: np.ndarray, hr: np.ndarray, cadence: np.ndarray) -> np.ndarray:
    with np.errstate(invalid="ignore"):
        cond = (cadence >= CADENCE_LOCK_MIN_CADENCE) & (np.abs(hr - 2 * cadence) <= CADENCE_LOCK_TOLERANCE_BPM)
    lock = np.zeros(len(t), dtype=bool)
    i, n = 0, len(t)
    while i < n:
        if not cond[i]:
            i += 1
            continue
        j = i
        while j + 1 < n and cond[j + 1]:
            j += 1
        if t[j] - t[i] >= CADENCE_LOCK_MIN_S and _tracks_cadence(t[i : j + 1], hr[i : j + 1], 2 * cadence[i : j + 1]):
            lock[i : j + 1] = True
        i = j + 1
    return lock


def valid_hr_mask(samples: Samples) -> np.ndarray:
    hr = floats(samples.hr)
    if len(hr) == 0:
        return np.zeros(0, dtype=bool)
    with np.errstate(invalid="ignore"):
        in_range = (hr >= HR_VALID_MIN) & (hr <= HR_VALID_MAX)
    med = pd.Series(np.where(in_range, hr, np.nan)).rolling(HR_SPIKE_WINDOW, center=True, min_periods=1).median().to_numpy()
    with np.errstate(invalid="ignore"):
        no_spike = np.abs(hr - med) <= HR_SPIKE_BPM
    lock = _cadence_lock(np.asarray(samples.t_s, dtype=float), hr, floats(samples.cadence))
    return in_range & no_spike & ~lock


def hr_max_from_data(series: Iterable[tuple[Samples, np.ndarray]]) -> int | None:
    best: float | None = None
    for samples, mask in series:
        hr = np.where(mask, floats(samples.hr), np.nan)
        if not mask.any():
            continue
        smooth = pd.Series(hr).rolling(HR_MAX_SMOOTH_WINDOW, center=True, min_periods=HR_MAX_SMOOTH_WINDOW).median().to_numpy()
        if np.isnan(smooth).all():
            continue
        peak = float(np.nanmax(smooth))
        if best is None or peak > best:
            best = peak
    return None if best is None else int(round(best))


def heart_rate_profile(
    athlete: Athlete, hr_max_data: int | None, garmin: list[GarminMetric], data_cutoff: date
) -> HeartRateProfile:
    if athlete.hr_max_override is not None:
        hr_max, max_source = athlete.hr_max_override, "override"
    elif hr_max_data is not None:
        hr_max, max_source = hr_max_data, "data"
    else:
        raise ValueError("Brak tętna maksymalnego: w danych nie ma poprawnego pomiaru tętna i nie podano wartości ręcznie.")

    if athlete.hr_rest_override is not None:
        hr_rest, rest_source = athlete.hr_rest_override, "override"
    else:
        start = data_cutoff - timedelta(days=HR_REST_WINDOW_DAYS)
        values = [
            m.value
            for m in garmin
            if m.kind == GarminMetricKind.RESTING_HR and start <= m.date < data_cutoff
        ]
        if values:
            hr_rest, rest_source = int(round(median(values))), "garmin"
        else:
            hr_rest, rest_source = HR_REST_DEFAULT, "default"
    return HeartRateProfile(hr_max=hr_max, hr_rest=hr_rest, hr_max_source=max_source, hr_rest_source=rest_source)
