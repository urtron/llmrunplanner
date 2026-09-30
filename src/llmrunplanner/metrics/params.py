from ..domain import Sex, Zone

MAX_SAMPLE_GAP_S = 5
# okno centrowane, z którego liczy się prędkość z dystansu (pole speed_mps z FIT bywa zawyżone na bieżni lekkoatletycznej)
SPEED_SMOOTH_S = 10

HR_VALID_MIN = 35
HR_VALID_MAX = 230
HR_SPIKE_WINDOW = 11
HR_SPIKE_BPM = 20
# czujnik optyczny podający kadencję zamiast tętna: tętno ≈ 2 · kadencja (FIT: jedna noga)
CADENCE_LOCK_TOLERANCE_BPM = 3
CADENCE_LOCK_MIN_S = 60
CADENCE_LOCK_MIN_CADENCE = 60
# blokada to zmiany tętna idące razem ze zmianami 2 · kadencji (korelacja różnic 5 s)
CADENCE_LOCK_MIN_CORR = 0.7
CADENCE_LOCK_DIFF_S = 5
CADENCE_LOCK_MIN_DIFFS = 10
CADENCE_LOCK_EXACT_BPM = 1
HR_MAX_SMOOTH_WINDOW = 5
HR_REST_WINDOW_DAYS = 30
HR_REST_DEFAULT = 60

# (a, b) w TRIMP Banistera: a · x · e^(b·x)
TRIMP_COEFFS = {Sex.M: (0.64, 1.92), Sex.F: (0.86, 1.67)}

CTL_DAYS = 42
ATL_DAYS = 7
LOAD_INIT_DAYS = 28

THRESHOLD_WINDOW_DAYS = 84
THRESHOLD_FALLBACK_WINDOW_DAYS = 182
EFFORT_DURATIONS_S = (180, 240, 300, 420, 600, 720, 900, 1200)
EFFORT_MAX_SPEED_MPS = 7.0
# szybciej niż jakikolwiek biegacz: większy skok dystansu między próbkami to błąd GPS
EFFORT_MAX_STEP_SPEED_MPS = 10.0
CV_MIN_EFFORTS = 3
CV_MIN_R2 = 0.95
D_PRIME_MIN_M = 30
D_PRIME_MAX_M = 500
# poniżej tej wartości odcinki były prawdopodobnie niemaksymalne
D_PRIME_SUBMAXIMAL_M = 100
CV_MIN_MPS = 2.0
CV_MAX_MPS = 6.5
THRESHOLD_HR_WINDOW_S = 1200
THRESHOLD_HR_MIN_VALID_SHARE = 0.9
THRESHOLD_HR_MIN_FRACTION = 0.75
THRESHOLD_HR_MAX_FRACTION = 0.97

# granice Stref jako ułamek progu; tempo: iloraz tempa i tempa progowego (wolniej = więcej),
# środki między całkowitymi przedziałami Friela (114–129, 106–113, 101–105, ≤100)
HR_ZONE_CUTS = (0.85, 0.90, 0.95, 1.00)
PACE_ZONE_CUTS = (1.295, 1.135, 1.055, 1.005)
# tempo reprezentatywne Strefy jako ułamek tempa progowego (Z2–Z4: środki przedziałów PACE_ZONE_CUTS)
ZONE_PACE_MID_FACTORS = {Zone.Z1: 1.35, Zone.Z2: 1.215, Zone.Z3: 1.095, Zone.Z4: 1.03, Zone.Z5: 0.97}
MOVING_MIN_SPEED_MPS = 1.0

EF_MIN_DURATION_S = 1200
EASY_MIN_SHARE = 0.8  # udział czasu z poprawnym tętnem w Z1–Z2
STEADY_MIN_DURATION_S = 2700
STEADY_MAX_SPEED_CV = 0.10
STEADY_SMOOTH_S = 30
STEADY_MAX_GAIN_M_PER_KM = 10
DECOUPLING_SKIP_S = 600

RIEGEL_EXPONENTS = (1.06, 1.08, 1.10)
RIEGEL_REFERENCE_M = 5000
COMPARISON_RIEGEL_EXPONENT = 1.08
# Garmin podaje prędkość progu mleczanowego w jednostkach 10 m/s (zgodnie z danymi autora i VO2max)
GARMIN_LT_SPEED_TO_MPS = 10.0
