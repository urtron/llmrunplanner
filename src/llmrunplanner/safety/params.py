from ..domain import Distance

PLAN_MIN_WEEKS = 6
PLAN_MAX_WEEKS = 20
MIN_WEEKS = {Distance.K5: 6, Distance.K10: 8, Distance.HM: 10, Distance.M: 14}

HISTORY_MIN_DAYS = 91
HISTORY_WINDOW_WEEKS = 12
HISTORY_MIN_ACTIVE_WEEKS = 10
HISTORY_MIN_RUNS = 24
HISTORY_MIN_HR_VALID_SHARE = 0.8

MIN_WEEKLY_KM = {Distance.K5: 10, Distance.K10: 15, Distance.HM: 25, Distance.M: 35}

# Wymagana poprawa względem Prognozy, na każdy Tydzień Planu (ułamek czasu).
IMPROVEMENT_OK_PER_WEEK = 0.0025
IMPROVEMENT_WARN_PER_WEEK = 0.005

# Wykładnik Riegela użyty w Bramce, zależny od dystansu (dla amatorów 1,06 jest zbyt optymistyczne na maratonie).
GATE_EXPONENTS = {Distance.K5: 1.06, Distance.K10: 1.06, Distance.HM: 1.08, Distance.M: 1.10}
TIME_ROUND_S = 10
