import re
from datetime import UTC, date, datetime, timedelta
from typing import Annotated, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .enums import ActivitySource, GarminMetricKind, Sex, SubSport, Zone

_Date = date  # pole "date" przesłania typ w ciele klasy
_SHA256_RE = re.compile(r"[0-9a-f]{64}")


class Athlete(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)

    id: str = Field(description="Losowy identyfikator Biegacza.")
    label: str = Field(description="Pseudonim Biegacza (bez imienia i nazwiska).")
    source: ActivitySource = Field(description="Źródło danych Biegacza.")
    sex: Sex = Field(description="Płeć Biegacza.")
    birth_year: int = Field(ge=1920, le=2015, description="Rok urodzenia.")
    hr_rest_override: int | None = Field(
        default=None, ge=25, le=120, description="Ręcznie podane tętno spoczynkowe [uderzenia/min]."
    )
    hr_max_override: int | None = Field(
        default=None, ge=120, le=230, description="Ręcznie podane tętno maksymalne [uderzenia/min]."
    )


class Samples(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)

    t_s: list[int] = Field(description="Czas zegarowy od startu Aktywności [s], wraz z pauzami (pauzy widać jako luki w szeregu).")
    hr: list[int | None] = Field(description="Tętno [uderzenia/min].")
    speed_mps: list[float | None] = Field(description="Prędkość [m/s].")
    distance_m: list[float | None] = Field(description="Dystans narastający [m].")
    altitude_m: list[float | None] = Field(description="Wysokość [m n.p.m.].")
    cadence: list[int | None] = Field(
        description="Kadencja jednej nogi jak w FIT, czyli połowa liczby kroków na minutę."
    )

    @model_validator(mode="after")
    def _check_series(self) -> Self:
        n = len(self.t_s)
        for name in ("hr", "speed_mps", "distance_m", "altitude_m", "cadence"):
            if len(getattr(self, name)) != n:
                raise ValueError(f"Szereg '{name}' ma inną długość niż 't_s'.")
        if any(b < a for a, b in zip(self.t_s, self.t_s[1:])):
            raise ValueError("Szereg 't_s' musi być niemalejący.")
        return self


class Activity(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)

    id: str = Field(description="Identyfikator Aktywności.")
    athlete_id: str = Field(description="Identyfikator Biegacza.")
    source: ActivitySource = Field(description="Źródło Aktywności.")
    start_time: datetime = Field(description="Czas startu w UTC (wymagana strefa czasowa).")
    utc_offset_s: int = Field(
        ge=-50400, le=50400, description="Przesunięcie czasu lokalnego względem UTC [s]."
    )
    duration_s: int = Field(ge=1, description="Czas pracy zegarka bez pauz [s].")
    distance_m: float = Field(ge=0, description="Dystans [m].")
    sub_sport: SubSport = Field(description="Rodzaj biegu.")
    has_hr: bool = Field(description="Czy Aktywność ma pomiar tętna.")
    has_gps: bool = Field(description="Czy Aktywność ma dane GPS.")
    garmin_activity_id: str | None = Field(
        default=None, description="Identyfikator Aktywności w Garmin Connect."
    )
    file_hash: str | None = Field(
        default=None, description="Skrót SHA-256 pliku (64 małe znaki szesnastkowe)."
    )

    @field_validator("start_time")
    @classmethod
    def _to_utc(cls, v: datetime) -> datetime:
        if v.tzinfo is None or v.utcoffset() is None:
            raise ValueError("Czas startu musi mieć strefę czasową.")
        return v.astimezone(UTC)

    @field_validator("file_hash")
    @classmethod
    def _check_hash(cls, v: str | None) -> str | None:
        if v is not None and not _SHA256_RE.fullmatch(v):
            raise ValueError("Skrót pliku musi mieć 64 małe znaki szesnastkowe (SHA-256).")
        return v

    @property
    def local_start(self) -> datetime:
        return (self.start_time + timedelta(seconds=self.utc_offset_s)).replace(tzinfo=None)

    @property
    def local_date(self) -> date:
        return self.local_start.date()

    @property
    def counts_for_performance(self) -> bool:
        return self.sub_sport != SubSport.TREADMILL and self.has_gps


class DailyLoad(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)

    date: _Date = Field(description="Dzień.")
    km: float = Field(ge=0, description="Dystans dnia [km].")
    minutes: float = Field(ge=0, description="Czas treningu dnia [min].")
    trimp: float = Field(ge=0, description="TRIMP dnia.")
    zone_minutes: dict[Zone, Annotated[float, Field(ge=0)]] = Field(
        default_factory=dict, description="Minuty w poszczególnych Strefach."
    )
    trained: bool = Field(description="Czy tego dnia był trening.")


class GarminMetric(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)

    athlete_id: str = Field(description="Identyfikator Biegacza.")
    date: _Date = Field(description="Dzień pomiaru.")
    kind: GarminMetricKind = Field(description="Rodzaj wskaźnika Garmina.")
    value: float = Field(description="Wartość w jednostce podanej przez Garmina.")
