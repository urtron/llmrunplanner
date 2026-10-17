import math
from abc import ABC, abstractmethod
from collections.abc import Mapping
from typing import Any, ClassVar, Literal

from ...domain import Distance, RuleKind, Violation


def fmt(value: float, digits: int = 1) -> str:
    """Liczba z polskim przecinkiem dziesiętnym."""
    return f"{value:.{digits}f}".replace(".", ",")


def _tenths(value: float) -> float:
    return round(value * 10, 6)


def fmt_max_km(value: float) -> str:
    """Górny limit w km, zaokrąglony w dół do 0,1: stosując podaną liczbę, nie przekroczy się limitu."""
    return fmt(math.floor(_tenths(value)) / 10)


def fmt_min_km(value: float) -> str:
    """Dolny limit w km, zaokrąglony w górę do 0,1: stosując podaną liczbę, nie zejdzie się poniżej limitu."""
    return fmt(math.ceil(_tenths(value)) / 10)


def pct_of(part: float, whole: float) -> float:
    """Procent zaokrąglony do 6 miejsc, żeby wartość równa limitowi nie przekraczała go przez błąd zmiennoprzecinkowy."""
    return round(100 * part / whole, 6)


def _fmt_pct(value: float) -> str:
    return fmt(value, 1).removesuffix(",0")


def fmt_pct_over(value: float) -> str:
    """Procent przekraczający limit górny, zaokrąglony w górę do 0,1, by nie wyglądał na równy limitowi."""
    return _fmt_pct(math.ceil(_tenths(value)) / 10)


def fmt_pct_under(value: float) -> str:
    """Procent poniżej limitu dolnego, zaokrąglony w dół do 0,1, by nie wyglądał na równy limitowi."""
    return _fmt_pct(math.floor(_tenths(value)) / 10)


def is_deload(previous_km: float, km: float, min_drop_pct: float) -> bool:
    """Tydzień odciążający: objętość niższa o co najmniej `min_drop_pct`% od poprzedniego Tygodnia."""
    return km <= round(previous_km * (1 - min_drop_pct / 100), 6)


def days_word(n: int) -> str:
    """dzień/dni zgodnie z liczbą."""
    return "dzień" if n == 1 else "dni"


def weeks_word(n: int) -> str:
    """Tydzień/Tygodnie/Tygodni zgodnie z liczbą."""
    if n == 1:
        return "Tydzień"
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return "Tygodnie"
    return "Tygodni"


def weeks_label(first: int, last: int) -> str:
    return f"Tydzień {first}" if first == last else f"Tygodnie {first}–{last}"


class Rule(ABC):
    id: ClassVar[str]
    level: ClassVar[Literal["skeleton", "week"]]
    kind: ClassVar[Literal["hard", "soft", "soft_then_hard"]]
    required_thresholds: ClassVar[tuple[str, ...]] = ()
    distance_thresholds: ClassVar[tuple[str, ...]] = ()  # progi zapisane osobno dla każdego dystansu

    def __init__(self, thresholds: Mapping[str, Any]) -> None:
        missing = [k for k in self.required_thresholds if k not in thresholds]
        if missing:
            raise ValueError(f"Reguła {self.id}: brakuje progów {missing}.")
        codes = [d.value for d in Distance]
        for name in self.distance_thresholds:
            value = thresholds.get(name)
            absent = codes if not isinstance(value, Mapping) else [c for c in codes if c not in value]
            if absent:
                raise ValueError(f"Reguła {self.id}: próg {name} nie ma wartości dla dystansów {absent}.")
        self.thresholds = thresholds

    @abstractmethod
    def check(self, ctx: Any) -> list[Violation]: ...

    def for_distance(self, name: str, distance: Distance) -> Any:
        """Próg zapisany w YAML osobno dla każdego dystansu (klucze 5K/10K/HM/M)."""
        return self.thresholds[name][distance.value]

    def violation(self, kind: RuleKind, location: str, message: str, message_for_model: str) -> Violation:
        return Violation(
            rule_id=self.id, kind=kind, location=location, message=message, message_for_model=message_for_model
        )

    def hard(self, location: str, message: str, message_for_model: str) -> Violation:
        return self.violation(RuleKind.HARD, location, message, message_for_model)

    def soft(self, location: str, message: str, message_for_model: str) -> Violation:
        return self.violation(RuleKind.SOFT, location, message, message_for_model)

    @staticmethod
    def graded_above(value: float, warn: float, error: float) -> RuleKind | None:
        """Rodzaj Naruszenia progu górnego: powyżej `error` twarde, powyżej `warn` miękkie."""
        if value > error:
            return RuleKind.HARD
        if value > warn:
            return RuleKind.SOFT
        return None

    @staticmethod
    def graded_below(value: float, warn: float, error: float) -> RuleKind | None:
        """Rodzaj Naruszenia progu dolnego: poniżej `error` twarde, poniżej `warn` miękkie."""
        if value < error:
            return RuleKind.HARD
        if value < warn:
            return RuleKind.SOFT
        return None
