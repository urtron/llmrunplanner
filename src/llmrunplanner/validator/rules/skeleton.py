from ...domain import Phase, RuleKind, Violation
from ..context import SkeletonContext
from .base import (
    Rule,
    fmt,
    fmt_max_km,
    fmt_min_km,
    fmt_pct_over,
    fmt_pct_under,
    is_deload,
    pct_of,
    weeks_label,
    weeks_word,
)

_ORDER = {p: i for i, p in enumerate(Phase)}
_PHASE_CHAIN = " < ".join(p.value for p in Phase)
_STEP_PCT = 10  # przyrost tygodniowy z reguły 10% (próg ostrzeżenia S4), przywoływany we wskazówce S3


def _phase_runs(ctx: SkeletonContext) -> list[tuple[Phase, int, int]]:
    """Ciągłe odcinki tej samej Fazy jako (Faza, pierwszy Tydzień, ostatni Tydzień)."""
    runs: list[tuple[Phase, int, int]] = []
    for w in ctx.skeleton.weeks:
        if runs and runs[-1][0] == w.phase:
            runs[-1] = (w.phase, runs[-1][1], w.number)
        else:
            runs.append((w.phase, w.number, w.number))
    return runs


class PhaseOrder(Rule):
    id = "S1"
    level = "skeleton"
    kind = "hard"

    def check(self, ctx: SkeletonContext) -> list[Violation]:
        out: list[Violation] = []
        weeks = ctx.skeleton.weeks
        for prev, cur in zip(weeks, weeks[1:]):
            if _ORDER[cur.phase] < _ORDER[prev.phase]:
                out.append(
                    self.hard(
                        f"Tydzień {cur.number}",
                        f"Tydzień {cur.number}: Faza {cur.phase.value} po Fazie {prev.phase.value} "
                        f"narusza kolejność {_PHASE_CHAIN}.",
                        f"Tydzień {cur.number} ma Fazę {cur.phase.value}, a poprzedni Tydzień {prev.phase.value}. "
                        f"Fazy muszą następować w kolejności niemalejącej {_PHASE_CHAIN}; popraw Fazy Tygodni.",
                    )
                )
        last = weeks[-1]
        if last.phase is not Phase.TAPER:
            out.append(
                self.hard(
                    f"Tydzień {last.number}",
                    f"Tydzień {last.number}: ostatni Tydzień ma Fazę {last.phase.value}, a powinien mieć TAPER.",
                    f"Ostatni Tydzień ({last.number}) ma Fazę {last.phase.value}. Szkielet musi kończyć się "
                    f"Fazą TAPER; przypisz ją ostatnim Tygodniom.",
                )
            )
        return out


class MinPhaseWeeks(Rule):
    id = "S1b"
    level = "skeleton"
    kind = "soft"
    required_thresholds = ("min_phase_weeks",)

    def check(self, ctx: SkeletonContext) -> list[Violation]:
        minimum = self.thresholds["min_phase_weeks"]
        out: list[Violation] = []
        for phase, first, last in _phase_runs(ctx):
            length = last - first + 1
            if phase is Phase.TAPER or length >= minimum:
                continue
            out.append(
                self.soft(
                    weeks_label(first, last),
                    f"{weeks_label(first, last)}: Faza {phase.value} trwa {length} {weeks_word(length)}, "
                    f"a powinna trwać co najmniej {minimum} {weeks_word(minimum)}.",
                    f"Faza {phase.value} ({weeks_label(first, last)}) trwa {length} {weeks_word(length)}. Każda Faza "
                    f"inna niż TAPER powinna trwać co najmniej {minimum} {weeks_word(minimum)}; wydłuż ją albo połącz "
                    f"z sąsiednią Fazą.",
                )
            )
        return out


class Taper(Rule):
    id = "S2"
    level = "skeleton"
    kind = "hard"
    required_thresholds = ("taper_weeks", "min_reduction_pct", "max_reduction_pct")
    distance_thresholds = ("taper_weeks",)

    def check(self, ctx: SkeletonContext) -> list[Violation]:
        out: list[Violation] = []
        weeks = ctx.skeleton.weeks
        taper = [w for w in weeks if w.phase is Phase.TAPER]
        build = [w for w in weeks if w.phase is not Phase.TAPER]
        low, high = self.for_distance("taper_weeks", ctx.goal.distance)
        goal = ctx.goal.distance.label
        expected = f"{low} {weeks_word(low)}" if low == high else f"{low}–{high} {weeks_word(high)}"
        if not low <= len(taper) <= high:
            where = weeks_label(taper[0].number, taper[-1].number) if taper else f"Tydzień {weeks[-1].number}"
            out.append(
                self.hard(
                    where,
                    f"Taper trwa {len(taper)} {weeks_word(len(taper))}, a przy celu „{goal}” powinien trwać {expected}.",
                    f"Liczba Tygodni z Fazą TAPER wynosi {len(taper)}. Przy celu „{goal}” taper musi trwać {expected} "
                    f"(Tygodnie tapera na końcu Szkieletu); popraw liczbę Tygodni z Fazą TAPER.",
                )
            )
        if not taper:
            return out
        where = weeks_label(taper[0].number, taper[-1].number)
        if not build:
            out.append(
                self.hard(
                    where,
                    "Taper nie ma poprzedzającej go budowy objętości.",
                    "Wszystkie Tygodnie mają Fazę TAPER. Przed taperem zaplanuj Tygodnie BASE, BUILD lub PEAK, "
                    "od których taper obniża objętość.",
                )
            )
            return out
        peak = max(w.target_volume_km for w in build)
        mean = sum(w.target_volume_km for w in taper) / len(taper)
        share = pct_of(mean, peak)
        share_min = 100 - self.thresholds["max_reduction_pct"]
        share_max = 100 - self.thresholds["min_reduction_pct"]
        if not share_min <= share <= share_max:
            share_txt = fmt_pct_under(share) if share < share_min else fmt_pct_over(share)
            lo_km, hi_km = fmt_min_km(peak * share_min / 100), fmt_max_km(peak * share_max / 100)
            out.append(
                self.hard(
                    where,
                    f"{where}: średnia objętość tapera {fmt(mean)} km to {share_txt}% szczytu ({fmt(peak)} km); "
                    f"oczekiwane {fmt(share_min, 0)}–{fmt(share_max, 0)}% ({lo_km}–{hi_km} km).",
                    f"Średnia objętość tapera ({where}) wynosi {fmt(mean)} km, czyli {share_txt}% szczytu "
                    f"({fmt(peak)} km). Redukcja ma wynosić {100 - share_max:.0f}–{100 - share_min:.0f}%: "
                    f"średnia objętość tapera między {lo_km} a {hi_km} km.",
                )
            )
        return out


class FirstWeekVolume(Rule):
    id = "S3"
    level = "skeleton"
    kind = "soft_then_hard"
    required_thresholds = ("warn_above_pct", "error_above_pct")

    def check(self, ctx: SkeletonContext) -> list[Violation]:
        baseline = ctx.summary.avg_weekly_km_last_4w
        if baseline <= 0:
            return []
        first = ctx.skeleton.weeks[0]
        pct = pct_of(first.target_volume_km, baseline)
        warn, error = self.thresholds["warn_above_pct"], self.thresholds["error_above_pct"]
        kind = self.graded_above(pct, warn, error)
        if kind is None:
            return []
        limit = error if kind is RuleKind.HARD else warn
        label = "błędu" if kind is RuleKind.HARD else "ostrzeżenia"
        return [
            self.violation(
                kind,
                "Tydzień 1",
                f"Tydzień 1: {fmt(first.target_volume_km)} km to {fmt_pct_over(pct)}% średniej z ostatnich 4 Tygodni "
                f"({fmt(baseline)} km); limit {label} {limit}%.",
                f"Objętość Tygodnia 1 ({fmt(first.target_volume_km)} km) to {fmt_pct_over(pct)}% średniej tygodniowej "
                f"Biegacza z ostatnich 4 Tygodni ({fmt(baseline)} km). Obniż ją do najwyżej "
                f"{fmt_max_km(baseline * limit / 100)} km ({limit}% tej średniej) i dostosuj kolejne Tygodnie tak, "
                f"by przyrost nie przekraczał {_STEP_PCT}% na Tydzień.",
            )
        ]


class WeeklyIncrease(Rule):
    id = "S4"
    level = "skeleton"
    kind = "soft_then_hard"
    required_thresholds = ("warn_above_pct", "error_above_pct", "deload_min_drop_pct")

    def check(self, ctx: SkeletonContext) -> list[Violation]:
        warn, error = self.thresholds["warn_above_pct"], self.thresholds["error_above_pct"]
        drop = self.thresholds["deload_min_drop_pct"]
        out: list[Violation] = []
        weeks = ctx.skeleton.weeks
        deload = [i > 0 and is_deload(weeks[i - 1].target_volume_km, w.target_volume_km, drop) for i, w in enumerate(weeks)]
        for i in range(1, len(weeks)):
            j = i - 1
            while deload[j]:
                j -= 1  # odniesienie: ostatni Tydzień sprzed serii odciążeń
            cur, prev = weeks[i], weeks[j]
            ref = f"Tygodnia {prev.number} sprzed odciążenia" if j < i - 1 else f"Tygodnia {prev.number}"
            increase = round(pct_of(cur.target_volume_km, prev.target_volume_km) - 100, 6)
            kind = self.graded_above(increase, warn, error)
            if kind is None:
                continue
            limit = error if kind is RuleKind.HARD else warn
            label = "błędu" if kind is RuleKind.HARD else "ostrzeżenia"
            out.append(
                self.violation(
                    kind,
                    f"Tydzień {cur.number}",
                    f"Tydzień {cur.number}: {fmt(cur.target_volume_km)} km to +{fmt_pct_over(increase)}% względem "
                    f"{ref} ({fmt(prev.target_volume_km)} km); limit {label} {limit}%.",
                    f"Objętość Tygodnia {cur.number} ({fmt(cur.target_volume_km)} km) jest o {fmt_pct_over(increase)}% "
                    f"wyższa niż {ref} ({fmt(prev.target_volume_km)} km). Przyrost nie może "
                    f"przekraczać {limit}%: obniż ją do najwyżej {fmt_max_km(prev.target_volume_km * (1 + limit / 100))} km "
                    f"i dostosuj kolejne Tygodnie tak, by przyrost nie przekraczał {warn}% na Tydzień.",
                )
            )
        return out


class Deload(Rule):
    id = "S6"
    level = "skeleton"
    kind = "soft"
    required_thresholds = ("build_weeks_max", "deload_min_drop_pct")

    def check(self, ctx: SkeletonContext) -> list[Violation]:
        longest = self.thresholds["build_weeks_max"]
        drop = self.thresholds["deload_min_drop_pct"]
        weeks = ctx.skeleton.weeks
        out: list[Violation] = []
        run: list[int] = []

        def close() -> None:
            if len(run) > longest:
                span = weeks_label(run[0], run[-1])
                out.append(
                    self.soft(
                        span,
                        f"{span}: {len(run)} {weeks_word(len(run))} budowania z rzędu bez Tygodnia odciążającego "
                        f"(limit {longest}).",
                        f"{span} to {len(run)} {weeks_word(len(run))} budowania z rzędu. Co najwyżej po {longest} takich Tygodniach "
                        f"wstaw Tydzień odciążający o objętości niższej o co najmniej {drop}% od poprzedniego Tygodnia.",
                    )
                )
            run.clear()

        for prev, cur in zip([None, *weeks], weeks):
            if cur.phase is Phase.TAPER:
                break
            deload = prev is not None and is_deload(prev.target_volume_km, cur.target_volume_km, drop)
            if deload:
                close()
            else:
                run.append(cur.number)
        close()
        return out
