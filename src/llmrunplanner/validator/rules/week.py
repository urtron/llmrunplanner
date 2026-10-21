import math

from ...domain import RuleKind, Violation, Workout, WorkoutType, Zone
from ...plan import draft_distance_km, expand_segments, workout_distance_m, workout_duration_s, zone_minutes
from ..context import WeekContext
from .base import Rule, days_word, fmt, fmt_max_km, fmt_min_km, fmt_pct_over, fmt_pct_under, pct_of

RACE_DAY = 7
_QUALITY_TYPES = ", ".join(t.value for t in WorkoutType if t.is_quality)
_HIGH_ZONES = (Zone.Z3, Zone.Z4, Zone.Z5)


def _by_day(ctx: WeekContext) -> list[Workout]:
    return sorted(ctx.draft.workouts, key=lambda w: w.day)


def _key_workouts(ctx: WeekContext) -> list[Workout]:
    return [w for w in _by_day(ctx) if w.type.is_key]


def _fmt_pace(s_per_km: float) -> str:
    total = round(s_per_km)
    return f"{total // 60}:{total % 60:02d}"


def _week_location(ctx: WeekContext) -> str:
    return f"Tydzień {ctx.number}"


def _day_location(ctx: WeekContext, day: int) -> str:
    return f"Tydzień {ctx.number}, dzień {day}"


def _days_list(days: list[int]) -> str:
    """„dzień 3” albo „dni 3 i 5”, „dni 2, 3 i 5”."""
    if len(days) == 1:
        return f"dzień {days[0]}"
    return "dni " + ", ".join(str(d) for d in days[:-1]) + f" i {days[-1]}"


class LongRunLimits(Rule):
    id = "S7"
    level = "week"
    kind = "hard"
    required_thresholds = ("max_km", "max_min")
    distance_thresholds = ("max_km", "max_min")

    def check(self, ctx: WeekContext) -> list[Violation]:
        max_km = self.for_distance("max_km", ctx.goal.distance)
        max_min = self.for_distance("max_min", ctx.goal.distance)
        goal = ctx.goal.distance.label
        out: list[Violation] = []
        for w in _by_day(ctx):
            if w.type is not WorkoutType.LONG:
                continue
            km = workout_distance_m(w) / 1000
            seconds = workout_duration_s(w, ctx.zones)
            pace = seconds / km
            time_km = max_min * 60 / pace
            limit = min(max_km, time_km)
            if round(km, 6) <= round(limit, 6):
                continue
            where = _day_location(ctx, w.day)
            out.append(
                self.hard(
                    where,
                    f"{where}: długie wybieganie ma {fmt(km)} km (około {round(seconds / 60)} min); "
                    f"limit to {fmt_max_km(limit)} km.",
                    f"Długie wybieganie (dzień {w.day}) ma {fmt(km)} km; limit to {fmt_max_km(limit)} km, "
                    f"bo przy tempie Jednostki ({_fmt_pace(pace)}/km) {max_min} min to {fmt_max_km(time_km)} km, "
                    f"a limit dystansu przy celu „{goal}” to {fmt(max_km, 0)} km. Skróć je, a nadwyżkę dystansu "
                    f"rozłóż na inne dni.",
                )
            )
        return out


class RestDays(Rule):
    id = "T1"
    level = "week"
    kind = "hard"
    required_thresholds = ("min_rest_days",)

    def check(self, ctx: WeekContext) -> list[Violation]:
        minimum = self.thresholds["min_rest_days"]
        # w Tygodniu startu dzień startu nie jest dniem wolnym, więc liczą się tylko dni 1–6
        last_day = RACE_DAY - 1 if ctx.is_race_week else 7
        runs = [w for w in ctx.draft.workouts if w.day <= last_day]
        rest = last_day - len(runs)
        if rest >= minimum:
            return []
        need = minimum - rest
        easy_first = sorted(runs, key=lambda w: (w.type.is_key, workout_distance_m(w), w.day))
        free = sorted(easy_first[:need], key=lambda w: w.day)
        free_txt = ", ".join(f"{w.type.value} {fmt(workout_distance_m(w) / 1000)} km" for w in free)
        those = "tej Jednostki" if need == 1 else "tych Jednostek"
        scope = " wśród dni 1–6 (dzień 7 to start)" if ctx.is_race_week else ""
        where = _week_location(ctx)
        return [
            self.hard(
                where,
                f"{where}: liczba dni wolnych{scope} to {rest}, a powinna być co najmniej {minimum}.",
                f"W Tygodniu {ctx.number} liczba dni wolnych{scope} to {rest}. Zaplanuj co najmniej {minimum} "
                f"{days_word(minimum)} bez żadnej Jednostki: zwolnij {_days_list([w.day for w in free])} "
                f"({free_txt}) i przenieś dystans {those} na inne dni ze spokojnym biegiem, by objętość Tygodnia "
                f"się nie zmieniła.",
            )
        ]


class KeyWorkoutSpacing(Rule):
    id = "T2"
    level = "week"
    kind = "hard"

    def check(self, ctx: WeekContext) -> list[Violation]:
        keys = _key_workouts(ctx)
        out: list[Violation] = []
        for a, b in zip(keys, keys[1:]):
            if b.day - a.day != 1:
                continue
            where = f"Tydzień {ctx.number}, dni {a.day}–{b.day}"
            out.append(
                self.hard(
                    where,
                    f"{where}: Jednostki kluczowe {a.type.value} i {b.type.value} w kolejnych dniach.",
                    f"Dni {a.day} ({a.type.value}) i {b.day} ({b.type.value}) to Jednostki kluczowe dzień po dniu. "
                    f"Przesuń jedną z nich tak, by między nimi był co najmniej jeden dzień wolny lub spokojny bieg.",
                )
            )
        return out


class KeyWorkoutCount(Rule):
    id = "T3"
    level = "week"
    kind = "hard"
    required_thresholds = ("max_quality", "max_long")

    def check(self, ctx: WeekContext) -> list[Violation]:
        max_quality = self.thresholds["max_quality"]
        max_long = self.thresholds["max_long"]
        quality = sum(w.type.is_quality for w in ctx.draft.workouts)
        long_runs = sum(w.type is WorkoutType.LONG for w in ctx.draft.workouts)
        where = _week_location(ctx)
        out: list[Violation] = []
        if quality > max_quality:
            out.append(
                self.hard(
                    where,
                    f"{where}: liczba Jednostek jakościowych to {quality}, a limit to {max_quality}.",
                    f"W Tygodniu {ctx.number} liczba Jednostek jakościowych ({_QUALITY_TYPES}) to {quality}, "
                    f"a limit to {max_quality}. Zamień nadmiarowe na EASY lub RECOVERY.",
                )
            )
        if long_runs > max_long:
            out.append(
                self.hard(
                    where,
                    f"{where}: liczba długich wybiegań to {long_runs}, a limit to {max_long}.",
                    f"W Tygodniu {ctx.number} liczba długich wybiegań (LONG) to {long_runs}, a limit to {max_long}. "
                    f"Zamień nadmiarowe na EASY.",
                )
            )
        return out


class LowIntensityShare(Rule):
    id = "T4"
    level = "week"
    kind = "soft_then_hard"
    required_thresholds = ("warn_below_pct", "error_below_pct")

    def check(self, ctx: WeekContext) -> list[Violation]:
        minutes = zone_minutes(ctx.draft.workouts, ctx.zones)
        total = sum(minutes.values())
        if total == 0:
            return []
        share = pct_of(minutes[Zone.Z1] + minutes[Zone.Z2], total)
        warn = self.thresholds["warn_below_pct"]
        error = self.thresholds["error_below_pct"]
        kind = self.graded_below(share, warn, error)
        if kind is None:
            return []
        limit = error if kind is RuleKind.HARD else warn
        high_min = sum(minutes[z] for z in _HIGH_ZONES)
        high_km = sum(
            s.distance_m for w in ctx.draft.workouts for s in expand_segments(w) if s.zone in _HIGH_ZONES
        ) / 1000
        # Przy stałym dystansie przeniesiony odcinek trwa w Z1–Z2 dłużej niż w Z3–Z5, więc wystarczy z zapasem
        # przenieść tyle minut, by w Z3–Z5 zostało (100 − próg)% obecnego czasu łącznego.
        move_min = high_min - (100 - warn) / 100 * total
        move_km = high_km * move_min / high_min
        where = _week_location(ctx)
        return [
            self.violation(
                kind,
                where,
                f"{where}: w Z1–Z2 tylko {fmt_pct_under(share)}% czasu biegania; "
                f"limit {'błędu' if kind is RuleKind.HARD else 'ostrzeżenia'} {limit}%.",
                f"W Tygodniu {ctx.number} w Strefach Z1–Z2 jest {fmt_pct_under(share)}% planowanego czasu, a powinno "
                f"być co najmniej {warn}%; w Z3–Z5 jest {math.ceil(high_min)} min. Zamień część dystansu w Z3–Z5 "
                f"na Z1–Z2, nie zmieniając sumy dystansów Tygodnia: przenieś około {math.ceil(move_min)} min "
                f"z Z3–Z5, czyli około {fmt_min_km(move_km)} km.",
            )
        ]


class LongRunShare(Rule):
    id = "T5"
    level = "week"
    kind = "soft"
    required_thresholds = ("max_long_share_pct",)
    distance_thresholds = ("max_long_share_pct",)

    def check(self, ctx: WeekContext) -> list[Violation]:
        limit_pct = self.for_distance("max_long_share_pct", ctx.goal.distance)
        volume = draft_distance_km(ctx.draft)
        if volume == 0:
            return []
        out: list[Violation] = []
        for w in _by_day(ctx):
            if w.type is not WorkoutType.LONG:
                continue
            km = workout_distance_m(w) / 1000
            share = pct_of(km, volume)
            if share <= limit_pct:
                continue
            where = _day_location(ctx, w.day)
            max_km = volume * limit_pct / 100
            out.append(
                self.soft(
                    where,
                    f"{where}: długie wybieganie to {fmt_pct_over(share)}% objętości Tygodnia "
                    f"({fmt(km)} z {fmt(volume)} km); limit {limit_pct}%.",
                    f"Długie wybieganie (dzień {w.day}) ma {fmt(km)} km, czyli {fmt_pct_over(share)}% objętości "
                    f"Tygodnia ({fmt(volume)} km). Limit przy celu „{ctx.goal.distance.label}” to {limit_pct}%: "
                    f"skróć je do najwyżej {fmt_max_km(max_km)} km, a nadwyżkę dystansu przenieś na inne dni, "
                    f"by objętość Tygodnia się nie zmieniła.",
                )
            )
        return out


class VolumeTarget(Rule):
    id = "T6"
    level = "week"
    kind = "hard"
    required_thresholds = ("min_pct", "max_pct")

    def range_km(self, target_km: float) -> tuple[str, str]:
        """Dozwolony zakres objętości w km, zaokrąglony do wnętrza przedziału."""
        return (
            fmt_min_km(target_km * (1 + self.thresholds["min_pct"] / 100)),
            fmt_max_km(target_km * (1 + self.thresholds["max_pct"] / 100)),
        )

    def check(self, ctx: WeekContext) -> list[Violation]:
        if ctx.target_volume_km <= 0:
            return []
        volume = draft_distance_km(ctx.draft)
        deviation = pct_of(volume, ctx.target_volume_km) - 100
        low, high = self.thresholds["min_pct"], self.thresholds["max_pct"]
        if low <= deviation <= high:
            return []
        lo_km, hi_km = self.range_km(ctx.target_volume_km)
        # dwa miejsca po przecinku, zaokrąglone od przedziału, by naruszenie nie wyglądało na wartość w przedziale
        round_away = math.floor if deviation < low else math.ceil
        shown = fmt(round_away(round(volume * 100, 6)) / 100, 2)
        race_note = "; start nie wlicza się do objętości" if ctx.is_race_week else ""
        where = _week_location(ctx)
        return [
            self.hard(
                where,
                f"{where}: objętość {shown} km przy celu {fmt(ctx.target_volume_km)} km; "
                f"dozwolone {lo_km}–{hi_km} km.",
                f"Objętość Tygodnia {ctx.number} (suma dystansów Segmentów{race_note}) wynosi "
                f"{shown} km, a cel to {fmt(ctx.target_volume_km)} km. Suma musi mieścić się "
                f"między {lo_km} a {hi_km} km; popraw dystanse.",
            )
        ]


class LastKeyBeforeRace(Rule):
    id = "T7"
    level = "week"
    kind = "hard"
    required_thresholds = ("min_days_before_race",)

    def check(self, ctx: WeekContext) -> list[Violation]:
        if not ctx.is_race_week:
            return []
        out: list[Violation] = []
        minimum = self.thresholds["min_days_before_race"]
        latest = RACE_DAY - minimum
        for w in ctx.draft.workouts:
            if w.day != RACE_DAY:
                continue
            where = _day_location(ctx, RACE_DAY)
            out.append(
                self.hard(
                    where,
                    f"{where}: w dniu startu zaplanowano Jednostkę {w.type.value}.",
                    f"Dzień {RACE_DAY} Tygodnia {ctx.number} to dzień startu, który dopisuje kod; nie planuj w nim "
                    f"żadnej Jednostki. Usuń Jednostkę {w.type.value} z dnia {RACE_DAY}, a jej dystans przenieś "
                    f"na spokojne biegi w dniach 1–{RACE_DAY - 1}.",
                )
            )
        keys = [w for w in _key_workouts(ctx) if w.day < RACE_DAY]
        if not keys:
            return out
        last = keys[-1]
        gap = RACE_DAY - last.day
        if gap >= minimum:
            return out
        where = _day_location(ctx, last.day)
        out.append(
            self.hard(
                where,
                f"{where}: ostatnia Jednostka kluczowa ({last.type.value}) jest {gap} {days_word(gap)} przed startem; "
                f"wymagane co najmniej {minimum} {days_word(minimum)}.",
                f"W Tygodniu startu Jednostka kluczowa {last.type.value} przypada w dniu {last.day}, czyli "
                f"{gap} {days_word(gap)} przed startem (dzień {RACE_DAY}). Przesuń ją najpóźniej na dzień "
                f"{latest} albo zamień na spokojny bieg.",
            )
        )
        return out
