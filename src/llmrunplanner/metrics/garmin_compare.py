import math
from datetime import date

from ..domain import (
    Distance,
    GarminComparisonRow,
    GarminMetric,
    GarminMetricKind,
    HeartRateProfile,
    RacePrediction,
    Threshold,
)
from .params import COMPARISON_RIEGEL_EXPONENT, GARMIN_LT_SPEED_TO_MPS

_RACE_ROWS = (
    ("Prognoza 5 km", Distance.K5, GarminMetricKind.RACE_PRED_5K),
    ("Prognoza 10 km", Distance.K10, GarminMetricKind.RACE_PRED_10K),
    ("Prognoza półmaraton", Distance.HM, GarminMetricKind.RACE_PRED_HM),
    ("Prognoza maraton", Distance.M, GarminMetricKind.RACE_PRED_M),
)


def garmin_comparison(
    threshold: Threshold,
    profile: HeartRateProfile,
    predictions: list[RacePrediction],
    garmin: list[GarminMetric],
    data_cutoff: date,
) -> list[GarminComparisonRow]:
    last: dict[GarminMetricKind, GarminMetric] = {}
    for m in garmin:
        if m.date < data_cutoff and (m.kind not in last or m.date >= last[m.kind].date):
            last[m.kind] = m

    def row(name, unit, ours, kind, convert=lambda v: v) -> GarminComparisonRow:
        g = last.get(kind)
        value = None if g is None else convert(g.value)
        diff = ours - value if ours is not None and value is not None else None
        return GarminComparisonRow(
            name=name, unit=unit, ours=ours, garmin=value, garmin_date=None if g is None else g.date, diff=diff
        )

    pred = {p.distance: p.time_s for p in predictions if math.isclose(p.exponent, COMPARISON_RIEGEL_EXPONENT)}
    rows = [
        row("Tempo progowe", "s/km", threshold.pace_s_per_km, GarminMetricKind.LT_SPEED,
            lambda v: 1000 / (v * GARMIN_LT_SPEED_TO_MPS)),
        row("Tętno progowe", "uderzenia/min", threshold.hr_bpm, GarminMetricKind.LT_HR),
        row("Tętno spoczynkowe", "uderzenia/min", profile.hr_rest, GarminMetricKind.RESTING_HR),
    ]
    rows += [row(name, "s", pred.get(d), kind) for name, d, kind in _RACE_ROWS]
    rows.append(row("VO2max", "ml/kg/min", None, GarminMetricKind.VO2MAX))
    return rows
