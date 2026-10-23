from pydantic import BaseModel, ConfigDict, Field

_CONFIG = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)


class Citation(BaseModel):
    """Cytowanie: liczba z tekstu stwierdzenia i ścieżka pola Podsumowania historii, z którego pochodzi."""

    model_config = _CONFIG

    field: str = Field(
        description="Ścieżka pola w JSON Podsumowania historii: klucze rozdzielone kropkami, element listy wybrany "
        "wartością pola-klucza w nawiasach kwadratowych, np. ctl, zone_distribution_hr_pct.Z1, "
        "weekly_volumes[week_start=2024-08-25].distance_km."
    )
    value: float = Field(description="Liczba dokładnie tak, jak w polu Podsumowania historii.")


class Statement(BaseModel):
    """Stwierdzenie o Historii treningowej Biegacza z cytowaniami liczb."""

    model_config = _CONFIG

    text: str = Field(description="Stwierdzenie po polsku, 1–3 zdania.")
    citations: list[Citation] = Field(
        description="Cytowania wszystkich liczb z tekstu, które pochodzą z Podsumowania historii; pusta lista, "
        "gdy tekst nie zawiera takich liczb."
    )


class Interpretation(BaseModel):
    """Interpretacja: opis Historii treningowej Biegacza na potrzeby Planu."""

    model_config = _CONFIG

    trends: list[Statement] = Field(
        min_length=1, max_length=3, description="Trendy objętości, obciążenia i wydolności tlenowej (1–3)."
    )
    strengths: list[Statement] = Field(min_length=1, max_length=3, description="Mocne strony Biegacza (1–3).")
    weaknesses: list[Statement] = Field(min_length=1, max_length=3, description="Słabe strony Biegacza (1–3).")
    risks: list[Statement] = Field(
        min_length=1, max_length=3, description="Ryzyka dla przygotowań, także ograniczenia samych danych (1–3)."
    )
    readiness: Statement = Field(description="Gotowość do Celu w dostępnym czasie.")


class CitationCheck(BaseModel):
    """Wynik sprawdzenia jednego cytowania z Podsumowaniem historii."""

    model_config = _CONFIG

    field: str = Field(description="Cytowana ścieżka pola.")
    cited: float = Field(description="Liczba podana przez model.")
    actual: float | None = Field(description="Wartość pola w Podsumowaniu historii; brak, gdy pole nie istnieje lub nie jest liczbą.")
    ok: bool = Field(description="Czy liczba zgadza się z Podsumowaniem w granicach tolerancji.")
    reason: str | None = Field(description="Przyczyna niezgodności; brak, gdy zgodne.")


class InterpretationCheck(BaseModel):
    """Zgodność liczb Interpretacji z Podsumowaniem historii."""

    model_config = _CONFIG

    total: int = Field(ge=0, description="Liczba cytowań.")
    matched: int = Field(ge=0, description="Liczba cytowań zgodnych z Podsumowaniem.")
    checks: list[CitationCheck] = Field(description="Wynik dla każdego cytowania, w kolejności występowania.")
    uncited: list[str] = Field(
        description="Liczby z tekstów stwierdzeń bez pasującego cytowania, w kolejności występowania."
    )
