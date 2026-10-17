from ..domain import Skeleton
from .rules.base import weeks_label, weeks_word


def skeleton_format_errors(skeleton: Skeleton, n_weeks: int) -> list[str]:
    """Błędy kształtu Szkieletu, których nie wyraża schemat odpowiedzi: liczba Tygodni zgodna z kalendarzem."""
    count = len(skeleton.weeks)
    if count == n_weeks:
        return []
    return [
        f"Szkielet ma {count} {weeks_word(count)}, a musi mieć {n_weeks} ({weeks_label(1, n_weeks)})."
    ]
