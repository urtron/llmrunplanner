from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from pydantic import BaseModel

from ..domain import Violation
from ..validator import RuleRegistry
from .models import CallOutcome
from .prompts import load_prompt, render_problems

Validate = Callable[[BaseModel], tuple[list[Violation], list[str]]]
# próba, wynik wywołania, Naruszenia i błędy formatu z walidacji (puste, gdy odpowiedź się nie sparsowała)
OnAttempt = Callable[[int, CallOutcome, list[Violation], list[str]], None]


@dataclass(frozen=True)
class GenerationResult:
    value: BaseModel | None
    violations: list[Violation]
    format_errors: list[str]
    status: Literal["ok", "niezatwierdzony"]
    attempts: int
    last_error: str | None = None  # błąd parsowania późniejszej próby, która nie dała odpowiedzi


def generate_validated(
    call: Callable[[list[BaseMessage]], CallOutcome],
    validate: Validate,
    initial: list[BaseMessage],
    registry: RuleRegistry,
    on_attempt: OnAttempt,
    max_repairs: int = 2,
) -> GenerationResult:
    """Pętla generuj – sprawdź – popraw. Poprawka to kolejna tura rozmowy, więc zasady pierwszego polecenia obowiązują."""
    repair = load_prompt("repair")
    messages = initial
    # value, violations i format_errors pochodzą z tej samej próby: ostatniej sparsowanej
    value: BaseModel | None = None
    violations: list[Violation] = []
    format_errors: list[str] = []
    for attempt in range(max_repairs + 1):
        outcome = call(messages)
        last_error: str | None = None
        if outcome.parsed is None:
            last_error = outcome.parse_error or "Odpowiedź nie zgadza się ze schematem."
            on_attempt(attempt, outcome, [], [])
            current_violations: list[Violation] = []
            current_errors = [last_error]
        else:
            value = outcome.parsed
            violations, format_errors = validate(value)
            on_attempt(attempt, outcome, violations, format_errors)
            current_violations, current_errors = violations, format_errors

        failed = last_error is not None or bool(format_errors) or registry.has_hard(violations)
        if not failed or attempt == max_repairs:
            return GenerationResult(
                value=value,
                violations=violations,
                format_errors=format_errors,
                status="niezatwierdzony" if failed else "ok",
                attempts=attempt + 1,
                last_error=last_error,
            )
        previous = outcome.raw_json or outcome.reply_text or "(brak odpowiedzi)"
        messages = [
            *initial,
            AIMessage(content=previous),
            HumanMessage(
                content=repair.render(problems=render_problems(current_violations, current_errors, registry))
            ),
        ]
    raise AssertionError("niedostępne")
