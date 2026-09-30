from datetime import date

from ..domain import Activity, ActivityMetrics, Athlete, AthleteMetrics, GarminMetric, Samples
from .aerobic import decoupling, efficiency_factor, is_steady
from .garmin_compare import garmin_comparison
from .hr_quality import heart_rate_profile, hr_max_from_data, sample_dt, valid_hr_mask
from .load import daily_load, fitness, hrtss, trimp
from .prediction import race_predictions
from .threshold import estimate_threshold
from .zones import time_in_zones_hr, time_in_zones_pace, zone_bounds


def compute_athlete_metrics(
    athlete: Athlete,
    activities: list[Activity],
    samples: dict[str, Samples],
    garmin: list[GarminMetric],
    data_cutoff: date,
) -> AthleteMetrics:
    for a in activities:
        if a.local_date >= data_cutoff:
            raise ValueError(f"Aktywność {a.id} z dnia {a.local_date} nie jest wcześniejsza niż Data odcięcia {data_cutoff}.")
        if a.id not in samples:
            raise ValueError(f"Brak próbek dla Aktywności {a.id}.")
    ordered = sorted(activities, key=lambda a: a.start_time)
    masks = {a.id: valid_hr_mask(samples[a.id]) for a in ordered}

    hr_max = hr_max_from_data((samples[a.id], masks[a.id]) for a in ordered)
    profile = heart_rate_profile(athlete, hr_max, garmin, data_cutoff)
    threshold = estimate_threshold([(a, samples[a.id], masks[a.id]) for a in ordered], profile.hr_max, profile.hr_rest, data_cutoff)
    zones = zone_bounds(threshold)

    metrics: dict[str, ActivityMetrics] = {}
    for a in ordered:
        s, mask = samples[a.id], masks[a.id]
        dt = sample_dt(s)
        total = float(dt.sum())
        steady = is_steady(a, s, mask, zones) if zones else False
        metrics[a.id] = ActivityMetrics(
            activity_id=a.id,
            date=a.local_date,
            trimp=trimp(s, mask, profile, athlete.sex),
            hrtss=hrtss(s, mask, profile.hr_rest, threshold.hr_bpm) if threshold.hr_bpm is not None else None,
            hr_valid_share=float(dt[mask].sum()) / total if total > 0 else 0.0,
            zone_seconds_hr=time_in_zones_hr(s, mask, zones) if zones else {},
            zone_seconds_pace=time_in_zones_pace(a, s, zones) if zones else None,
            ef=efficiency_factor(a, s, mask, zones) if zones else None,
            is_steady=steady,
            decoupling_pct=decoupling(s, mask, steady) if zones else None,
        )

    predictions = race_predictions(threshold.critical_speed)
    daily = daily_load(ordered, metrics, ordered[0].local_date, data_cutoff) if ordered else []
    return AthleteMetrics(
        data_cutoff=data_cutoff,
        hr_profile=profile,
        threshold=threshold,
        zones=zones,
        activities=[metrics[a.id] for a in ordered],
        daily=daily,
        load=fitness(daily),
        predictions=predictions,
        garmin_comparison=garmin_comparison(threshold, profile, predictions, garmin, data_cutoff),
    )
