from datetime import date
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .activity import DailyLoad
from .enums import Distance, Zone

_Date = date  # pole "date" przesłania typ w ciele klasy

_CONFIG = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)


class HeartRateProfile(BaseModel):
    model_config = _CONFIG

    hr_max: int = Field(description="Tętno maksymalne [uderzenia/min].")
    hr_rest: int = Field(description="Tętno spoczynkowe [uderzenia/min].")
    hr_max_source: Literal["override", "data"] = Field(description="Skąd pochodzi tętno maksymalne.")
    hr_rest_source: Literal["override", "garmin", "default"] = Field(
        description="Skąd pochodzi tętno spoczynkowe."
    )

    @model_validator(mode="after")
    def _check_range(self) -> Self:
        if self.hr_max <= self.hr_rest:
            raise ValueError("Tętno maksymalne musi być większe od tętna spoczynkowego.")
        return self


class BestEffort(BaseModel):
    model_config = _CONFIG

    duration_s: int = Field(description="Czas odcinka [s].")
    distance_m: float = Field(description="Dystans przebiegnięty na odcinku [m].")
    activity_id: str = Field(description="Aktywność, z której pochodzi odcinek.")
    date: _Date = Field(description="Dzień Aktywności.")


class CriticalSpeed(BaseModel):
    model_config = _CONFIG

    cv_mps: float | None = Field(description="Prędkość krytyczna [m/s].")
    d_prime_m: float | None = Field(description="Zapas beztlenowy D′ [m].")
    r2: float | None = Field(description="Dopasowanie modelu (R²).")
    efforts: list[BestEffort] = Field(description="Najlepszy odcinek dla każdej długości użyty w dopasowaniu.")
    valid: bool = Field(description="Czy dopasowanie przeszło kontrole wiarygodności.")
    issues: list[str] = Field(description="Powody odrzucenia lub zastrzeżenia do dopasowania.")


class Threshold(BaseModel):
    model_config = _CONFIG

    critical_speed: CriticalSpeed = Field(description="Model prędkości krytycznej.")
    pace_s_per_km: float | None = Field(description="Tempo progowe [s/km], 1000 / prędkość krytyczna, gdy model wiarygodny.")
    hr_bpm: int | None = Field(description="Tętno progowe [uderzenia/min].")
    hr_issues: list[str] = Field(description="Zastrzeżenia do tętna progowego.")
    window_days: int = Field(description="Długość okna [dni], z którego wyznaczono Próg.")
    warnings: list[str] = Field(description="Ostrzeżenia dotyczące wiarygodności Progu.")


class ZoneBounds(BaseModel):
    model_config = _CONFIG

    zone: Zone = Field(description="Strefa.")
    hr_low: float | None = Field(description="Dolna granica tętna [uderzenia/min]; brak = otwarta.")
    hr_high: float | None = Field(description="Górna granica tętna [uderzenia/min]; brak = otwarta.")
    pace_fast_s_per_km: float | None = Field(description="Szybsza granica tempa [s/km]; brak = otwarta.")
    pace_slow_s_per_km: float | None = Field(description="Wolniejsza granica tempa [s/km]; brak = otwarta.")
    pace_mid_s_per_km: float = Field(description="Tempo reprezentatywne Strefy do przeliczenia dystansu na czas")


class ActivityMetrics(BaseModel):
    model_config = _CONFIG

    activity_id: str = Field(description="Identyfikator Aktywności.")
    date: _Date = Field(description="Dzień Aktywności.")
    trimp: float = Field(description="TRIMP Banistera sumowany po próbkach.")
    hrtss: float | None = Field(description="hrTSS względem tętna progowego.")
    hr_valid_share: float = Field(ge=0, le=1, description="Udział czasu z poprawnym tętnem (0–1).")
    zone_seconds_hr: dict[Zone, float] = Field(description="Sekundy w Strefach tętna.")
    zone_seconds_pace: dict[Zone, float] | None = Field(description="Sekundy w Strefach tempa; brak, gdy nie da się policzyć.")
    ef: float | None = Field(description="Wskaźnik efektywności (prędkość do tętna).")
    is_steady: bool = Field(description="Czy bieg jest równy (kwalifikuje się do decouplingu).")
    decoupling_pct: float | None = Field(description="Decoupling tętno–tempo [%].")


class LoadPoint(BaseModel):
    model_config = _CONFIG

    date: _Date = Field(description="Dzień.")
    ctl: float = Field(description="Obciążenie przewlekłe (średnia wykładnicza z 42 dni).")
    atl: float = Field(description="Obciążenie ostre (średnia wykładnicza z 7 dni).")
    tsb: float = Field(description="Równowaga obciążenia, CTL − ATL.")


class RacePrediction(BaseModel):
    model_config = _CONFIG

    distance: Distance = Field(description="Dystans startu.")
    exponent: float = Field(description="Wykładnik wzoru Riegela.")
    time_s: float = Field(description="Prognozowany czas [s].")


class GarminComparisonRow(BaseModel):
    model_config = _CONFIG

    name: str = Field(description="Nazwa wskaźnika.")
    unit: str = Field(description="Jednostka.")
    ours: float | None = Field(description="Wartość policzona w systemie.")
    garmin: float | None = Field(description="Wartość Garmina.")
    garmin_date: _Date | None = Field(description="Dzień wartości Garmina.")
    diff: float | None = Field(description="Różnica (nasza − Garmina), gdy obie wartości są dostępne.")


class AthleteMetrics(BaseModel):
    model_config = _CONFIG

    data_cutoff: _Date = Field(description="Data odcięcia.")
    hr_profile: HeartRateProfile = Field(description="Tętno maksymalne i spoczynkowe.")
    threshold: Threshold = Field(description="Próg.")
    zones: list[ZoneBounds] | None = Field(description="Granice Stref; brak, gdy brakuje tętna progowego lub prędkości krytycznej.")
    activities: list[ActivityMetrics] = Field(description="Wskaźniki Aktywności.")
    daily: list[DailyLoad] = Field(description="Dzienne obciążenie.")
    load: list[LoadPoint] = Field(description="CTL/ATL/TSB w kolejnych dniach.")
    predictions: list[RacePrediction] = Field(description="Prognozy czasów.")
    garmin_comparison: list[GarminComparisonRow] = Field(description="Porównanie z wartościami Garmina.")
