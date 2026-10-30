"""Ekran „Biegacz”: profile, edycja, synchronizacja z Garmin Connect."""

import contextlib
from uuid import uuid4

import pandas as pd
import streamlit as st
from pydantic import ValidationError

from llmrunplanner.config import load_settings
from llmrunplanner.domain import ActivitySource, Athlete, Sex
from llmrunplanner.ingest.garmin_sync import GarminAuthError, GarminSyncError, SyncReport, sync_garmin
from llmrunplanner.storage import connect, save_athlete
from llmrunplanner.ui import data, state
from llmrunplanner.ui.components import table
from llmrunplanner.ui.format import date_pl, datetime_pl

_SOURCE_LABELS = {
    ActivitySource.GARMIN: "Garmin Connect",
    ActivitySource.IMPORT: "Import plików FIT",
    ActivitySource.PUBLIC: "Zbiór publiczny",
}
_NEW_SOURCES = [ActivitySource.GARMIN, ActivitySource.IMPORT]
_SEX_LABELS = {Sex.M: "M", Sex.F: "K"}
_HR_SOURCE = {"override": "wartość ręczna", "data": "z danych Aktywności", "garmin": "mediana z Garmin Connect", "default": "wartość domyślna"}
_MODE_KEY, _NEXT_MODE_KEY, _REPORT_KEY = "athlete_mode", "_athlete_mode_next", "sync_result"
_EDIT, _NEW = "Edytuj profil", "Nowy Biegacz"


def _overview_table() -> None:
    rows = data.overview()
    if not rows:
        st.info("Brak profili. Utwórz pierwszego Biegacza poniżej.")
        return
    overview = pd.DataFrame(
        {
            "Pseudonim": o.athlete.label,
            "Źródło": _SOURCE_LABELS.get(o.athlete.source, o.athlete.source.value),
            "Płeć": _SEX_LABELS[o.athlete.sex],
            "Rok urodzenia": o.athlete.birth_year,
            "HRmax (ręczne)": o.athlete.hr_max_override,
            "HRspocz (ręczne)": o.athlete.hr_rest_override,
            "Aktywności": o.activity_count,
            "Historia": f"{date_pl(o.first_date)} – {date_pl(o.last_date)}" if o.first_date else "–",
            "Ostatnia synchronizacja": (
                f"{datetime_pl(o.synced_at)} ({'pełna' if o.sync_complete else 'niepełna'})" if o.synced_at else "–"
            ),
        }
        for o in rows
    ).astype({"HRmax (ręczne)": "Int64", "HRspocz (ręczne)": "Int64"})
    table(overview)


def _defaults(athlete_id: str) -> None:
    cutoff = state.cutoff()
    if cutoff is None:
        return
    try:
        _, activities, metrics, _ = data.athlete_metrics(athlete_id, cutoff)
    except ValueError as exc:
        st.warning(f"Nie udało się policzyć wartości domyślnych: {exc}")
        return
    if metrics is None:
        st.caption(f"Brak Aktywności przed Datą odcięcia {date_pl(cutoff)}, więc nie ma wartości domyślnych.")
        return
    p = metrics.hr_profile
    st.caption(
        f"Dla Daty odcięcia {date_pl(cutoff)} będą użyte: HRmax {p.hr_max} ({_HR_SOURCE[p.hr_max_source]}), "
        f"HRspocz {p.hr_rest} ({_HR_SOURCE[p.hr_rest_source]})."
    )


def _form(current: Athlete | None) -> None:
    key = current.id if current else "new"
    with st.form(f"athlete_form_{key}"):
        label = st.text_input("Pseudonim (bez imienia i nazwiska)", value=current.label if current else "", max_chars=40)
        c1, c2 = st.columns(2)
        sex = c1.radio("Płeć", list(_SEX_LABELS), format_func=_SEX_LABELS.get, horizontal=True, index=list(_SEX_LABELS).index(current.sex) if current else 0)
        birth_year = c2.number_input("Rok urodzenia", min_value=1920, max_value=2015, value=current.birth_year if current else 1990, step=1)
        c3, c4 = st.columns(2)
        hr_max = c3.number_input("HRmax (opcjonalnie, nadpisuje wartość z danych)", min_value=120, max_value=230, value=current.hr_max_override if current else None, step=1)
        hr_rest = c4.number_input("HRspocz (opcjonalnie, nadpisuje wartość domyślną)", min_value=25, max_value=120, value=current.hr_rest_override if current else None, step=1)
        sources = list(_SOURCE_LABELS) if current else _NEW_SOURCES
        source = st.selectbox("Źródło danych", sources, format_func=_SOURCE_LABELS.get, index=sources.index(current.source) if current else 0)
        submitted = st.form_submit_button("Zapisz profil")
    if not submitted:
        return
    if not label.strip():
        st.error("Podaj pseudonim.")
        return
    taken = {a.label.strip().casefold() for a in data.athletes() if current is None or a.id != current.id}
    if label.strip().casefold() in taken:
        st.error(f"Pseudonim „{label.strip()}” jest już zajęty. Wybierz inny.")
        return
    if hr_max and hr_rest and hr_max <= hr_rest:
        st.error("HRmax musi być większe od HRspocz.")
        return
    try:
        athlete = Athlete(
            id=current.id if current else uuid4().hex,
            label=label.strip(),
            source=source,
            sex=sex,
            birth_year=int(birth_year),
            hr_rest_override=int(hr_rest) if hr_rest else None,
            hr_max_override=int(hr_max) if hr_max else None,
        )
    except ValidationError as exc:
        st.error("Nieprawidłowe dane profilu: " + "; ".join(e["msg"] for e in exc.errors()))
        return
    with contextlib.closing(connect(load_settings().db_path)) as conn:
        save_athlete(conn, athlete)
    data.invalidate()
    state.request_athlete(athlete.id)
    st.session_state[_NEXT_MODE_KEY] = _EDIT
    st.session_state["flash"] = f"Zapisano profil „{athlete.label}”."
    st.rerun()


def _report_view(report: SyncReport) -> None:
    if report.complete:
        st.success("Synchronizacja pełna.")
    else:
        st.warning("Synchronizacja niepełna: uruchom ją ponownie, aby dokończyć.")
    fields = [
        ("Nowe Aktywności", report.new),
        ("Duplikaty", report.duplicates),
        ("Pominięte – inne sporty w historii", report.skipped_not_running),
        ("Pominięte – za krótkie", report.skipped_too_short),
        ("Uszkodzone", report.broken),
        ("Bez tętna", report.without_hr),
        ("Zaktualizowane wartości Garmina", report.garmin_metrics),
    ]
    cols = st.columns(len(fields))
    for col, (name, value) in zip(cols, fields):
        col.metric(name, value)
    st.caption(f"Błędy: {len(report.errors)}")
    if report.errors:
        with st.expander("Komunikaty o błędach"):
            for e in report.errors:
                st.write(f"- {e}")


def _sync_section(athlete: Athlete) -> None:
    st.subheader("Synchronizacja z Garmin Connect")
    st.caption("Pobiera nowe biegi i wartości wyliczone przez Garmina. Wymaga wcześniejszego jednorazowego zalogowania w terminalu.")
    if st.button("Synchronizuj z Garmin Connect", type="primary"):
        bar = st.progress(0.0, text="Łączenie z Garmin Connect…")

        def on_progress(done: int, total: int) -> None:
            bar.progress(done / total if total else 1.0, text=f"Pobrano {done} z {total}")

        result: dict
        try:
            with contextlib.closing(connect(load_settings().db_path)) as conn:
                result = {"athlete": athlete.id, "report": sync_garmin(conn, athlete.id, load_settings().fit_dir, progress=on_progress)}
        except GarminAuthError as exc:
            result = {"athlete": athlete.id, "auth_error": str(exc)}
        except GarminSyncError as exc:
            result = {"athlete": athlete.id, "error": str(exc)}
        bar.empty()
        data.invalidate()
        st.session_state[_REPORT_KEY] = result
        st.rerun()

    result = st.session_state.get(_REPORT_KEY)
    if not result or result["athlete"] != athlete.id:
        return
    if "auth_error" in result:
        st.error("Logowanie do Garmin Connect nie powiodło się. Zaloguj się w terminalu (jednorazowo, z MFA):")
        st.code("poetry run python -m llmrunplanner.ingest.garmin_login", language="bash")
    elif "error" in result:
        st.error(result["error"])
    else:
        _report_view(result["report"])


st.title("Biegacz")
if flash := st.session_state.pop("flash", None):
    st.success(flash)
if (nxt := st.session_state.pop(_NEXT_MODE_KEY, None)) is not None:
    st.session_state[_MODE_KEY] = nxt

_overview_table()

selected = next((a for a in data.athletes() if a.id == state.athlete_id()), None)
modes = [_EDIT, _NEW] if selected else [_NEW]
if st.session_state.get(_MODE_KEY) not in modes:
    st.session_state[_MODE_KEY] = modes[0]
mode = st.radio("Profil", modes, key=_MODE_KEY, horizontal=True, label_visibility="collapsed")

edited = selected if mode == _EDIT else None
st.subheader(f"{_EDIT}: {edited.label}" if edited else _NEW)
_form(edited)
if edited:
    _defaults(edited.id)
    if edited.source == ActivitySource.GARMIN:
        _sync_section(edited)
