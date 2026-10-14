from ..domain import Segment, WeekDraft, Workout


def expand_segments(workout: Workout) -> list[Segment]:
    return [s for block in workout.blocks for _ in range(block.repeat) for s in block.segments]


def workout_distance_m(workout: Workout) -> int:
    return sum(s.distance_m for s in expand_segments(workout))


def draft_distance_km(draft: WeekDraft) -> float:
    return sum(workout_distance_m(w) for w in draft.workouts) / 1000
