"""Elementy wspólne ekranów: tabele, Interpretacja, stan wyniku, koszt i nazwa modelu."""

import pandas as pd
import streamlit as st

from ..domain import Interpretation, InterpretationCheck
from ..llm import MODELS
from . import format as f
from .theme import STATUS

_ROW_PX = 35
_MAX_FULL_ROWS = 25
_STATUS_LABELS = {
    "ok": "zatwierdzony",
    "niezatwierdzony": "niezatwierdzony",
    "pominięty": "pominięty",
    "błąd API": "błąd API",
    "wstrzymany": "wstrzymany",
}


def table(df: pd.DataFrame, precision: int | dict[str, int] = 1) -> None:
    """Tabela w polskiej konwencji: przecinek dziesiętny, „–” dla braków, bez separatora tysięcy. Liczby
    zmiennoprzecinkowe mają 1 miejsce po przecinku albo tyle, ile podano dla kolumny. Krótka tabela
    pokazuje wszystkie wiersze bez wewnętrznego przewijania."""
    default = precision if isinstance(precision, int) else 1
    per_column = precision if isinstance(precision, dict) else {}

    def text(v, digits: int) -> str:
        if pd.isna(v):
            return "–"
        return f.num(v, digits) if isinstance(v, float) else str(v)

    # Streamlit pokazuje pustą komórkę jako „None” mimo na_rep, więc kolumny z brakami idą jako gotowy tekst.
    df = df.assign(
        **{c: [text(v, per_column.get(c, default)) for v in df[c]] for c in df.columns if df[c].isna().any()}
    )
    formatters = {
        c: (lambda v, d=per_column.get(c, default): f.num(v, d))
        for c in df.columns
        if pd.api.types.is_float_dtype(df[c])
    }
    styler = df.style.format(formatter=formatters)
    height = (len(df) + 1) * _ROW_PX + 3 if len(df) <= _MAX_FULL_ROWS else "auto"
    st.dataframe(styler, hide_index=True, width="stretch", height=height)


def cited_value(field_path: str, value: float) -> str:
    """Wartość cytowanego pola Podsumowania historii: tempo jako m:ss/km, czas jako m:ss, liczby całkowite bez
    części ułamkowej."""
    leaf = field_path.rsplit(".", 1)[-1]
    if "s_per_km" in leaf:
        return f.pace(value)
    if leaf.endswith("_s"):
        return f.race_time(value)
    if float(value).is_integer():
        return f.num(value, 0)
    return f.num(value, 3).rstrip("0").rstrip(",")


def show_interpretation(interp: Interpretation, check: InterpretationCheck | None) -> None:
    sections = [
        ("Trendy", interp.trends),
        ("Mocne strony", interp.strengths),
        ("Słabe strony", interp.weaknesses),
        ("Ryzyka", interp.risks),
        ("Gotowość do Celu", [interp.readiness]),
    ]
    for title, statements in sections:
        st.markdown(f"**{title}**")
        for s in statements:
            st.markdown(f"- {s.text}")
            if s.citations:
                st.caption("Cytaty: " + "; ".join(f"`{c.field}` = {cited_value(c.field, c.value)}" for c in s.citations))
    if check is None:
        return
    ok = check.matched == check.total and not check.uncited
    status = STATUS["ok" if ok else "warning"]
    st.markdown(
        f"{status['icon']} **Zgodne liczby: {check.matched}/{check.total}** · **Liczby bez cytatu: {len(check.uncited)}**"
    )
    failing = [c for c in check.checks if not c.ok]
    if failing:
        err = STATUS["error"]
        table(
            pd.DataFrame(
                {
                    "Stan": [f"{err['icon']} {err['label']}"] * len(failing),
                    "Pole": [c.field for c in failing],
                    "Podana liczba": [cited_value(c.field, c.cited) for c in failing],
                    "Wartość w Podsumowaniu": [
                        cited_value(c.field, c.actual) if c.actual is not None else None for c in failing
                    ],
                    "Przyczyna": [c.reason for c in failing],
                }
            )
        )
    if check.uncited:
        st.caption("Liczby bez cytatu: " + ", ".join(check.uncited))


def status_label(status: str) -> str:
    return _STATUS_LABELS.get(status, status)


def status_line(status: str) -> str:
    """Stan Planu, Szkieletu lub Tygodnia z ikoną: zatwierdzony ✅, pominięty ⚠️, pozostałe ⛔."""
    kind = "ok" if status == "ok" else "warning" if status == "pominięty" else "error"
    return f"{STATUS[kind]['icon']} {status_label(status)}"


def usd(cost: float | None) -> str:
    return f.num(cost, 4)


def model_label(key: str) -> str:
    return MODELS[key].label if key in MODELS else key
