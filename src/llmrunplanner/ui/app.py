"""Wejście aplikacji: poprawne uruchomienie to `streamlit run src/llmrunplanner/ui/app.py`."""

from datetime import date

import streamlit as st

from llmrunplanner.safety import MEDICAL_DISCLAIMER
from llmrunplanner.ui import data, state
from llmrunplanner.ui.format import date_pl

DEMO_CUTOFF = date(2024, 9, 1)


def _sidebar() -> None:
    state.apply_pending()
    with st.sidebar:
        athletes = data.athletes()
        if not athletes:
            st.info("Brak profili. Dodaj Biegacza na ekranie „Biegacz”.")
            st.session_state.pop(state.ATHLETE_KEY, None)
        else:
            labels = {a.id: a.label for a in athletes}
            if state.athlete_id() not in labels:
                st.session_state[state.ATHLETE_KEY] = athletes[0].id
            st.selectbox("Biegacz", list(labels), format_func=labels.get, key=state.ATHLETE_KEY)

            current = state.athlete_id()
            if state.cutoff_belongs_to() != current or state.cutoff() is None:
                st.session_state[state.CUTOFF_KEY] = data.default_cutoff(current)
                state.mark_cutoff_for(current)
            st.date_input("Data odcięcia", key=state.CUTOFF_KEY, format="DD.MM.YYYY")
            st.caption(
                "Domyślnie dzień ostatniej pełnej synchronizacji. Do demonstracji używa się Daty odcięcia "
                f"{date_pl(DEMO_CUTOFF)}."
            )
            st.button(f"Ustaw {date_pl(DEMO_CUTOFF)}", width="stretch", on_click=state.set_cutoff, args=(DEMO_CUTOFF,))
        st.divider()
        st.caption(MEDICAL_DISCLAIMER)


st.set_page_config(page_title="Planowanie treningu biegowego", layout="wide")
state.keep_widget_state()
_sidebar()
navigation = st.navigation(
    [
        st.Page("pages/athlete.py", title="Biegacz", icon=":material/person:", default=True),
        st.Page("pages/analysis.py", title="Analiza", icon=":material/monitoring:"),
        st.Page("pages/plan.py", title="Cel i Plan", icon=":material/flag:"),
    ]
)
navigation.run()
