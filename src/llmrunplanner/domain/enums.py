from enum import StrEnum


class Sex(StrEnum):
    M = "M"
    F = "F"


class ActivitySource(StrEnum):
    GARMIN = "garmin"
    IMPORT = "import"
    PUBLIC = "public"


class SubSport(StrEnum):
    STREET = "street"  # bieg na zewnątrz po drogach, także FIT sub_sport=generic
    TREADMILL = "treadmill"
    TRAIL = "trail"
    TRACK = "track"


class Zone(StrEnum):
    """Strefa intensywności według Friela, liczona względem Progu Biegacza (tempo i tętno możliwe do
    utrzymania przez ok. godzinę). Tempo jako % tempa progowego, tętno jako % tętna progowego:
    Z1 – regeneracja, tempo wolniejsze niż 129%, tętno poniżej 85%; Z2 – spokojny bieg tlenowy, tempo
    114–129%, tętno 85–89%; Z3 – umiarkowanie, tempo 106–113%, tętno 90–94%; Z4 – próg, tempo 101–105%,
    tętno 95–99%; Z5 – powyżej progu, tempo 100% i szybciej, tętno od 100%. Z1–Z2 to intensywność niska,
    Z3 umiarkowana, Z4–Z5 wysoka."""

    Z1 = "Z1"
    Z2 = "Z2"
    Z3 = "Z3"
    Z4 = "Z4"
    Z5 = "Z5"


class Phase(StrEnum):
    """Faza Planu, w kolejności: BASE – bazowa, BUILD – budująca, PEAK – szczytowa, TAPER – zmniejszenie
    objętości przed startem."""

    BASE = "BASE"
    BUILD = "BUILD"
    PEAK = "PEAK"
    TAPER = "TAPER"


class Distance(StrEnum):
    K5 = "5K"
    K10 = "10K"
    HM = "HM"
    M = "M"

    @property
    def km(self) -> float:
        return _DISTANCE_KM[self]

    @property
    def label(self) -> str:
        """Polska nazwa dystansu do komunikatów, np. „10 km”, „półmaraton”."""
        return _DISTANCE_LABEL[self]


_DISTANCE_KM = {
    Distance.K5: 5.0,
    Distance.K10: 10.0,
    Distance.HM: 21.0975,
    Distance.M: 42.195,
}

_DISTANCE_LABEL = {
    Distance.K5: "5 km",
    Distance.K10: "10 km",
    Distance.HM: "półmaraton",
    Distance.M: "maraton",
}


class WorkoutType(StrEnum):
    """Typ jednostki z Katalogu jednostek. RECOVERY – bieg regeneracyjny w Z1; EASY – spokojny
    bieg w Z1–Z2, opcjonalnie z krótkimi przebieżkami; LONG – długie wybieganie, głównie w Z2;
    TEMPO – ciągły bieg w Z3–Z4 po rozgrzewce; THRESHOLD_INTERVALS – powtórzenia w Z4 z przerwami w Z1;
    VO2MAX_INTERVALS – powtórzenia w Z5 z przerwami w Z1. Jednostki jakościowe: TEMPO, THRESHOLD_INTERVALS,
    VO2MAX_INTERVALS; Jednostki kluczowe: jakościowe i LONG. Start nie jest Jednostką: dopisuje go kod."""

    RECOVERY = "RECOVERY"
    EASY = "EASY"
    LONG = "LONG"
    TEMPO = "TEMPO"
    THRESHOLD_INTERVALS = "THRESHOLD_INTERVALS"
    VO2MAX_INTERVALS = "VO2MAX_INTERVALS"

    @property
    def is_quality(self) -> bool:
        return self in (
            WorkoutType.TEMPO,
            WorkoutType.THRESHOLD_INTERVALS,
            WorkoutType.VO2MAX_INTERVALS,
        )

    @property
    def is_key(self) -> bool:
        return self.is_quality or self is WorkoutType.LONG


class GateStatus(StrEnum):
    """Wynik Bramki bezpieczeństwa: OK – można planować, WARN – można planować z ostrzeżeniem,
    STOP – Plan nie powstaje."""

    OK = "OK"
    WARN = "WARN"
    STOP = "STOP"


class RuleKind(StrEnum):
    HARD = "HARD"
    SOFT = "SOFT"


class GarminMetricKind(StrEnum):
    LT_HR = "lt_hr"
    LT_SPEED = "lt_speed"
    VO2MAX = "vo2max"
    RESTING_HR = "resting_hr"
    RACE_PRED_5K = "race_pred_5k"
    RACE_PRED_10K = "race_pred_10k"
    RACE_PRED_HM = "race_pred_hm"
    RACE_PRED_M = "race_pred_m"
