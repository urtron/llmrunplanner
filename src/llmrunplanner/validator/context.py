from dataclasses import dataclass

from ..domain import CalendarWeek, Goal, HistorySummary, Phase, Skeleton, WeekDraft, ZoneBounds


@dataclass(frozen=True)
class SkeletonContext:
    skeleton: Skeleton
    goal: Goal
    summary: HistorySummary
    n_weeks: int


@dataclass(frozen=True)
class WeekContext:
    draft: WeekDraft
    phase: Phase
    week: CalendarWeek
    goal: Goal
    target_volume_km: float
    zones: list[ZoneBounds]

    @property
    def number(self) -> int:
        return self.week.number

    @property
    def is_race_week(self) -> bool:
        return self.week.end == self.goal.race_date
