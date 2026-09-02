from datetime import date
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .enums import Distance, Phase, WorkoutType, Zone


class Goal(BaseModel):
    """Cel: bieg uliczny na wybranym dystansie w danym dniu."""

    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)

    distance: Distance = Field(description="Dystans startu.")
    race_date: date = Field(description="Data startu.")
    target_time_s: int | None = Field(
        default=None, ge=1, description="Docelowy czas [s]; brak, jeśli Biegacz go nie podał."
    )


class Segment(BaseModel):
    """Segment: odcinek biegu w jednej Strefie."""

    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)

    zone: Zone = Field(description="Strefa intensywności odcinka.")
    distance_m: int = Field(ge=1, description="Długość odcinka [m].")


class Block(BaseModel):
    """Blok: 1-4 Segmenty powtórzone `repeat` razy; rozgrzewka i schłodzenie to Bloki z repeat = 1.

    Przerwę między powtórzeniami zapisuje się jako Segment truchtu w Z1 z dystansem w metrach,
    np. 6×(1000 m Z4, 400 m Z1).
    """

    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)

    repeat: int = Field(ge=1, le=30, description="Liczba powtórzeń Bloku.")
    segments: list[Segment] = Field(
        min_length=1, max_length=4, description="Segmenty w kolejności wykonania (1-4)."
    )


class Workout(BaseModel):
    """Jednostka: trening jednego dnia, złożony z Bloków."""

    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)

    day: int = Field(ge=1, le=7, description="Numer dnia w Tygodniu Planu, 1–7 (1 = pierwszy dzień Tygodnia, niekoniecznie poniedziałek; daty dni podaje prompt).")
    type: WorkoutType = Field(description="Typ Jednostki.")
    blocks: list[Block] = Field(min_length=1, description="Bloki w kolejności wykonania.")


class WeekDraft(BaseModel):
    """Tydzień: Jednostki rozpisane na 7 dni; dzień bez Jednostki jest wolny. Numer i Fazę dopisuje kod."""

    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)

    workouts: list[Workout] = Field(description="Jednostki Tygodnia, najwyżej jedna na dzień.")

    @field_validator("workouts")
    @classmethod
    def _unique_days(cls, workouts: list[Workout]) -> list[Workout]:
        seen: set[int] = set()
        for w in workouts:
            if w.day in seen:
                raise ValueError(f"Dzień {w.day} ma więcej niż jedną Jednostkę.")
            seen.add(w.day)
        return workouts


class SkeletonWeek(BaseModel):
    """Tydzień Szkieletu: Faza, docelowa objętość i Jednostki kluczowe."""

    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)

    number: int = Field(ge=1, description="Numer Tygodnia w Planie, od 1.")
    phase: Phase = Field(description="Faza Tygodnia.")
    target_volume_km: float = Field(gt=0, description="Docelowa objętość Tygodnia [km].")
    key_workouts: list[WorkoutType] = Field(
        description=(
            "Typy Jednostek kluczowych Tygodnia (jakościowe lub długie wybieganie); "
            "najwyżej 2 jakościowe i 1 długie wybieganie."
        )
    )

    @field_validator("key_workouts")
    @classmethod
    def _only_key(cls, types: list[WorkoutType]) -> list[WorkoutType]:
        for t in types:
            if not t.is_key:
                raise ValueError(f"Typ {t.value} nie jest Jednostką kluczową.")
        quality = sum(t.is_quality for t in types)
        long_runs = sum(t is WorkoutType.LONG for t in types)
        if quality > 2 or long_runs > 1:
            raise ValueError(
                f"Tydzień może mieć najwyżej 2 Jednostki jakościowe i 1 długie wybieganie "
                f"(otrzymano {quality} jakościowych i {long_runs} długich wybiegań)."
            )
        return types


class Skeleton(BaseModel):
    """Szkielet: Tygodnie Planu z Fazami, objętościami i Jednostkami kluczowymi."""

    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)

    weeks: list[SkeletonWeek] = Field(min_length=1, description="Tygodnie numerowane od 1 po kolei.")

    @model_validator(mode="after")
    def _consecutive_numbers(self) -> Self:
        if [w.number for w in self.weeks] != list(range(1, len(self.weeks) + 1)):
            raise ValueError(f"Numery Tygodni muszą być kolejnymi liczbami od 1, otrzymano {[w.number for w in self.weeks]}.")
        return self
