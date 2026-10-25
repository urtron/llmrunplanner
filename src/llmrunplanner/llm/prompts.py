import hashlib
import json
from dataclasses import dataclass
from datetime import date, timedelta
from functools import cache
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from ..domain import (
    CalendarWeek,
    Goal,
    HistorySummary,
    Interpretation,
    RuleKind,
    Skeleton,
    SkeletonWeek,
    Statement,
    Violation,
    WorkoutType,
)
from ..config import KNOWLEDGE_BASE_DIR
from ..plan import CatalogEntry
from ..validator import RuleRegistry, volume_target_range

PROMPTS_DIR = Path(__file__).resolve().parents[3] / "prompts"
VARIANT = "FULL"

_WEEKDAYS = ("poniedziałek", "wtorek", "środa", "czwartek", "piątek", "sobota", "niedziela")


@dataclass(frozen=True)
class PromptTemplate:
    name: str
    text: str
    file_hash: str

    @property
    def version(self) -> str:
        return f"{self.file_hash}:{VARIANT}"

    def render(self, **values: Any) -> str:
        try:
            return self.text.format_map(values)
        except KeyError as e:
            raise KeyError(f"Szablon {self.name}: brak wartości dla {e.args[0]}.") from None


@cache
def load_prompt(name: str) -> PromptTemplate:
    raw = (PROMPTS_DIR / f"{name}.txt").read_bytes()
    return PromptTemplate(name=name, text=raw.decode("utf-8"), file_hash=_sha12(raw))


def schema_hash(model: type[BaseModel]) -> str:
    return _sha12(json.dumps(model.model_json_schema(), sort_keys=True).encode("utf-8"))


def summary_hash(summary: HistorySummary) -> str:
    return _sha12(summary.model_dump_json().encode("utf-8"))


def context_hash() -> str:
    """Skrót wiedzy widocznej dla modelu poza szablonem: Reguł, Katalogu jednostek i legendy Podsumowania historii."""
    data = (
        (KNOWLEDGE_BASE_DIR / "rules.yaml").read_bytes()
        + (KNOWLEDGE_BASE_DIR / "workout_catalog.yaml").read_bytes()
        + summary_legend(HistorySummary).encode("utf-8")
    )
    return _sha12(data)


def _sha12(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()[:12]


def _km(value: float) -> str:
    return f"{value:.1f}".replace(".", ",")


def summary_legend(model: type[BaseModel]) -> str:
    """Jedna linia na ścieżkę pola, z opisów w schemacie; pola elementów list jako `lista[].pole`."""
    schema = model.model_json_schema()
    lines: list[str] = []
    _legend_lines(schema, schema.get("$defs", {}), "", lines)
    return "\n".join(lines)


def _legend_lines(node: dict[str, Any], defs: dict[str, Any], prefix: str, lines: list[str]) -> None:
    for name, prop in node.get("properties", {}).items():
        path = f"{prefix}{name}"
        target = _deref(prop, defs)
        line = f"{path} — {prop.get('description', '')}".rstrip()
        if "enum" in target:
            line += f" Wartości: {', '.join(target['enum'])}."
        lines.append(line)
        if target.get("type") == "array":
            item = _deref(target.get("items", {}), defs)
            if "properties" in item:
                _legend_lines(item, defs, f"{path}[].", lines)
        elif "properties" in target:
            _legend_lines(target, defs, f"{path}.", lines)


def _deref(node: dict[str, Any], defs: dict[str, Any]) -> dict[str, Any]:
    while True:
        if "anyOf" in node:
            node = next((b for b in node["anyOf"] if b.get("type") != "null"), {})
        elif "$ref" in node:
            node = defs[node["$ref"].rsplit("/", 1)[-1]]
        else:
            return node


def _day(d: date) -> str:
    return f"{d.isoformat()} ({_WEEKDAYS[d.weekday()]})"


def _time(seconds: int) -> str:
    h, rest = divmod(seconds, 3600)
    m, s = divmod(rest, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def render_goal(goal: Goal) -> str:
    target = _time(goal.target_time_s) if goal.target_time_s is not None else "brak"
    return f"Dystans: {goal.distance.label}\nData startu: {_day(goal.race_date)}\nCzas docelowy: {target}"


def render_weeks(weeks: list[CalendarWeek]) -> str:
    rows = ["Tydzień | od | do", *(f"{w.number} | {_day(w.start)} | {_day(w.end)}" for w in weeks)]
    return "\n".join(rows)


def render_days(week: CalendarWeek) -> str:
    return "\n".join(f"dzień {i + 1}: {_day(week.start + timedelta(days=i))}" for i in range(7))


def render_catalog(catalog: dict[WorkoutType, CatalogEntry]) -> str:
    lines = []
    for e in catalog.values():
        kind = "Jednostka kluczowa i jakościowa" if e.quality else "Jednostka kluczowa" if e.key else None
        head = f"{e.type.value} — {e.name}" + (f" ({kind})" if kind else "")
        lines.append(f"- {head}: {e.description}")
    return "\n".join(lines)


def render_interpretation(interpretation: Interpretation) -> str:
    def section(title: str, statements: list[Statement]) -> str:
        return "\n".join([f"{title}:", *(f"- {s.text}" for s in statements)])

    return "\n".join(
        [
            section("Trendy", interpretation.trends),
            section("Mocne strony", interpretation.strengths),
            section("Słabe strony", interpretation.weaknesses),
            section("Ryzyka", interpretation.risks),
            section("Gotowość do Celu", [interpretation.readiness]),
        ]
    )


def render_target(target_km: float, registry: RuleRegistry) -> str:
    """Docelowa objętość Tygodnia z dopuszczalnym zakresem, tym samym, który sprawdza walidator."""
    low, high = volume_target_range(registry, target_km)
    return f"{_km(target_km)} km, dopuszczalnie od {low} do {high} km"


def render_key_workouts(week: SkeletonWeek, catalog: dict[WorkoutType, CatalogEntry]) -> str:
    if not week.key_workouts:
        return "brak"
    return ", ".join(f"{t.value} ({catalog[t].name})" for t in week.key_workouts)


def render_neighbours(skeleton: Skeleton, number: int) -> str:
    lines = []
    for w in skeleton.weeks:
        if w.number in (number - 1, number + 1):
            which = "poprzedni" if w.number < number else "następny"
            keys = ", ".join(t.value for t in w.key_workouts) or "brak"
            lines.append(
                f"Tydzień {w.number} ({which}): Faza {w.phase.value}, {_km(w.target_volume_km)} km, "
                f"Jednostki kluczowe: {keys}"
            )
    return "\n".join(lines) or "brak"


def render_race_note(goal: Goal, week: CalendarWeek) -> str:
    """Uwaga o starcie dla Tygodnia startu, od nowej linii; pusty tekst dla pozostałych Tygodni."""
    if week.end != goal.race_date:
        return ""
    return (
        f"\nTo Tydzień startu: w dniu 7, {_day(goal.race_date)}, odbywa się start ({goal.distance.label}). "
        "Start dopisuje kod: nie planuj na dzień 7 żadnej Jednostki i nie wliczaj startu do objętości Tygodnia."
    )


def render_problems(violations: list[Violation], format_errors: list[str], registry: RuleRegistry) -> str:
    """Ponumerowana lista Naruszeń twardych z opisem Reguły oraz błędów formatu do prompta Poprawki."""
    lines: list[str] = []
    described: dict[str, int] = {}
    for v in violations:
        if v.kind is not RuleKind.HARD:
            continue
        n = len(lines) + 1
        spec = registry.spec(v.rule_id)
        item = f"{n}. Reguła {v.rule_id} „{spec.title}”: {v.message_for_model}"
        if v.rule_id in described:
            item += f"\n   Opis Reguły w punkcie {described[v.rule_id]}."
        else:
            item += f"\n   Opis Reguły: {spec.description}"
            described[v.rule_id] = n
        lines.append(item)
    for error in format_errors:
        lines.append(f"{len(lines) + 1}. Błąd formatu: {error}")
    return "\n".join(lines)
