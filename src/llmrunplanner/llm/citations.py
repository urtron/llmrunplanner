import re
from typing import Any

from ..domain import Citation, CitationCheck, Distance, HistorySummary, Interpretation, InterpretationCheck, Statement

_PART = re.compile(r"(?P<name>[A-Za-z0-9_]+)(?:\[(?P<key>[A-Za-z0-9_]+)=(?P<value>[^\[\]]+)\])?(?:\.|$)")
_MISSING = object()
_DATE = re.compile(r"\d{4}-\d{2}-\d{2}|\d{1,2}\.\d{1,2}\.\d{4}")
# liczba, która nie jest częścią słowa: bez litery tuż przed (Z2, VO2max) ani litery lub łącznika ze słowem tuż po
# (10K, 4-tygodniowy)
# liczba okien czasu („ostatnich 4 tygodni”, „7 dni”) nie jest wartością z Podsumowania
_WINDOW_WORD = re.compile(r"\s?(?:dzień|dni|dnia|tydzień|tygodnie|tygodni|tygodnia)\b", re.IGNORECASE)
_NUMBER = re.compile(r"(?<!\w)(?<!\d[.,])\d+(?:[.,]\d+)?(?!\w|[.,]\d|-[^\W\d_])")


def check_citations(
    interpretation: Interpretation, summary: HistorySummary, distance: Distance
) -> InterpretationCheck:
    """Porównuje każdą zacytowaną liczbę z polem Podsumowania historii, z tolerancją zaokrągleń,
    i wskazuje liczby z tekstów bez pasującego cytowania (poza datami, dystansem startu i liczbą dni lub Tygodni)."""
    data = summary.model_dump(mode="json")
    statements = [
        *interpretation.trends,
        *interpretation.strengths,
        *interpretation.weaknesses,
        *interpretation.risks,
        interpretation.readiness,
    ]
    checks = [_check(c, data) for s in statements for c in s.citations]
    uncited = [n for s in statements for n in _uncited(s, distance)]
    return InterpretationCheck(
        total=len(checks), matched=sum(c.ok for c in checks), checks=checks, uncited=uncited
    )


def _uncited(statement: Statement, distance: Distance) -> list[str]:
    cited = [c.value for c in statement.citations]
    out = []
    text = _DATE.sub(" ", statement.text)
    for m in _NUMBER.finditer(text):
        if _WINDOW_WORD.match(text, m.end()):
            continue
        number = float(m.group().replace(",", "."))
        if number == round(distance.km) or abs(number - distance.km) <= 0.11:
            continue
        if not any(_close(number, abs(v)) for v in cited):
            out.append(m.group())
    return out


def _tolerance(actual: float) -> float:
    return max(0.051, 0.01 * abs(actual))


def _close(value: float, actual: float) -> bool:
    return abs(value - actual) <= _tolerance(actual)


def _check(citation: Citation, data: dict[str, Any]) -> CitationCheck:
    def result(actual: float | None, reason: str | None) -> CitationCheck:
        return CitationCheck(
            field=citation.field, cited=citation.value, actual=actual, ok=reason is None, reason=reason
        )

    value = _resolve(data, citation.field.strip())
    if value is _MISSING:
        return result(None, "nieznane pole")
    if value is None:
        return result(None, "pole bez wartości")
    if isinstance(value, bool) or not isinstance(value, int | float):
        return result(None, "pole nie jest liczbą")
    actual = float(value)
    tolerance = _tolerance(actual)
    if not _close(citation.value, actual):
        return result(actual, f"różnica większa niż tolerancja ±{tolerance:.3g}".replace(".", ","))
    return result(actual, None)


def _resolve(data: Any, path: str) -> Any:
    """Wartość pod ścieżką `a.b[klucz=wartość].c`; elementy listy wybiera się wartością pola, nie indeksem."""
    if not path or path.endswith("."):
        return _MISSING
    node, pos = data, 0
    while pos < len(path):
        m = _PART.match(path, pos)
        if m is None:
            return _MISSING
        pos = m.end()
        if not isinstance(node, dict) or m["name"] not in node:
            return _MISSING
        node = node[m["name"]]
        if m["key"] is not None:
            if not isinstance(node, list):
                return _MISSING
            wanted = m["value"].strip()
            found = [it for it in node if isinstance(it, dict) and _same_key(it.get(m["key"], _MISSING), wanted)]
            if len(found) != 1:
                return _MISSING
            node = found[0]
    return node


def _same_key(value: Any, wanted: str) -> bool:
    if value is _MISSING:
        return False
    if str(value) == wanted:
        return True
    if isinstance(value, int | float) and not isinstance(value, bool):
        try:
            return float(wanted) == float(value)
        except ValueError:
            return False
    return False
