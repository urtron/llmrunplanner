from collections.abc import Iterable
from datetime import date, timedelta

import numpy as np

from ..domain import Activity, BestEffort, CriticalSpeed, Samples, Threshold
from .params import (
    CV_MAX_MPS,
    CV_MIN_EFFORTS,
    CV_MIN_MPS,
    CV_MIN_R2,
    D_PRIME_MAX_M,
    D_PRIME_MIN_M,
    D_PRIME_SUBMAXIMAL_M,
    EFFORT_DURATIONS_S,
    EFFORT_MAX_SPEED_MPS,
    EFFORT_MAX_STEP_SPEED_MPS,
    MAX_SAMPLE_GAP_S,
    THRESHOLD_FALLBACK_WINDOW_DAYS,
    THRESHOLD_HR_MAX_FRACTION,
    THRESHOLD_HR_MIN_FRACTION,
    THRESHOLD_HR_MIN_VALID_SHARE,
    THRESHOLD_HR_WINDOW_S,
    THRESHOLD_WINDOW_DAYS,
)
from .speed import floats


def _segments(t: np.ndarray, d: np.ndarray | None = None) -> list[tuple[int, int]]:
    """Przedziały indeksów [start, end) bez luki większej niż MAX_SAMPLE_GAP_S; z `d` także bez skoków dystansu."""
    if len(t) == 0:
        return []
    dt = np.diff(t)
    cut = dt > MAX_SAMPLE_GAP_S
    if d is not None:
        dd = np.diff(d)
        cut |= (dd < 0) | (dd > EFFORT_MAX_STEP_SPEED_MPS * np.maximum(dt, 1.0))
    breaks = np.flatnonzero(cut) + 1
    starts = np.concatenate(([0], breaks))
    ends = np.concatenate((breaks, [len(t)]))
    return list(zip(starts.tolist(), ends.tolist()))


def best_efforts(activity: Activity, samples: Samples) -> list[BestEffort]:
    if not activity.counts_for_performance:
        return []
    t = np.asarray(samples.t_s, dtype=float)
    d = floats(samples.distance_m)
    keep = ~np.isnan(d)
    t, d = t[keep], d[keep]
    best: dict[int, float] = {}
    for a, b in _segments(t, d):
        if b - a < 2:
            continue
        grid = np.arange(np.ceil(t[a]), np.floor(t[b - 1]) + 1)
        dist = np.interp(grid, t[a:b], d[a:b])
        for dur in EFFORT_DURATIONS_S:
            if len(grid) <= dur:
                continue
            diffs = dist[dur:] - dist[:-dur]
            diffs = diffs[diffs / dur <= EFFORT_MAX_SPEED_MPS]
            if len(diffs) and float(diffs.max()) > best.get(dur, -np.inf):
                best[dur] = float(diffs.max())
    return [
        BestEffort(duration_s=dur, distance_m=m, activity_id=activity.id, date=activity.local_date)
        for dur, m in sorted(best.items())
    ]


def critical_speed(efforts: list[BestEffort]) -> CriticalSpeed:
    per_duration: dict[int, BestEffort] = {}
    for e in efforts:
        cur = per_duration.get(e.duration_s)
        if cur is None or e.distance_m > cur.distance_m:
            per_duration[e.duration_s] = e
    used = [per_duration[k] for k in sorted(per_duration)]
    issues: list[str] = []
    if len(used) < CV_MIN_EFFORTS:
        issues.append(f"Za mało odcinków o różnej długości: {len(used)}, wymagane co najmniej {CV_MIN_EFFORTS}.")
    if len(used) < 2:
        return CriticalSpeed(cv_mps=None, d_prime_m=None, r2=None, efforts=used, valid=False, issues=issues)

    x = np.array([e.duration_s for e in used], dtype=float)
    y = np.array([e.distance_m for e in used], dtype=float)
    cv, d_prime = np.polyfit(x, y, 1)
    ss_res = float(np.sum((y - (cv * x + d_prime)) ** 2))
    ss_tot = float(np.sum((y - y.mean()) ** 2))
    r2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else 0.0
    cv, d_prime = float(cv), float(d_prime)

    if r2 < CV_MIN_R2:
        issues.append(f"Słabe dopasowanie modelu: R² = {r2:.3f}, wymagane co najmniej {CV_MIN_R2}.")
    if not D_PRIME_MIN_M <= d_prime <= D_PRIME_MAX_M:
        issues.append(f"D′ = {d_prime:.0f} m poza zakresem {D_PRIME_MIN_M}–{D_PRIME_MAX_M} m.")
    if not CV_MIN_MPS <= cv <= CV_MAX_MPS:
        issues.append(f"Prędkość krytyczna {cv:.2f} m/s poza zakresem {CV_MIN_MPS}–{CV_MAX_MPS} m/s.")
    return CriticalSpeed(cv_mps=cv, d_prime_m=d_prime, r2=r2, efforts=used, valid=not issues, issues=issues)


def _best_window_hr(samples: Samples, mask: np.ndarray) -> float | None:
    t = np.asarray(samples.t_s, dtype=float)
    hr = floats(samples.hr)
    valid = mask & ~np.isnan(hr)
    best: float | None = None
    w = THRESHOLD_HR_WINDOW_S
    for a, b in _segments(t):
        grid = np.arange(np.ceil(t[a]), np.floor(t[b - 1]) + 1)
        if len(grid) < w:
            continue
        idx = a + np.searchsorted(t[a:b], grid, side="right") - 1  # ostatnia próbka nie późniejsza niż sekunda siatki
        ok = valid[idx].astype(float)
        val = np.where(valid[idx], hr[idx], 0.0)
        c_ok = np.concatenate(([0.0], np.cumsum(ok)))
        c_val = np.concatenate(([0.0], np.cumsum(val)))
        n_ok = c_ok[w:] - c_ok[:-w]
        s_val = c_val[w:] - c_val[:-w]
        good = n_ok >= THRESHOLD_HR_MIN_VALID_SHARE * w
        if not good.any():
            continue
        m = float(np.max(s_val[good] / n_ok[good]))
        if best is None or m > best:
            best = m
    return best


def threshold_hr(
    series: Iterable[tuple[Activity, Samples, np.ndarray]], hr_max: int
) -> tuple[int | None, list[str]]:
    best: float | None = None
    for activity, samples, mask in series:
        if not activity.has_hr:
            continue
        m = _best_window_hr(samples, mask)
        if m is not None and (best is None or m > best):
            best = m
    if best is None:
        return None, [f"Brak ciągłego wysiłku trwającego {THRESHOLD_HR_WINDOW_S // 60} min z poprawnym tętnem."]
    value = int(round(best))
    issues: list[str] = []
    lo, hi = THRESHOLD_HR_MIN_FRACTION * hr_max, THRESHOLD_HR_MAX_FRACTION * hr_max
    if not lo <= value <= hi:
        issues.append(
            f"Tętno progowe {value} uderzeń/min poza oczekiwanym zakresem "
            f"{lo:.0f}–{hi:.0f} ({THRESHOLD_HR_MIN_FRACTION:.0%}–{THRESHOLD_HR_MAX_FRACTION:.0%} tętna maksymalnego)."
        )
    return value, issues


def _fit_window(
    items: list[tuple[Activity, Samples, np.ndarray]], data_cutoff: date, days: int
) -> tuple[CriticalSpeed, list[tuple[Activity, Samples, np.ndarray]]]:
    start = data_cutoff - timedelta(days=days)
    window = [it for it in items if it[0].local_date >= start]
    return critical_speed([e for a, s, _ in window for e in best_efforts(a, s)]), window


def estimate_threshold(
    items: list[tuple[Activity, Samples, np.ndarray]], hr_max: int, hr_rest: int, data_cutoff: date
) -> Threshold:
    days = THRESHOLD_WINDOW_DAYS
    cs, window = _fit_window(items, data_cutoff, days)
    warnings: list[str] = []
    if not cs.valid or (cs.d_prime_m or 0) < D_PRIME_SUBMAXIMAL_M:
        cs_wide, window_wide = _fit_window(items, data_cutoff, THRESHOLD_FALLBACK_WINDOW_DAYS)
        if cs_wide.valid:
            cs, window, days = cs_wide, window_wide, THRESHOLD_FALLBACK_WINDOW_DAYS
            warnings.append(f"Próg wyznaczony z {days // 7} tygodni, może być nieaktualny")
    if cs.valid and cs.d_prime_m is not None and cs.d_prime_m < D_PRIME_SUBMAXIMAL_M:
        warnings.append(
            f"D′ poniżej {D_PRIME_SUBMAXIMAL_M} m: najlepsze odcinki były prawdopodobnie niemaksymalne, Próg może być zaniżony"
        )
    pace = 1000.0 / cs.cv_mps if cs.valid and cs.cv_mps else None
    hr, hr_issues = threshold_hr(window, hr_max)
    if hr is not None and hr <= hr_rest:
        hr_issues = [*hr_issues, f"Tętno progowe {hr} uderzeń/min nie przekracza tętna spoczynkowego {hr_rest}."]
        hr = None
    return Threshold(
        critical_speed=cs, pace_s_per_km=pace, hr_bpm=hr, hr_issues=hr_issues, window_days=days, warnings=warnings
    )
