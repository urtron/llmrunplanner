"""Kolory i wspólny układ wykresów."""

import plotly.graph_objects as go

BLUE, ORANGE, AQUA, YELLOW = "#2a78d6", "#eb6834", "#1baf7a", "#eda100"
SEILER_COLORS = {"low": "#86b6ef", "moderate": "#2a78d6", "high": "#104281"}

# Stan nigdy nie jest oznaczany samym kolorem: zawsze ikona i etykieta.
STATUS = {
    "error": {"icon": "⛔", "label": "Błąd"},
    "warning": {"icon": "⚠️", "label": "Ostrzeżenie"},
    "ok": {"icon": "✅", "label": "OK"},
}

_GRID = "rgba(128, 128, 128, 0.18)"


def base_layout(fig: go.Figure, *, height: int = 340, legend: bool | None = None) -> go.Figure:
    """Wspólny wygląd: tło przezroczyste (motyw Streamlit), wyciszona siatka, cienkie linie, przecinek dziesiętny.
    Tytuł przy górnej krawędzi, legenda poziomo nad obszarem wykresu, domyślnie tylko dla co najmniej dwóch serii."""
    show_legend = len(fig.data) >= 2 if legend is None else legend
    fig.update_layout(
        height=height,
        margin={"l": 8, "r": 8, "t": 80, "b": 8},
        title={"x": 0, "xanchor": "left", "y": 0.97, "yref": "container", "yanchor": "top", "font": {"size": 15}},
        showlegend=show_legend,
        legend={"orientation": "h", "yanchor": "bottom", "y": 1.02, "x": 0},
        separators=", ",
        hovermode="x unified",
        font={"size": 13},
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        bargap=0.35,
    )
    fig.update_xaxes(showgrid=False, zeroline=False, linecolor=_GRID)
    fig.update_yaxes(gridcolor=_GRID, gridwidth=1, zeroline=False, showline=False)
    fig.update_traces(selector={"type": "scatter"}, line={"width": 2})
    fig.update_traces(selector={"type": "bar"}, marker_cornerradius=4)
    return fig
