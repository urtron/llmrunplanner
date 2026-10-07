from datetime import date

from pydantic import BaseModel, ConfigDict, Field

from .enums import Distance, Zone

_Date = date  # pole "date" przesłania typ w ciele klasy

_CONFIG = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)


class WeekVolume(BaseModel):
    model_config = _CONFIG

    week_start: _Date = Field(description="Pierwszy dzień 7-dniowego bloku.")
    distance_km: float = Field(description="Dystans bloku [km].")
    duration_min: int = Field(description="Czas treningu w bloku [min].")
    trimp: int = Field(description="Suma TRIMP bloku.")
    runs: int = Field(description="Liczba biegów w bloku.")


class LongRun(BaseModel):
    model_config = _CONFIG

    date: _Date = Field(description="Dzień biegu.")
    distance_km: float = Field(description="Dystans biegu [km].")
    duration_min: int = Field(description="Czas biegu [min].")


class TrendPoint(BaseModel):
    model_config = _CONFIG

    period_start: _Date = Field(description="Pierwszy dzień okresu.")
    value: float = Field(
        description="Mediana wskaźnika w okresie (jednostka jak w nazwie pola nadrzędnego: EF w metrach na uderzenie serca "
        "(m/min ÷ ud./min), decoupling w %)."
    )
    n: int = Field(description="Liczba biegów w okresie.")


class BestEffortSummary(BaseModel):
    model_config = _CONFIG

    duration_s: int = Field(description="Czas odcinka [s].")
    pace_s_per_km: int = Field(description="Tempo na odcinku [s/km].")
    date: _Date = Field(description="Dzień odcinka.")


class PredictionSummary(BaseModel):
    model_config = _CONFIG

    distance: Distance = Field(description="Dystans startu.")
    time_s_optimistic: int = Field(description="Prognozowany czas, wykładnik Riegela 1,06 [s].")
    time_s_conservative: int = Field(description="Prognozowany czas, wykładnik Riegela 1,10 [s].")


class HistorySummary(BaseModel):
    """Podsumowanie historii treningowej: jedyne dane o Biegaczu widoczne dla modelu."""

    model_config = _CONFIG

    data_cutoff: _Date = Field(description="Data odcięcia, stała w całym przebiegu.")
    as_of: _Date = Field(description="Dzień stanu: początek planowanego Tygodnia.")
    age_range: str = Field(description="Przedział wieku Biegacza, np. 20–29.")
    history_start: _Date = Field(description="Dzień pierwszego biegu w danych.")
    weekly_volumes: list[WeekVolume] = Field(description="Objętości 7-dniowych bloków, od najstarszego.")
    long_runs: list[LongRun] = Field(description="Najdłuższy bieg każdego bloku, od najstarszego.")
    avg_weekly_km_last_4w: float = Field(description="Średnia tygodniowa objętość z ostatnich 4 bloków [km].")
    zone_distribution_hr_pct: dict[Zone, int] = Field(
        description="Udział czasu w Strefach tętna w oknie podsumowania [%, liczby całkowite]. Udziały z tętna zaniżają "
        "intensywność interwałów, bo tętno nie nadąża za krótkimi powtórzeniami."
    )
    intensity_distribution_seiler_hr_pct: dict[str, int] = Field(
        description="Udział czasu w 3 strefach Seilera (low, moderate, high) liczony ze Stref tętna [%]; "
        "zaniża intensywność interwałów, bo tętno opóźnia się względem wysiłku."
    )
    zone_distribution_pace_pct: dict[Zone, int] = Field(
        description="Udział czasu w Strefach tempa w oknie podsumowania [%, liczby całkowite]; obejmuje tylko biegi "
        "na zewnątrz z GPS, puste, gdy takich biegów brak."
    )
    intensity_distribution_seiler_pace_pct: dict[str, int] = Field(
        description="Udział czasu w 3 strefach Seilera (low, moderate, high) liczony ze Stref tempa [%]; obejmuje tylko "
        "biegi na zewnątrz z GPS, puste, gdy takich biegów brak."
    )
    ctl: float = Field(description="Obciążenie przewlekłe rano w dniu stanu.")
    atl: float = Field(description="Obciążenie ostre rano w dniu stanu.")
    tsb: float = Field(description="Równowaga obciążenia, CTL − ATL.")
    monotony_last_7d: float | None = Field(description="Monotonia Fostera z ostatnich 7 dni; brak, gdy nie do policzenia.")
    strain_last_7d: int | None = Field(description="Strain Fostera z ostatnich 7 dni; brak, gdy nie do policzenia.")
    threshold_pace_s_per_km: int | None = Field(description="Tempo progowe [s/km].")
    threshold_hr_bpm: int | None = Field(description="Tętno progowe [uderzenia/min].")
    threshold_window_days: int = Field(description="Długość okna, z którego wyznaczono Próg [dni].")
    threshold_warnings: list[str] = Field(description="Ostrzeżenia dotyczące wiarygodności Progu.")
    hr_max_bpm: int = Field(description="Tętno maksymalne [uderzenia/min].")
    hr_rest_bpm: int = Field(description="Tętno spoczynkowe [uderzenia/min].")
    ef_trend: list[TrendPoint] = Field(description="Trend wskaźnika EF w blokach 4-tygodniowych, od najstarszego.")
    decoupling_trend_pct: list[TrendPoint] = Field(
        description="Trend decouplingu [%] w blokach 4-tygodniowych, od najstarszego."
    )
    best_efforts: list[BestEffortSummary] = Field(description="Najlepsze odcinki z treningów użyte do wyznaczenia Progu; to prawdopodobnie wysiłki submaksymalne, "
        "a nie wyniki zawodów.")
    race_predictions: list[PredictionSummary] = Field(description="Prognozy czasów na dystansach startowych.")
