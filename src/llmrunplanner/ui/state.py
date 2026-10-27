"""Typowane dostępy do st.session_state."""

from datetime import date

import streamlit as st

from ..safety import HEALTH_QUESTIONS

_ATHLETE = "athlete_id"
_CUTOFF = "cutoff"
_PENDING_ATHLETE = "_pending_athlete_id"
_CUTOFF_FOR = "_cutoff_for_athlete"


def athlete_id() -> str | None:
    return st.session_state.get(_ATHLETE)


def cutoff() -> date | None:
    return st.session_state.get(_CUTOFF)


def request_athlete(athlete_id: str) -> None:
    """Zmiana wybranego Biegacza po zbudowaniu widżetu paska bocznego: zadziała od następnego przebiegu."""
    st.session_state[_PENDING_ATHLETE] = athlete_id


def set_cutoff(d: date) -> None:
    """Do użycia jako on_click przycisku: wartość widżetu można zmienić tylko w wywołaniu zwrotnym."""
    st.session_state[_CUTOFF] = d


def apply_pending() -> None:
    """Wywoływane na początku przebiegu, przed utworzeniem widżetów wyboru."""
    if (a := st.session_state.pop(_PENDING_ATHLETE, None)) is not None:
        st.session_state[_ATHLETE] = a


def cutoff_belongs_to() -> str | None:
    return st.session_state.get(_CUTOFF_FOR)


def mark_cutoff_for(athlete_id: str | None) -> None:
    st.session_state[_CUTOFF_FOR] = athlete_id


ATHLETE_KEY = _ATHLETE
CUTOFF_KEY = _CUTOFF

# Widżety ekranu „Cel i Plan”, których wartości mają przetrwać przejście na inny ekran.
PLAN_DISTANCE_KEY = "plan_distance"
PLAN_RACE_DATE_KEY = "plan_race_date"
PLAN_TARGET_KEY = "plan_target"
PLAN_MODEL_KEY = "plan_model"
PLAN_HISTORY_PICK_KEY = "plan_history_pick"


def question_key(question_id: str) -> str:
    return f"plan_q_{question_id}"


PERSISTENT_WIDGET_KEYS = (
    PLAN_DISTANCE_KEY,
    PLAN_RACE_DATE_KEY,
    PLAN_TARGET_KEY,
    PLAN_MODEL_KEY,
    PLAN_HISTORY_PICK_KEY,
    *(question_key(q.id) for q in HEALTH_QUESTIONS),
)


def keep_widget_state() -> None:
    """Streamlit usuwa stan widżetów, których nie narysowano w przebiegu (np. na innym ekranie). Ponowne
    przypisanie na początku każdego przebiegu zamienia go w zwykły stan sesji, który przetrwa nawigację."""
    for key in PERSISTENT_WIDGET_KEYS:
        if key in st.session_state:
            st.session_state[key] = st.session_state[key]
