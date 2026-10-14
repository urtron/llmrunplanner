from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field

from ..domain import WorkoutType, Zone


class CatalogEntry(BaseModel):
    """Wpis Katalogu jednostek; opis trafia do prompta modelu."""

    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)

    type: WorkoutType = Field(description="Typ Jednostki.")
    name: str = Field(description="Nazwa Typu po polsku.")
    quality: bool = Field(description="Czy to Jednostka jakościowa.")
    key: bool = Field(description="Czy to Jednostka kluczowa.")
    zones: list[Zone] = Field(description="Główne Strefy Jednostki.")
    description: str = Field(description="Cel i budowa Jednostki w Blokach i Strefach.")
    use: str = Field(description="W jakich Fazach i dla jakich dystansów stosować.")


def load_workout_catalog(path: Path) -> dict[WorkoutType, CatalogEntry]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    entries = [CatalogEntry(**item) for item in raw]
    catalog: dict[WorkoutType, CatalogEntry] = {}
    for e in entries:
        if e.type in catalog:
            raise ValueError(f"Typ {e.type.value} występuje w Katalogu więcej niż raz.")
        if e.quality != e.type.is_quality or e.key != e.type.is_key:
            raise ValueError(f"Typ {e.type.value}: flagi quality/key niezgodne z definicją Typu.")
        catalog[e.type] = e
    missing = set(WorkoutType) - set(catalog)
    if missing:
        raise ValueError(f"W Katalogu brakuje Typów: {sorted(t.value for t in missing)}.")
    return catalog
