from collections import defaultdict
from collections.abc import Callable
from datetime import date, timedelta
from statistics import median

from ..domain import (
    Activity,
    ActivityMetrics,
    Athlete,
    AthleteMetrics,
    BestEffortSummary,
    DailyLoad,
    Distance,
    HistorySummary,
    LongRun,
    PredictionSummary,
    TrendPoint,
    WeekVolume,
    Zone,
)
from ..metrics import SEILER_ZONE, fitness, monotony
from .params import AGE_RANGE_WIDTH, DECOUPLING_OUTLIER_PCT, SUMMARY_WEEKS, TREND_BLOCK_WEEKS, TREND_MIN_N

_SEILER_NAMES = {1: "low", 2: "moderate", 3: "high"}
_OPTIMISTIC_EXPONENT = 1.06
_CONSERVATIVE_EXPONENT = 1.10


def build_history_summary(
    athlete: Athlete,
    activities: list[Activity],
    metrics: AthleteMetrics,
    daily: list[DailyLoad],
    as_of: date,
) -> HistorySummary:
    if as_of < metrics.data_cutoff:
        raise ValueError(f"Dzień stanu {as_of} jest wcześniejszy niż Data odcięcia {metrics.data_cutoff}.")
    if not daily:
        raise ValueError("Dzienne obciążenie jest puste.")
    if any(d.date >= as_of for d in daily):
        raise ValueError(f"Dzienne obciążenie zawiera dni nie wcześniejsze niż Dzień stanu {as_of}.")
    for prev, cur in zip(daily, daily[1:]):
        if cur.date != prev.date + timedelta(days=1):
            raise ValueError(
                f"Dzienne obciążenie nie jest ciągłe ani posortowane: po {prev.date} następuje {cur.date}."
            )
    if daily[-1].date != as_of - timedelta(days=1):
        raise ValueError(f"Dzienne obciążenie musi kończyć się dniem {as_of - timedelta(days=1)}, kończy się {daily[-1].date}.")
    if not activities:
        raise ValueError("Brak Aktywności.")
    if any(a.local_date >= metrics.data_cutoff for a in activities):
        raise ValueError(f"Aktywności zawierają dni nie wcześniejsze niż Data odcięcia {metrics.data_cutoff}.")
    if metrics.daily and daily[0].date != metrics.daily[0].date:
        raise ValueError(
            f"Dzienne obciążenie zaczyna się {daily[0].date}, a w metrykach {metrics.daily[0].date}: "
            "inicjalizacja CTL zależy od początku szeregu."
        )

    by_day = {d.date: d for d in daily}
    acts_by_day: dict[date, list[Activity]] = defaultdict(list)
    for a in activities:
        acts_by_day[a.local_date].append(a)

    # blok k obejmuje [as_of − 7k, as_of − 7(k−1)); pomijamy bloki w całości sprzed historii
    first_day = daily[0].date
    weekly: list[WeekVolume] = []
    long_runs: list[LongRun] = []
    for k in range(SUMMARY_WEEKS, 0, -1):
        start = as_of - timedelta(days=7 * k)
        days = [by_day[d] for d in (start + timedelta(days=i) for i in range(7)) if d in by_day]
        if start + timedelta(days=7) <= first_day:
            continue
        runs = 0
        candidates: list[tuple[float, LongRun]] = []
        for day in days:
            acts = acts_by_day.get(day.date)
            if acts:
                runs += len(acts)
                candidates += [
                    (
                        a.distance_m,
                        LongRun(date=day.date, distance_km=round(a.distance_m / 1000, 1), duration_min=round(a.duration_s / 60)),
                    )
                    for a in acts
                ]
            elif day.trained:
                runs += 1
                candidates.append(
                    (day.km * 1000, LongRun(date=day.date, distance_km=round(day.km, 1), duration_min=round(day.minutes)))
                )
        weekly.append(
            WeekVolume(
                week_start=start,
                distance_km=round(sum(d.km for d in days), 1),
                duration_min=round(sum(d.minutes for d in days)),
                trimp=round(sum(d.trimp for d in days)),
                runs=runs,
            )
        )
        if candidates:
            long_runs.append(max(candidates, key=lambda c: c[0])[1])

    avg_4w = round(
        sum(d.km for d in daily if as_of - timedelta(days=28) <= d.date < as_of) / 4, 1
    )

    window_start = as_of - timedelta(days=7 * SUMMARY_WEEKS)
    zone_minutes: dict[Zone, float] = {z: 0.0 for z in Zone}
    for d in daily:
        if d.date >= window_start:
            for z, m in d.zone_minutes.items():
                zone_minutes[z] += m
    seiler_minutes = dict.fromkeys(_SEILER_NAMES.values(), 0.0)
    for z, m in zone_minutes.items():
        seiler_minutes[_SEILER_NAMES[SEILER_ZONE[z]]] += m

    pace_seconds: dict[Zone, float] = {z: 0.0 for z in Zone}
    has_pace = False
    for m in metrics.activities:
        if window_start <= m.date < as_of and m.zone_seconds_pace is not None:
            has_pace = True
            for z, sec in m.zone_seconds_pace.items():
                pace_seconds[z] += sec
    pace_seiler = dict.fromkeys(_SEILER_NAMES.values(), 0.0)
    for z, sec in pace_seconds.items():
        pace_seiler[_SEILER_NAMES[SEILER_ZONE[z]]] += sec
    pace_pct = _percents(pace_seconds) if has_pace and sum(pace_seconds.values()) > 0 else {}
    pace_seiler_pct = _percents(pace_seiler) if pace_pct else {}

    point = fitness(daily)[-1]
    mono, strain = monotony([d.trimp for d in daily[-7:]]) if len(daily) >= 7 else (None, None)

    th = metrics.threshold
    return HistorySummary(
        data_cutoff=metrics.data_cutoff,
        as_of=as_of,
        age_range=_age_range(as_of.year - athlete.birth_year),
        history_start=min(a.local_date for a in activities),
        weekly_volumes=weekly,
        long_runs=long_runs,
        avg_weekly_km_last_4w=avg_4w,
        zone_distribution_hr_pct=_percents(zone_minutes),
        intensity_distribution_seiler_hr_pct=_percents(seiler_minutes),
        zone_distribution_pace_pct=pace_pct,
        intensity_distribution_seiler_pace_pct=pace_seiler_pct,
        ctl=round(point.ctl, 1),
        atl=round(point.atl, 1),
        tsb=round(point.tsb, 1),
        monotony_last_7d=None if mono is None else round(mono, 2),
        strain_last_7d=None if strain is None else round(strain),
        threshold_pace_s_per_km=None if th.pace_s_per_km is None else round(th.pace_s_per_km),
        threshold_hr_bpm=th.hr_bpm,
        threshold_window_days=th.window_days,
        threshold_warnings=list(th.warnings),
        hr_max_bpm=metrics.hr_profile.hr_max,
        hr_rest_bpm=metrics.hr_profile.hr_rest,
        ef_trend=_trend(metrics.activities, metrics.data_cutoff, lambda m: m.ef, 3),
        decoupling_trend_pct=_trend(metrics.activities, metrics.data_cutoff, _clean_decoupling, 1),
        best_efforts=[
            BestEffortSummary(
                duration_s=e.duration_s, pace_s_per_km=round(e.duration_s / e.distance_m * 1000), date=e.date
            )
            for e in th.critical_speed.efforts
        ],
        race_predictions=_predictions(metrics),
    )


def _age_range(age: int) -> str:
    low = age // AGE_RANGE_WIDTH * AGE_RANGE_WIDTH
    return f"{low}–{low + AGE_RANGE_WIDTH - 1}"


def _clean_decoupling(m: ActivityMetrics) -> float | None:
    if not m.is_steady or m.decoupling_pct is None or abs(m.decoupling_pct) > DECOUPLING_OUTLIER_PCT:
        return None
    return m.decoupling_pct


def _percents[K](amounts: dict[K, float]) -> dict[K, int]:
    """Udziały w całkowitych procentach o sumie dokładnie 100 (metoda największych reszt); same zera, gdy brak danych."""
    total = sum(amounts.values())
    if total <= 0:
        return dict.fromkeys(amounts, 0)
    raw = {k: v / total * 100 for k, v in amounts.items()}
    result = {k: int(r) for k, r in raw.items()}
    leftover = 100 - sum(result.values())
    for k in sorted(raw, key=lambda k: raw[k] - result[k], reverse=True)[:leftover]:
        result[k] += 1
    return result


def _trend(
    activities: list[ActivityMetrics], cutoff: date, value: Callable[[ActivityMetrics], float | None], digits: int
) -> list[TrendPoint]:
    block_days = 7 * TREND_BLOCK_WEEKS
    points = []
    for j in range(SUMMARY_WEEKS // TREND_BLOCK_WEEKS, 0, -1):
        start = cutoff - timedelta(days=block_days * j)
        end = start + timedelta(days=block_days)
        values = [v for m in activities if start <= m.date < end and (v := value(m)) is not None]
        if len(values) >= TREND_MIN_N:
            points.append(TrendPoint(period_start=start, value=round(median(values), digits), n=len(values)))
    return points


def _predictions(metrics: AthleteMetrics) -> list[PredictionSummary]:
    by_key = {(p.distance, round(p.exponent, 2)): p.time_s for p in metrics.predictions}
    return [
        PredictionSummary(
            distance=d,
            time_s_optimistic=round(by_key[(d, _OPTIMISTIC_EXPONENT)]),
            time_s_conservative=round(by_key[(d, _CONSERVATIVE_EXPONENT)]),
        )
        for d in Distance
        if (d, _OPTIMISTIC_EXPONENT) in by_key and (d, _CONSERVATIVE_EXPONENT) in by_key
    ]
