"""Ekran „Analiza”: Wskaźniki, Próg, Strefy, obciążenie, porównanie z Garminem, Interpretacja."""

import pandas as pd
import streamlit as st
from pydantic import ValidationError

from llmrunplanner.domain import AthleteMetrics, GarminComparisonRow, HistorySummary, Interpretation, InterpretationCheck
from llmrunplanner.metrics import SEILER_ZONE
from llmrunplanner.summary.params import DECOUPLING_OUTLIER_PCT, SUMMARY_WEEKS, TREND_BLOCK_WEEKS
from llmrunplanner.ui import charts, data, state
from llmrunplanner.ui import format as f
from llmrunplanner.ui.components import model_label, show_interpretation, table
from llmrunplanner.ui.theme import STATUS

_HR_MAX_SOURCE = {"override": "wartość ręczna", "data": "z danych"}
_HR_REST_SOURCE = {"override": "wartość ręczna", "garmin": "Garmin Connect", "default": "wartość domyślna"}
_SEILER_NAME = {1: "Niska", 2: "Umiarkowana", 3: "Wysoka"}


def _chart(fig, *tables: pd.DataFrame, key: str = "", precision: int = 1) -> None:
    st.plotly_chart(fig, theme="streamlit", width="stretch", key=f"chart_{key}")
    with st.expander("Tabela"):
        for df in tables:
            table(df, precision)


def _signed(value: float, fmt) -> str:
    sign = "+" if value > 0 else "−" if value < 0 else ""
    return sign + fmt(abs(value))


_UNIT_FORMATS = {
    "s/km": (f.pace, lambda v: f"{f.num(v, 1)} s/km"),
    "s": (f.race_time, f.race_time),
    "uderzenia/min": (lambda v: f.num(v, 0), lambda v: f"{f.num(v, 0)} ud./min"),
    "ml/kg/min": (lambda v: f.num(v, 1), lambda v: f.num(v, 1)),
}


def _comparison_table(rows: list[GarminComparisonRow]) -> pd.DataFrame:
    out = []
    for r in rows:
        show, show_diff = _UNIT_FORMATS.get(r.unit, (lambda v: f.num(v, 1), lambda v: f.num(v, 1)))
        out.append(
            {
                "Wskaźnik": r.name,
                "Nasze": show(r.ours) if r.ours is not None else "–",
                "Garmin": show(r.garmin) if r.garmin is not None else "–",
                "Różnica": _signed(r.diff, show_diff) if r.diff is not None else "–",
                "Data wartości Garmina": f.date_pl(r.garmin_date),
            }
        )
    return pd.DataFrame(out)


def _header(athlete_activities: int, metrics: AthleteMetrics, summary: HistorySummary) -> None:
    hp = metrics.hr_profile
    cols = st.columns(3)
    cols[0].metric("Aktywności przed Datą odcięcia", athlete_activities)
    cols[1].metric("Ostatnie 4 tygodnie [km/tydz.]", f.num(summary.avg_weekly_km_last_4w))
    cols[2].metric("HRmax / HRspocz [ud./min]", f"{hp.hr_max} / {hp.hr_rest}")
    cols = st.columns(3)
    cols[0].metric("CTL", f.num(summary.ctl))
    cols[1].metric("ATL", f.num(summary.atl))
    cols[2].metric("TSB", f.num(summary.tsb))
    st.caption(
        f"CTL, ATL i TSB rano w Dniu stanu ({f.date_pl(summary.as_of)}), czyli po ostatnim dniu przed Datą odcięcia. "
        f"HRmax: {_HR_MAX_SOURCE[hp.hr_max_source]}; HRspocz: {_HR_REST_SOURCE[hp.hr_rest_source]}."
    )


def _threshold(metrics: AthleteMetrics) -> None:
    st.subheader("Próg")
    st.caption(
        "Próg to tempo i tętno możliwe do utrzymania przez ok. godzinę; tempo wynika z modelu prędkości krytycznej "
        "dopasowanego do najlepszych odcinków 3–20 min. Odcinki treningowe nie są maksymalne, więc to estymacja zaniżona."
    )
    th = metrics.threshold
    cs = th.critical_speed
    if th.pace_s_per_km is None:
        st.warning("Nie udało się wyznaczyć Progu tempa z dostępnych Aktywności.")
    cols = st.columns(6)
    cols[0].metric("Tempo progowe", f.pace(th.pace_s_per_km))
    cols[1].metric("Tętno progowe [ud./min]", th.hr_bpm if th.hr_bpm is not None else "–")
    cols[2].metric("Okno", f.days(th.window_days))
    cols[3].metric("CV [m/s]", f.num(cs.cv_mps, 2))
    cols[4].metric("D′ [m]", f.num(cs.d_prime_m, 0))
    cols[5].metric("R²", f.num(cs.r2, 3))
    s = STATUS["ok" if cs.valid else "error"]
    st.write(f"{s['icon']} **{'Dopasowanie wiarygodne' if cs.valid else 'Dopasowanie niewiarygodne'}**")
    for text in [*cs.issues, *th.hr_issues, *th.warnings]:
        st.write(f"{STATUS['warning']['icon']} {text}")
    if cs.cv_mps is not None and cs.d_prime_m is not None and cs.efforts:
        fig, df = charts.efforts_chart(cs.efforts, cs.cv_mps, cs.d_prime_m)
        _chart(fig, df, key="efforts")


def _zones(metrics: AthleteMetrics) -> None:
    st.subheader("Strefy")
    st.caption("Strefy Z1–Z5 według Friela, liczone od Progu; grupy Seilera łączą je w trzy poziomy intensywności.")
    if metrics.zones is None:
        st.info("Strefy wymagają Progu tempa i tętna, a tych nie udało się wyznaczyć.")
        return
    table(
        pd.DataFrame(
            {
                "Strefa": [z.zone.value for z in metrics.zones],
                "Tętno [ud./min]": [f.hr_range(z.hr_low, z.hr_high) for z in metrics.zones],
                "Tempo": [f.pace_range(z.pace_fast_s_per_km, z.pace_slow_s_per_km) for z in metrics.zones],
                "Tempo reprezentatywne": [f.pace(z.pace_mid_s_per_km) for z in metrics.zones],
                "Grupa Seilera": [_SEILER_NAME[SEILER_ZONE[z.zone]] for z in metrics.zones],
            }
        )
    )


def _volume(summary: HistorySummary) -> None:
    st.subheader("Objętość")
    st.caption(
        f"Okna 7-dniowe liczone wstecz od Dnia stanu, tak jak w Podsumowaniu historii ({len(summary.weekly_volumes)} okien)."
    )
    fig, df = charts.volume_chart(summary)
    _chart(fig, df, key="volume")
    fig, df = charts.trimp_chart(summary)
    _chart(fig, df, key="trimp")


def _load(metrics: AthleteMetrics) -> None:
    st.subheader("Obciążenie")
    st.caption("CTL i ATL to średnie wykładnicze z 42 i 7 dni dziennego TRIMP; TSB to ich różnica (świeżość).")
    fig, df = charts.load_chart(metrics)
    _chart(fig, df, key="load")
    fig, df = charts.tsb_chart(metrics)
    _chart(fig, df, key="tsb")


def _fitness(metrics: AthleteMetrics, summary: HistorySummary) -> None:
    st.subheader("Wydolność")
    st.caption(
        "EF (stosunek prędkości do tętna na spokojnych biegach) rośnie wraz z wydolnością tlenową. Punkty obejmują "
        f"całą historię, a linia to mediany z okresów {TREND_BLOCK_WEEKS}-tygodniowych tylko z ostatnich "
        f"{SUMMARY_WEEKS} tygodni przed Datą odcięcia (tak jak w Podsumowaniu historii)."
    )
    ef = [(m.date, m.ef) for m in metrics.activities if m.ef is not None]
    if ef:
        fig, df, medians = charts.trend_chart(
            ef, summary.ef_trend, name="EF biegu", trend_name="Mediana 4 tygodni", unit="m/uderzenie", digits=2,
            title="EF biegów kwalifikujących się do analizy",
        )
        _chart(fig, df, medians, key="ef", precision=3)
    else:
        st.info("Brak biegów kwalifikujących się do wyliczenia EF.")
    dec = [(m.date, m.decoupling_pct) for m in metrics.activities if m.decoupling_pct is not None]
    if dec:
        fig, df, medians = charts.trend_chart(
            dec, summary.decoupling_trend_pct, name="Decoupling biegu", trend_name="Mediana 4 tygodni", unit="%", digits=1,
            title="Decoupling tętno–tempo równych biegów",
        )
        _chart(fig, df, medians, key="decoupling")
        st.caption(
            f"Punkty pokazują wszystkie równe biegi (co najmniej 45 min, głównie Z1–Z2); do mediany nie wchodzą wartości "
            f"spoza ±{f.num(DECOUPLING_OUTLIER_PCT, 0)}%."
        )
    else:
        st.info("Brak równych biegów, dla których da się policzyć decoupling.")


def _intensity(summary: HistorySummary) -> None:
    st.subheader("Rozkład intensywności")
    st.caption(
        "Udział czasu w Strefach z ostatnich okien Podsumowania historii. Tętno zaniża intensywność interwałów, "
        "bo opóźnia się względem wysiłku (Bellinger i in. 2020), więc rozkład ze Stref tempa bywa bardziej „w górę”."
    )
    fig, df = charts.zones_chart(summary)
    _chart(fig, df, key="zones")
    if not summary.zone_distribution_pace_pct:
        st.info("Rozkład ze Stref tempa wymaga biegów na zewnątrz z GPS i Progu tempa; takich danych brak.")
    fig, df = charts.seiler_chart(summary)
    _chart(fig, df, key="seiler")


def _predictions(metrics: AthleteMetrics) -> None:
    st.subheader("Prognozy")
    st.caption(
        "Prognoza czasu wzorem Riegela; wykładnik 1,06 jest optymistyczny, 1,10 ostrożny "
        "(dla amatorów na maratonie bardziej realistyczne są wyższe wartości)."
    )
    if not metrics.predictions:
        st.info("Brak prognoz: nie ma wystarczających danych o najlepszych odcinkach.")
        return
    rows = {}
    for p in metrics.predictions:
        rows.setdefault(p.distance, {"Dystans": p.distance.label})[f"Wykładnik {f.num(p.exponent, 2)}"] = f.race_time(p.time_s)
    table(pd.DataFrame(list(rows.values())))


def _garmin(metrics: AthleteMetrics) -> None:
    st.subheader("Porównanie z Garminem")
    st.caption("Wartości liczone w systemie obok wartości wyliczonych przez Garmina (różnica = nasze − Garmin).")
    if not metrics.garmin_comparison:
        st.info("Brak wartości Garmina dla tego Biegacza i Daty odcięcia.")
        return
    table(_comparison_table(metrics.garmin_comparison))


def _interpretation(athlete_id: str, cutoff) -> None:
    st.subheader("Interpretacja")
    st.caption("Opis Historii treningowej przygotowany przez model; każda liczba ma cytat pola Podsumowania historii.")
    saved = [p for p in data.plans(athlete_id) if p.data_cutoff == cutoff and p.interpretation_json]
    if not saved:
        st.info("Dla tej Daty odcięcia nie ma jeszcze Interpretacji. Powstaje razem z Planem na ekranie „Cel i Plan”.")
        return
    record = max(saved, key=lambda p: p.created_at)
    try:
        interp = Interpretation.model_validate_json(record.interpretation_json)
        check = (
            InterpretationCheck.model_validate_json(record.interpretation_check_json)
            if record.interpretation_check_json
            else None
        )
    except ValidationError:
        st.warning("Zapisana Interpretacja ma nieczytelny format.")
        return
    created = f.datetime_pl(record.created_at.astimezone(data.LOCAL_TZ))
    st.caption(f"Model: {model_label(record.model_key)}, zapisano {created}.")
    show_interpretation(interp, check)


def main() -> None:
    st.title("Analiza")
    athlete_id, cutoff = state.athlete_id(), state.cutoff()
    if athlete_id is None or cutoff is None:
        st.info("Najpierw dodaj Biegacza na ekranie „Biegacz”.")
        return
    athlete, activities, metrics, summary = data.athlete_metrics(athlete_id, cutoff)
    if metrics is None or summary is None:
        st.info(
            f"Przed Datą odcięcia {f.date_pl(cutoff)} nie ma Aktywności tego Biegacza. "
            "Zmień Datę odcięcia lub zsynchronizuj dane na ekranie „Biegacz”."
        )
        return
    _header(len(activities), metrics, summary)
    _threshold(metrics)
    _zones(metrics)
    _volume(summary)
    _load(metrics)
    _fitness(metrics, summary)
    _intensity(summary)
    _predictions(metrics)
    _garmin(metrics)
    _interpretation(athlete_id, cutoff)
    with st.expander("Podsumowanie historii (dane dla modelu)"):
        st.json(summary.model_dump(mode="json"))


main()
