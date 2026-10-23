from datetime import date, datetime
from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from .validation import Violation


class ModelSpec(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)

    key: str = Field(description="Klucz modelu w rejestrze.")
    provider: Literal["anthropic", "openrouter"] = Field(description="Dostawca, przez którego wywołuje się model.")
    model_id: str = Field(description="Identyfikator modelu u dostawcy.")
    price_in_usd_per_mtok: float = Field(ge=0, description="Cena wejścia, USD za 1 mln tokenów.")
    price_out_usd_per_mtok: float = Field(ge=0, description="Cena wyjścia, USD za 1 mln tokenów.")
    label: str = Field(description="Nazwa modelu w interfejsie.")


class CallRecord(BaseModel):
    """Jedno wywołanie modelu w logu przebiegu."""

    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)

    run_id: str = Field(description="Identyfikator przebiegu.")
    plan_id: str | None = Field(description="Identyfikator Planu, jeśli już istnieje.")
    athlete_id: str = Field(description="Identyfikator Biegacza.")
    step: Literal["interpretation", "skeleton", "week"] = Field(description="Krok grafu.")
    week_number: int | None = Field(description="Numer Tygodnia dla kroku week.")
    attempt: int = Field(ge=0, description="0 to pierwsza próba, 1–2 to Poprawki.")
    model_key: str = Field(description="Klucz modelu w rejestrze.")
    model_id: str = Field(description="Identyfikator modelu u dostawcy.")
    prompt_version: str = Field(
        description="Skrót pliku szablonu i wariant; w Poprawce z dopiskiem +repair: i wersją szablonu Poprawki."
    )
    schema_hash: str = Field(description="Skrót schematu odpowiedzi.")
    summary_hash: str = Field(description="Skrót Podsumowania historii.")
    context_hash: str = Field(description="Skrót rules.yaml, workout_catalog.yaml i legendy Podsumowania historii.")
    as_of: date = Field(description="Dzień stanu.")
    input_tokens: int | None = Field(ge=0, description="Liczba tokenów wejścia; brak, gdy dostawca jej nie podał.")
    output_tokens: int | None = Field(ge=0, description="Liczba tokenów wyjścia; brak, gdy dostawca jej nie podał.")
    reasoning_tokens: int | None = Field(ge=0, description="Tokeny rozumowania wliczone do wyjścia, jeśli dostawca je podaje.")
    cost_usd: float | None = Field(ge=0, description="Koszt wywołania w USD; brak, gdy nie znamy liczby tokenów.")
    latency_ms: int = Field(ge=0, description="Czas wywołania w milisekundach.")
    stop_reason: str | None = Field(description="Powód zakończenia odpowiedzi podany przez dostawcę.")
    output_json: str | None = Field(description="Argumenty wywołania narzędzia zwrócone przez model.")
    parse_error: str | None = Field(description="Błąd parsowania odpowiedzi, jeśli wystąpił.")
    format_errors: list[str] = Field(description="Błędy formatu wykryte w sparsowanej odpowiedzi.")
    violations: list[Violation] = Field(description="Naruszenia wykryte w tej próbie.")
    created_at: AwareDatetime = Field(description="Czas zapisu (UTC).")


class PlanRecord(BaseModel):
    """Wiersz tabeli plan; kolumny JSON jako tekst."""

    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)

    id: str
    run_id: str
    athlete_id: str
    data_cutoff: date
    as_of: date
    goal_json: str
    model_key: str
    status: Literal["ok", "niezatwierdzony", "błąd API"]
    error: str | None = None
    gate_json: str
    interpretation_json: str | None = None
    interpretation_check_json: str | None = None
    skeleton_json: str | None = None
    skeleton_status: str | None = None
    skeleton_violations_json: str | None = None
    skeleton_format_errors_json: str | None = None
    week_json: str | None = None
    week_status: str | None = None
    week_violations_json: str | None = None
    week_format_errors_json: str | None = None
    created_at: AwareDatetime
