import math
from datetime import date, timedelta

from ..domain import (
    AthleteMetrics,
    Distance,
    GateProposal,
    GateResult,
    GateStatus,
    Goal,
    HistorySummary,
)
from .params import (
    GATE_EXPONENTS,
    HISTORY_MIN_ACTIVE_WEEKS,
    HISTORY_MIN_DAYS,
    HISTORY_MIN_HR_VALID_SHARE,
    HISTORY_MIN_RUNS,
    HISTORY_WINDOW_WEEKS,
    IMPROVEMENT_OK_PER_WEEK,
    IMPROVEMENT_WARN_PER_WEEK,
    MIN_WEEKLY_KM,
    MIN_WEEKS,
    PLAN_MAX_WEEKS,
    PLAN_MIN_WEEKS,
    TIME_ROUND_S,
)
from .questionnaire import HEALTH_QUESTIONS

_HEALTH_REASON = "Odpowiedź twierdząca w Ankiecie zdrowotnej: skonsultuj się z lekarzem przed rozpoczęciem treningu."
_PAST_DATE_REASON = "Data startu musi być późniejsza niż Dzień stanu."


def _fmt_time(seconds: float) -> str:
    total = round(seconds)
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def _num(value: float, digits: int = 1) -> str:
    return f"{value:.{digits}f}".replace(".", ",")


def _plural_form(n: int) -> int:
    """0 – liczba pojedyncza (1), 1 – formy 2–4 (poza 12–14), 2 – pozostałe."""
    if n == 1:
        return 0
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return 1
    return 2


def _weeks_left(n: int) -> str:
    """Zdanie o liczbie pełnych Tygodni do startu, z czasownikiem zgodnym z liczbą."""
    form = _plural_form(n)
    verb = ("został", "zostały", "zostało")[form]
    noun = ("pełny Tydzień", "pełne Tygodnie", "pełnych Tygodni")[form]
    return f"{verb} {n} {noun}"


def _weeks(n: int) -> str:
    return f"{n} {('Tydzień', 'Tygodnie', 'Tygodni')[_plural_form(n)]}"


def _in_weeks(n: int) -> str:
    return f"{n} {'Tygodniu' if n == 1 else 'Tygodniach'}"


def _race_date_for(as_of: date, weeks: int) -> date:
    # Data startu = dzień stanu + 7·N − 1: Tydzień 1 zaczyna się w dniu stanu.
    return as_of + timedelta(days=7 * weeks - 1)


def _race_date_proposal(as_of: date, weeks: int, text: str | None = None) -> GateProposal:
    d = _race_date_for(as_of, weeks)
    return GateProposal(
        kind="race_date", race_date=d, text=text or f"Start nie wcześniej niż {d.isoformat()} ({_weeks(weeks)})."
    )


def check_health(answers: dict[str, bool]) -> str | None:
    """Sprawdza samą Ankietę zdrowotną: powód zatrzymania albo None, gdy wszystkie odpowiedzi są przeczące."""
    missing = [q.id for q in HEALTH_QUESTIONS if q.id not in answers]
    if missing:
        raise ValueError(f"Brak odpowiedzi na pytania Ankiety zdrowotnej: {', '.join(missing)}.")
    return _HEALTH_REASON if any(answers[q.id] for q in HEALTH_QUESTIONS) else None


def _prediction(metrics: AthleteMetrics, distance: Distance) -> float | None:
    exponent = GATE_EXPONENTS[distance]
    return next(
        (p.time_s for p in metrics.predictions if p.distance == distance and math.isclose(p.exponent, exponent)),
        None,
    )


def _history_reason(summary: HistorySummary, metrics: AthleteMetrics) -> str | None:
    as_of = summary.as_of
    runs_by_block = [0] * HISTORY_WINDOW_WEEKS
    for a in metrics.activities:
        offset = (as_of - a.date).days
        if 1 <= offset <= 7 * HISTORY_WINDOW_WEEKS and a.hr_valid_share >= HISTORY_MIN_HR_VALID_SHARE:
            runs_by_block[(offset - 1) // 7] += 1
    active_weeks = sum(1 for n in runs_by_block if n > 0)
    total_runs = sum(runs_by_block)
    if (
        (as_of - summary.history_start).days >= HISTORY_MIN_DAYS
        and active_weeks >= HISTORY_MIN_ACTIVE_WEEKS
        and total_runs >= HISTORY_MIN_RUNS
    ):
        return None
    return (
        "Historia treningowa jest poza zakresem systemu: potrzebne są co najmniej 3 miesiące "
        f"regularnego biegania z pomiarem tętna. Historia obejmuje {(as_of - summary.history_start).days} dni "
        f"(wymagane co najmniej {HISTORY_MIN_DAYS}). W ostatnich {HISTORY_WINDOW_WEEKS} Tygodniach: "
        f"Tygodni z biegami z pomiarem tętna {active_weeks} (wymagane co najmniej {HISTORY_MIN_ACTIVE_WEEKS}), "
        f"takich biegów {total_runs} (wymagane co najmniej {HISTORY_MIN_RUNS})."
    )


def run_gate(
    answers: dict[str, bool], goal: Goal, summary: HistorySummary, metrics: AthleteMetrics
) -> GateResult:
    health = check_health(answers)
    as_of = summary.as_of
    weeks = goal.weeks_from(as_of)
    distance = goal.distance
    pred = _prediction(metrics, distance)
    predicted = None if pred is None else round(pred)

    def result(status: GateStatus, reasons, warnings, proposals) -> GateResult:
        return GateResult(
            status=status, reasons=reasons, warnings=warnings, proposals=proposals, weeks=weeks,
            predicted_time_s=predicted,
        )

    if health is not None:
        return result(GateStatus.STOP, [health], [], [])
    if goal.race_date <= as_of:
        return result(GateStatus.STOP, [_PAST_DATE_REASON], [], [])

    reasons: list[str] = []
    warnings: list[str] = []
    proposals: list[GateProposal] = []
    name = distance.label

    too_long = weeks > PLAN_MAX_WEEKS
    weeks_eff = weeks
    if weeks < PLAN_MIN_WEEKS:
        weeks_eff = max(weeks, MIN_WEEKS[distance], PLAN_MIN_WEEKS)
        reasons.append(f"Do startu {_weeks_left(weeks)}, a Plan trwa co najmniej {_weeks(PLAN_MIN_WEEKS)}.")
    elif too_long:
        reasons.append(
            f"Do startu {_weeks_left(weeks)}, a Plan trwa najwyżej {_weeks(PLAN_MAX_WEEKS)}. "
            f"Plan można rozpocząć najwcześniej {(goal.race_date - timedelta(days=7 * PLAN_MAX_WEEKS - 1)).isoformat()}."
        )
    elif weeks < MIN_WEEKS[distance]:
        weeks_eff = MIN_WEEKS[distance]
        reasons.append(f"Cel {name} wymaga co najmniej {_weeks(weeks_eff)} przygotowania (jest {weeks}).")

    history_reason = _history_reason(summary, metrics)
    if history_reason:
        reasons.append(history_reason)
    if metrics.zones is None:
        reasons.append("Brak wiarygodnego Progu: Stref nie da się przeliczyć na tempa, więc Plan nie powstaje.")

    race_weeks = weeks_eff if weeks_eff > weeks else None  # liczba Tygodni z propozycji nowej daty startu
    race_text: str | None = None
    target_proposal: GateProposal | None = None
    if not too_long and not history_reason and metrics.zones is not None:
        if summary.avg_weekly_km_last_4w < MIN_WEEKLY_KM[distance]:
            warnings.append(
                f"Średnia objętość z ostatnich 4 Tygodni ({_num(summary.avg_weekly_km_last_4w)} km) jest niższa niż "
                f"zalecane minimum dla celu {name} ({MIN_WEEKLY_KM[distance]} km); Plan zacznie od niskiej objętości."
            )
        if pred is None:
            warnings.append("Brak Prognozy czasu: nie można ocenić wykonalności czasu docelowego.")
        elif goal.target_time_s is not None:
            r = 1 - goal.target_time_s / pred
            ok_limit = IMPROVEMENT_OK_PER_WEEK * weeks_eff

            def verdict(label: str) -> str:
                return (
                    f"Czas docelowy {_fmt_time(goal.target_time_s)} {label}: Prognoza wynosi {_fmt_time(pred)}, "
                    f"a wymagana poprawa to {_num(r * 100)}% w {_in_weeks(weeks_eff)}."
                )

            if r > IMPROVEMENT_WARN_PER_WEEK * weeks_eff:
                reasons.append(verdict("jest nierealny"))
                realistic = math.ceil(pred * (1 - ok_limit) / TIME_ROUND_S) * TIME_ROUND_S
                target_date = None if race_weeks is None else _race_date_for(as_of, race_weeks)
                target_text = f"Realny czas docelowy: {_fmt_time(realistic)}."
                if target_date is not None:
                    target_text = (
                        f"Realny czas docelowy: {_fmt_time(realistic)} przy starcie nie wcześniej niż "
                        f"{target_date.isoformat()} ({_weeks(race_weeks)})."
                    )
                target_proposal = GateProposal(
                    kind="target_time", target_time_s=realistic, race_date=target_date, text=target_text
                )
                needed = math.ceil(r / IMPROVEMENT_OK_PER_WEEK)
                while r > IMPROVEMENT_OK_PER_WEEK * needed:
                    needed += 1
                if weeks_eff < needed <= PLAN_MAX_WEEKS:
                    race_weeks = needed
                    race_text = (
                        f"Czas {_fmt_time(goal.target_time_s)} jest realny przy starcie nie wcześniej niż "
                        f"{_race_date_for(as_of, needed).isoformat()} ({_weeks(needed)})."
                    )
            elif r > ok_limit:
                warnings.append(verdict("jest ambitny"))

    if target_proposal is not None:
        proposals.append(target_proposal)
    if race_weeks is not None:
        proposals.append(_race_date_proposal(as_of, race_weeks, race_text))

    status = GateStatus.STOP if reasons else GateStatus.WARN if warnings else GateStatus.OK
    return result(status, reasons, warnings, proposals)
