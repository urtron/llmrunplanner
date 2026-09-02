from pydantic import BaseModel, ConfigDict, Field

from .enums import RuleKind


class Violation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)

    rule_id: str = Field(description="Identyfikator Reguły, np. T4.")
    kind: RuleKind = Field(description="Rodzaj Naruszenia: twarde lub miękkie.")
    location: str = Field(description="Miejsce Naruszenia, np. 'Tydzień 3, dzień 2'.")
    message: str = Field(description="Opis Naruszenia dla człowieka.")
    message_for_model: str = Field(description="Opis Naruszenia do prompta Poprawki.")
