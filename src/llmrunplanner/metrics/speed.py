import numpy as np

from ..domain import Samples
from .params import EFFORT_MAX_STEP_SPEED_MPS, MAX_SAMPLE_GAP_S, SPEED_SMOOTH_S


def floats(values: list) -> np.ndarray:
    """Lista z brakami (None) jako tablica float z NaN."""
    return np.array([np.nan if v is None else v for v in values], dtype=float)


def moving_speed(samples: Samples) -> np.ndarray:
    """Prędkość [m/s] z przyrostu dystansu w centrowanym oknie SPEED_SMOOTH_S; NaN przy braku dystansu, luce lub skoku GPS."""
    t = np.asarray(samples.t_s, dtype=float)
    d = floats(samples.distance_m)
    n = len(t)
    out = np.full(n, np.nan)
    if n < 2:
        return out
    dt = np.diff(t)
    dd = np.diff(d)
    with np.errstate(invalid="ignore"):
        gap = dt > MAX_SAMPLE_GAP_S
        glitch = (dd < 0) | (dd > EFFORT_MAX_STEP_SPEED_MPS * np.maximum(dt, 1.0))
    c_gap = np.concatenate(([0], np.cumsum(gap)))
    c_glitch = np.concatenate(([0], np.cumsum(glitch)))

    half = SPEED_SMOOTH_S / 2
    lo = np.searchsorted(t, t - half, side="left")
    hi = np.searchsorted(t, t + half, side="right") - 1
    # luka sąsiadująca z oknem (krok wchodzący lub wychodzący) też przecina okno
    gap_lo = np.maximum(lo - 1, 0)
    gap_hi = np.minimum(hi, n - 2)
    gaps = c_gap[gap_hi + 1] - c_gap[gap_lo]
    glitches = c_glitch[hi] - c_glitch[lo]
    span = t[hi] - t[lo]
    ok = (hi > lo) & (span > 0) & (gaps == 0) & (glitches == 0) & ~np.isnan(d) & ~np.isnan(d[lo]) & ~np.isnan(d[hi])
    out[ok] = (d[hi] - d[lo])[ok] / span[ok]
    return out
