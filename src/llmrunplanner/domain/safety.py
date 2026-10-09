from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .enums import GateStatus

_Date = date

_CONFIG = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)


class HealthQuestion(BaseModel):
    """Pytanie Ankiety zdrowotnej; odpowiedź twierdząca wstrzymuje Plan."""

    model_config = _CONFIG

    id: str = Field(description="Identyfikator pytania Ankiety zdrowotnej.")
    text: str = Field(description="Treść pytania; odpowiedź twierdząca zaleca konsultację lekarską.")


class GateProposal(BaseModel):
    """Propozycja Bramki: realny czas docelowy albo późniejsza data startu; decyzję podejmuje Biegacz."""

    model_config = _CONFIG

    kind: Literal["target_time", "race_date"] = Field(description="Rodzaj propozycji.")
    target_time_s: int | None = Field(default=None, description="Proponowany czas docelowy [s].")
    race_date: _Date | None = Field(default=None, description="Proponowana data startu.")
    text: str = Field(description="Opis propozycji.")

    @model_validator(mode="after")
    def _fields_match_kind(self) -> "GateProposal":
        if self.kind == "race_date" and self.race_date is None:
            raise ValueError("Propozycja rodzaju race_date wymaga daty startu.")
        if self.kind == "target_time" and self.target_time_s is None:
            raise ValueError("Propozycja rodzaju target_time wymaga czasu docelowego.")
        return self


class GateResult(BaseModel):
    """Wynik Bramki bezpieczeństwa: status, powody zatrzymania, ostrzeżenia i propozycje zmiany Celu."""

    model_config = _CONFIG

    status: GateStatus = Field(description="Wynik Bramki.")
    reasons: list[str] = Field(description="Powody zatrzymania.")
    warnings: list[str] = Field(description="Ostrzeżenia.")
    proposals: list[GateProposal] = Field(description="Propozycje zmiany Celu.")
    weeks: int = Field(description="Liczba Tygodni Planu do startu.")
    predicted_time_s: int | None = Field(description="Prognoza czasu na dystansie Celu [s]; brak, gdy nie do policzenia.")
