from collections.abc import Mapping
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field

from ..domain import RuleKind, Violation
from .context import SkeletonContext, WeekContext
from .rules.base import Rule
from .rules.skeleton import Deload, FirstWeekVolume, MinPhaseWeeks, PhaseOrder, Taper, WeeklyIncrease
from .rules.week import (
    KeyWorkoutCount,
    KeyWorkoutSpacing,
    LastKeyBeforeRace,
    LongRunLimits,
    LongRunShare,
    LowIntensityShare,
    RestDays,
    VolumeTarget,
)

RULE_CLASSES: dict[str, type[Rule]] = {
    cls.id: cls
    for cls in (
        PhaseOrder,
        MinPhaseWeeks,
        Taper,
        FirstWeekVolume,
        WeeklyIncrease,
        Deload,
        LongRunLimits,
        RestDays,
        KeyWorkoutSpacing,
        KeyWorkoutCount,
        LowIntensityShare,
        LongRunShare,
        VolumeTarget,
        LastKeyBeforeRace,
    )
}

# Reguły opisane w YAML, ale jeszcze bez klasy; pusta, bo wszystkie Reguły mają klasy.
PENDING_RULES: frozenset[str] = frozenset()


class RuleSpec(BaseModel):
    """Wpis Reguły z rules.yaml; opis trafia do prompta Poprawki i do Bazy wiedzy."""

    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)

    id: str = Field(description="Identyfikator Reguły, np. T4.")
    level: Literal["skeleton", "week"] = Field(description="Poziom sprawdzania: Szkielet lub Tydzień.")
    kind: Literal["hard", "soft", "soft_then_hard"] = Field(description="Rodzaj Naruszeń, jakie Reguła może zgłosić.")
    thresholds: Mapping[str, Any] = Field(description="Progi, także zagnieżdżone według dystansu (5K/10K/HM/M).")
    title: str = Field(description="Krótki tytuł Reguły.")
    description: str = Field(description="Co musi zrobić plan; pokazywane modelowi w Poprawce.")
    rationale: str = Field(description="Uzasadnienie Reguły.")
    source: str = Field(description="Źródło w literaturze.")


class RuleRegistry:
    def __init__(self, specs: dict[str, RuleSpec], rules: list[Rule]) -> None:
        self.specs = specs
        self._rules = rules

    def spec(self, rule_id: str) -> RuleSpec:
        return self.specs[rule_id]

    def validate_skeleton(self, ctx: SkeletonContext) -> list[Violation]:
        return self._run("skeleton", ctx)

    def validate_week(self, ctx: WeekContext) -> list[Violation]:
        return self._run("week", ctx)

    def _run(self, level: str, ctx: Any) -> list[Violation]:
        return [v for rule in self._rules if rule.level == level for v in rule.check(ctx)]

    @staticmethod
    def has_hard(violations: list[Violation]) -> bool:
        return any(v.kind is RuleKind.HARD for v in violations)

    def rule(self, rule_id: str) -> Rule:
        return next(r for r in self._rules if r.id == rule_id)


def volume_target_range(registry: RuleRegistry, target_km: float) -> tuple[str, str]:
    """Dozwolony zakres objętości Tygodnia (min, max w km z przecinkiem), ten sam, który sprawdza Reguła T6."""
    rule = registry.rule(VolumeTarget.id)
    assert isinstance(rule, VolumeTarget)
    return rule.range_km(target_km)


def load_rules(path: Path) -> RuleRegistry:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    specs: dict[str, RuleSpec] = {}
    for item in raw:
        spec = RuleSpec(**item)
        if spec.id in specs:
            raise ValueError(f"Reguła {spec.id} występuje w {path.name} więcej niż raz.")
        specs[spec.id] = spec
    for rule_id in RULE_CLASSES:
        if rule_id not in specs:
            raise ValueError(f"Reguła {rule_id} ma klasę, ale nie ma wpisu w {path.name}.")
    rules: list[Rule] = []
    for rule_id, spec in specs.items():
        cls = RULE_CLASSES.get(rule_id)
        if cls is None:
            if rule_id not in PENDING_RULES:
                raise ValueError(f"Reguła {rule_id} z {path.name} nie ma klasy.")
            continue
        if cls.level != spec.level:
            raise ValueError(f"Reguła {rule_id}: poziom {spec.level} w YAML, a {cls.level} w klasie.")
        if cls.kind != spec.kind:
            raise ValueError(f"Reguła {rule_id}: rodzaj {spec.kind} w YAML, a {cls.kind} w klasie.")
        rules.append(cls(spec.thresholds))
    return RuleRegistry(specs, rules)
