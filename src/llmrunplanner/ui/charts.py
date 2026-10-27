"""Wykresy ekranu „Analiza”: funkcje zwracają gotowe figury plotly i tabele z tymi samymi danymi."""

from datetime import date, timedelta

import pandas as pd
import plotly.graph_objects as go

from ..domain import AthleteMetrics, BestEffort, HistorySummary, Phase, Skeleton, Zone
from . import format as f
from .theme import AQUA, BLUE, ORANGE, SEILER_COLORS, YELLOW, base_layout

ZONES = list(Zone)
SEILER_LABELS = {"low": "Niska (Z1–Z2)", "moderate": "Umiarkowana (Z3)", "high": "Wysoka (Z4–Z5)"}
_DATE_AXIS = {"type": "date", "tickformat": "%-d.%m.%Y", "hoverformat": "%-d.%m.%Y"}


def _title(fig: go.Figure, text: str) -> None:
    fig.update_layout(title_text=text)  # położenie tytułu ustala base_layout


def efforts_chart(efforts: list[BestEffort], cv_mps: float, d_prime_m: float) -> tuple[go.Figure, pd.DataFrame]:
    efforts = sorted(efforts, key=lambda e: e.duration_s)
    t_max = max(e.duration_s for e in efforts) * 1.05
    fig = go.Figure()
    fig.add_scatter(
        x=[e.duration_s / 60 for e in efforts],
        y=[e.distance_m for e in efforts],
        mode="markers",
        name="Najlepsze odcinki",
        marker={"color": BLUE, "size": 10},
        customdata=[[f.race_time(e.duration_s), f.date_pl(e.date), f.pace(e.duration_s / e.distance_m * 1000)] for e in efforts],
        hovertemplate="Czas: %{customdata[0]}<br>Dystans: %{y:.0f} m<br>Tempo: %{customdata[2]}<br>Dzień: %{customdata[1]}<extra></extra>",
    )
    fig.add_scatter(
        x=[0, t_max / 60],
        y=[d_prime_m, cv_mps * t_max + d_prime_m],
        mode="lines",
        name="Model prędkości krytycznej",
        line={"color": ORANGE, "width": 2},
        hovertemplate="Dystans modelu: %{y:.0f} m<extra></extra>",
    )
    base_layout(fig, height=360)
    _title(fig, "Dystans odcinka w zależności od czasu (dystans = CV · czas + D′)")
    fig.update_xaxes(title="Czas odcinka [min]")
    fig.update_yaxes(title="Dystans [m]")
    fig.update_layout(hovermode="closest")
    table = pd.DataFrame(
        {
            "Czas": [f.race_time(e.duration_s) for e in efforts],
            "Dystans [m]": [round(e.distance_m) for e in efforts],
            "Tempo": [f.pace(e.duration_s / e.distance_m * 1000) for e in efforts],
            "Dzień": [f.date_pl(e.date) for e in efforts],
        }
    )
    return fig, table


def _week_bars(
    summary: HistorySummary, attr: str, name: str, unit: str, digits: int, column: str
) -> tuple[go.Figure, pd.DataFrame]:
    weeks = summary.weekly_volumes
    xs = [w.week_start for w in weeks]
    ys = [getattr(w, attr) for w in weeks]
    fig = go.Figure(
        go.Bar(
            x=xs,
            y=ys,
            name=name,
            marker_color=BLUE,
            customdata=[f.num(y, digits) for y in ys],
            hovertemplate=f"Okno 7 dni od %{{x|%-d.%m.%Y}}<br>{name}: %{{customdata}} {unit}<extra></extra>",
        )
    )
    base_layout(fig, height=340)
    _title(fig, f"{name} w oknach 7-dniowych [{unit}]")
    fig.update_xaxes(**_DATE_AXIS, tickvals=xs)
    fig.update_yaxes(title=unit)
    table = pd.DataFrame({"Początek okna": [f.date_pl(x) for x in xs], column: [float(y) for y in ys]})
    return fig, table


def volume_chart(summary: HistorySummary) -> tuple[go.Figure, pd.DataFrame]:
    return _week_bars(summary, "distance_km", "Objętość", "km", 1, "Dystans [km]")


def trimp_chart(summary: HistorySummary) -> tuple[go.Figure, pd.DataFrame]:
    return _week_bars(summary, "trimp", "TRIMP", "TRIMP", 0, "TRIMP")


def load_chart(metrics: AthleteMetrics, days: int = 120) -> tuple[go.Figure, pd.DataFrame]:
    points = metrics.load[-days:]
    xs = [p.date for p in points]
    fig = go.Figure()
    for name, attr, color in (("CTL (obciążenie przewlekłe)", "ctl", BLUE), ("ATL (obciążenie ostre)", "atl", ORANGE)):
        ys = [getattr(p, attr) for p in points]
        fig.add_scatter(
            x=xs,
            y=ys,
            mode="lines",
            name=name,
            line={"color": color, "width": 2},
            customdata=[f.num(y) for y in ys],
            hovertemplate=f"{name.split(' ')[0]}: %{{customdata}}<extra></extra>",
        )
    base_layout(fig, height=360)
    _title(fig, f"CTL i ATL, ostatnie {len(points)} dni")
    fig.update_xaxes(**_DATE_AXIS)
    fig.update_yaxes(title="TRIMP na dzień")
    table = pd.DataFrame(
        {
            "Dzień": [f.date_pl(p.date) for p in points],
            "CTL": [p.ctl for p in points],
            "ATL": [p.atl for p in points],
            "TSB": [p.tsb for p in points],
        }
    )
    return fig, table


def tsb_chart(metrics: AthleteMetrics, days: int = 120) -> tuple[go.Figure, pd.DataFrame]:
    points = metrics.load[-days:]
    ys = [p.tsb for p in points]
    fig = go.Figure(
        go.Scatter(
            x=[p.date for p in points],
            y=ys,
            mode="lines",
            name="TSB",
            line={"color": AQUA, "width": 2},
            customdata=[f.num(y) for y in ys],
            hovertemplate="TSB: %{customdata}<extra></extra>",
        )
    )
    fig.add_hline(y=0, line={"color": "rgba(128,128,128,0.7)", "width": 1, "dash": "dot"})
    base_layout(fig, height=300)
    _title(fig, "TSB (równowaga obciążenia, CTL − ATL)")
    fig.update_xaxes(**_DATE_AXIS)
    fig.update_yaxes(title="TSB")
    table = pd.DataFrame({"Dzień": [f.date_pl(p.date) for p in points], "TSB": ys})
    return fig, table


def _trend_x(period_start: date) -> date:
    return period_start + timedelta(days=14)  # środek okresu 4-tygodniowego


def trend_chart(
    points: list[tuple[date, float]],
    trend: list,
    *,
    name: str,
    trend_name: str,
    unit: str,
    digits: int,
    title: str,
) -> tuple[go.Figure, pd.DataFrame, pd.DataFrame]:
    fig = go.Figure()
    fig.add_scatter(
        x=[d for d, _ in points],
        y=[v for _, v in points],
        mode="markers",
        name=name,
        marker={"color": BLUE, "size": 8, "opacity": 0.8},
        customdata=[f.num(v, digits) for _, v in points],
        hovertemplate=f"{name}: %{{customdata}}<extra></extra>",
    )
    if trend:
        fig.add_scatter(
            x=[_trend_x(t.period_start) for t in trend],
            y=[t.value for t in trend],
            mode="lines+markers",
            name=trend_name,
            line={"color": ORANGE, "width": 2},
            marker={"color": ORANGE, "size": 9},
            customdata=[[f.num(t.value, digits), t.n] for t in trend],
            hovertemplate=f"{trend_name}: %{{customdata[0]}} (biegi: %{{customdata[1]}})<extra></extra>",
        )
    base_layout(fig, height=360)
    _title(fig, title)
    fig.update_xaxes(**_DATE_AXIS)
    fig.update_yaxes(title=unit)
    table = pd.DataFrame(
        {"Dzień": [f.date_pl(d) for d, _ in points], f"{name} [{unit}]": [float(v) for _, v in points]}
    )
    medians = pd.DataFrame(
        {
            "Początek okresu": [f.date_pl(t.period_start) for t in trend],
            f"{trend_name} [{unit}]": [float(t.value) for t in trend],
            "Biegi": [t.n for t in trend],
        }
    )
    return fig, table, medians


def zones_chart(summary: HistorySummary) -> tuple[go.Figure, pd.DataFrame]:
    hr = [summary.zone_distribution_hr_pct.get(z, 0) for z in ZONES]
    pace = [summary.zone_distribution_pace_pct.get(z) for z in ZONES] if summary.zone_distribution_pace_pct else None
    fig = go.Figure()
    series = [("Ze Stref tętna", hr, BLUE)] + ([("Ze Stref tempa", pace, ORANGE)] if pace else [])
    for name, vals, color in series:
        fig.add_bar(
            x=[z.value for z in ZONES],
            y=vals,
            name=name,
            marker_color=color,
            hovertemplate=f"{name}: %{{y}}% czasu<extra></extra>",
        )
    base_layout(fig, height=360)
    fig.update_layout(barmode="group")
    _title(fig, "Udział czasu w Strefach [%]")
    fig.update_yaxes(title="% czasu")
    table = pd.DataFrame({"Strefa": [z.value for z in ZONES], "Tętno [%]": hr})
    if pace:
        table["Tempo [%]"] = pace
    return fig, table


def seiler_chart(summary: HistorySummary) -> tuple[go.Figure, pd.DataFrame]:
    rows = {"Ze Stref tętna": summary.intensity_distribution_seiler_hr_pct}
    if summary.intensity_distribution_seiler_pace_pct:
        rows["Ze Stref tempa"] = summary.intensity_distribution_seiler_pace_pct
    fig = go.Figure()
    for key, label in SEILER_LABELS.items():
        fig.add_bar(
            y=list(rows),
            x=[r.get(key, 0) for r in rows.values()],
            orientation="h",
            name=label,
            marker_color=SEILER_COLORS[key],
            text=[f"{r.get(key, 0)}%" for r in rows.values()],
            textposition="inside",
            hovertemplate=f"{label}: %{{x}}% czasu<extra></extra>",
        )
    base_layout(fig, height=110 + 70 * len(rows), legend=True)
    fig.update_layout(barmode="stack", hovermode="closest", legend_traceorder="normal")
    _title(fig, "Rozkład intensywności w 3 strefach Seilera [%]")
    fig.update_xaxes(range=[0, 100], title="% czasu")
    fig.update_yaxes(autorange="reversed")
    table = pd.DataFrame({"Metoda": list(rows), **{lab: [r.get(k, 0) for r in rows.values()] for k, lab in SEILER_LABELS.items()}})
    return fig, table


PHASE_COLORS = {Phase.BASE: BLUE, Phase.BUILD: ORANGE, Phase.PEAK: AQUA, Phase.TAPER: YELLOW}
PHASE_LABELS = {
    Phase.BASE: "BASE (bazowa)",
    Phase.BUILD: "BUILD (budująca)",
    Phase.PEAK: "PEAK (szczytowa)",
    Phase.TAPER: "TAPER (przed startem)",
}


def skeleton_chart(skeleton: Skeleton, week_starts: dict[int, date]) -> go.Figure:
    """Objętość tygodniowa Szkieletu; kolor oznacza Fazę."""
    fig = go.Figure()
    for phase in Phase:
        weeks = [w for w in skeleton.weeks if w.phase is phase]
        if not weeks:
            continue
        fig.add_bar(
            x=[w.number for w in weeks],
            y=[w.target_volume_km for w in weeks],
            name=PHASE_LABELS[phase],
            marker_color=PHASE_COLORS[phase],
            customdata=[[f.num(w.target_volume_km), f.date_pl(week_starts.get(w.number))] for w in weeks],
            hovertemplate="Tydzień %{x} (od %{customdata[1]})<br>Objętość: %{customdata[0]} km<extra>" + PHASE_LABELS[phase] + "</extra>",
        )
    base_layout(fig, height=340, legend=True)
    _title(fig, "Docelowa objętość Tygodni Szkieletu [km]")
    fig.update_xaxes(title="Tydzień", type="category")
    fig.update_yaxes(title="km")
    return fig
