from datetime import date, timedelta

from ..domain import CalendarWeek, weeks_until_race


def calendar_weeks(as_of: date, race_date: date) -> list[CalendarWeek]:
    """Tygodnie liczone wstecz od dnia startu; ostatni kończy się w dniu startu."""
    n = weeks_until_race(as_of, race_date)
    if n < 1:
        raise ValueError(f"Między {as_of} a startem {race_date} nie mieści się pełny Tydzień.")
    weeks = []
    for number in range(1, n + 1):
        end = race_date - timedelta(days=7 * (n - number))
        weeks.append(CalendarWeek(number=number, start=end - timedelta(days=6), end=end))
    return weeks


def pre_plan_days(as_of: date, weeks: list[CalendarWeek]) -> list[date]:
    """Dni od `as_of` do dnia przed Tygodniem 1; nie należą do Planu."""
    return [as_of + timedelta(days=i) for i in range((weeks[0].start - as_of).days)]
