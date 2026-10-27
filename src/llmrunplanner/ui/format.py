"""Formatowanie liczb, czasów i dat w polskiej konwencji (przecinek dziesiętny, tempo m:ss/km)."""

from datetime import date, datetime

_DASH = "–"


def num(x: float | None, digits: int = 1) -> str:
    if x is None:
        return _DASH
    text = f"{x:.{digits}f}"
    if text.startswith("-") and float(text) == 0:
        text = text[1:]
    return text.replace(".", ",")


def integer(n: int | None) -> str:
    """Liczba całkowita ze spacją jako separatorem tysięcy, np. „24 619”."""
    return _DASH if n is None else f"{n:,}".replace(",", " ")


def km(x: float | None, digits: int = 1) -> str:
    return _DASH if x is None else f"{num(x, digits)} km"


def pct(x: float | None, digits: int = 0) -> str:
    """Ułamek (0–1) jako procent, np. 0,7 -> „70%”."""
    return _DASH if x is None else f"{num(x * 100, digits)}%"


def _mmss(total_s: float) -> str:
    total = round(total_s)
    return f"{total // 60}:{total % 60:02d}"


def pace(s_per_km: float | None) -> str:
    return _DASH if s_per_km is None else f"{_mmss(s_per_km)}/km"


def pace_range(fast: float | None, slow: float | None) -> str:
    """Zakres tempa; brak granicy oznacza zakres otwarty (szybciej niż / wolniej niż)."""
    if fast is None and slow is None:
        return _DASH
    if fast is None:
        return f"szybciej niż {pace(slow)}"
    if slow is None:
        return f"wolniej niż {pace(fast)}"
    return f"{_mmss(fast)}{_DASH}{_mmss(slow)}/km"


def hr_range(low: float | None, high: float | None) -> str:
    if low is None and high is None:
        return _DASH
    if low is None:
        return f"poniżej {round(high)}"
    if high is None:
        return f"od {round(low)}"
    return f"{round(low)}{_DASH}{round(high)}"


def duration(s: float | None) -> str:
    """Czas trwania Jednostki lub Aktywności, np. „1 h 05 min”, „45 min”."""
    if s is None:
        return _DASH
    minutes = round(s / 60)
    if minutes < 1:
        return f"{round(s)} s"
    hours, rest = divmod(minutes, 60)
    return f"{hours} h {rest:02d} min" if hours else f"{rest} min"


def race_time(s: float | None) -> str:
    """Czas zegarowy, np. „47:30”, „1:45:10”."""
    if s is None:
        return _DASH
    total = round(s)
    hours, rest = divmod(total, 3600)
    return f"{hours}:{rest // 60:02d}:{rest % 60:02d}" if hours else _mmss(total)


def date_pl(d: date | datetime | None) -> str:
    if d is None:
        return _DASH
    return f"{d.day}.{d.month:02d}.{d.year}"


def datetime_pl(dt: datetime | None) -> str:
    return _DASH if dt is None else f"{date_pl(dt)} {dt:%H:%M}"


def plural(n: int, one: str, few: str, many: str) -> str:
    if n == 1:
        return one
    if n % 10 in (2, 3, 4) and n % 100 not in (12, 13, 14):
        return few
    return many


def weeks(n: int) -> str:
    return f"{n} {plural(n, 'Tydzień', 'Tygodnie', 'Tygodni')}"


def days(n: int) -> str:
    return f"{n} {plural(n, 'dzień', 'dni', 'dni')}"


_WEEKDAYS = ["poniedziałek", "wtorek", "środa", "czwartek", "piątek", "sobota", "niedziela"]


def weekday_pl(d: date | datetime) -> str:
    return _WEEKDAYS[d.weekday()]


def parse_time(text: str) -> int:
    """„mm:ss” lub „h:mm:ss” na sekundy; ValueError z komunikatem po polsku, gdy format jest zły."""
    parts = text.strip().split(":")
    if len(parts) not in (2, 3) or not all(p.isdigit() for p in parts):
        raise ValueError("Podaj czas jako mm:ss lub h:mm:ss, np. 44:00 albo 1:45:00.")
    nums = [int(p) for p in parts]
    if any(n >= 60 for n in nums[1:]):
        raise ValueError("Minuty i sekundy muszą być mniejsze od 60.")
    seconds = nums[-1] + 60 * nums[-2] + (3600 * nums[0] if len(nums) == 3 else 0)
    if seconds < 1:
        raise ValueError("Czas docelowy musi być dodatni.")
    return seconds
