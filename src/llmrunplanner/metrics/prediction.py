from ..domain import CriticalSpeed, Distance, RacePrediction
from .params import RIEGEL_EXPONENTS, RIEGEL_REFERENCE_M


def race_predictions(cs: CriticalSpeed) -> list[RacePrediction]:
    if not cs.valid or cs.cv_mps is None or cs.d_prime_m is None:
        return []
    t_ref = (RIEGEL_REFERENCE_M - cs.d_prime_m) / cs.cv_mps
    return [
        RacePrediction(
            distance=distance,
            exponent=b,
            time_s=t_ref * (distance.km * 1000 / RIEGEL_REFERENCE_M) ** b,
        )
        for distance in Distance
        for b in RIEGEL_EXPONENTS
    ]
