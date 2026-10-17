import tempfile
from dataclasses import dataclass, field
from datetime import datetime, time
from pathlib import Path

import pandas as pd
import streamlit as st

from maestro.app import DATA_DIR, PROJECT_DIR, build_agent
from maestro.config import Settings
from maestro.core.agent import StopReason
from maestro.core.trace import TraceEvent
from maestro.prompts import ReportLanguage, report_task
from maestro.tools.factory_data import ShiftWindow
from maestro.ui_model import (
    StepTracker,
    describe_error,
    downtime_by_machine,
    report_file_name,
)

LOGO_PATH = PROJECT_DIR / "docs" / "logo.png"
SAMPLE_LOG = DATA_DIR / "fault_log.csv"
UPLOAD_FILE_NAME = "uploaded_fault_log.csv"
QUOTA_NOTE = "Each report uses about 35k tokens of the provider's daily quota."
SOURCE_UPLOAD = "Upload CSV"
SOURCE_SAMPLE = "Use sample data"
LANGUAGES = {"English": ReportLanguage.ENGLISH, "German": ReportLanguage.GERMAN}
OUTCOME_KEY = "report_outcome"
CHART_COLOR = "#F59E0B"
TIME_STEP_SECONDS = 900


@dataclass(frozen=True)
class ReportRequest:
    log_bytes: bytes | None
    shift_start: time
    shift_end: time
    language: ReportLanguage


@dataclass(frozen=True)
class ReportOutcome:
    steps_markdown: str
    report: str | None = None
    downtime: dict[str, float] = field(default_factory=dict)
    file_name: str = ""
    error: str | None = None


def render_sidebar() -> ReportRequest | None:
    with st.sidebar:
        st.image(str(LOGO_PATH), width=120)
        source = st.radio("Fault log", [SOURCE_UPLOAD, SOURCE_SAMPLE])
        upload = st.file_uploader("Fault log CSV", type=["csv"]) if source == SOURCE_UPLOAD else None
        shift_start = st.time_input("Shift start", time(6, 0), step=TIME_STEP_SECONDS)
        shift_end = st.time_input("Shift end", time(14, 0), step=TIME_STEP_SECONDS)
        language_name = st.radio("Report language", list(LANGUAGES), horizontal=True)
        ready = source == SOURCE_SAMPLE or upload is not None
        clicked = st.button("Generate report", type="primary", disabled=not ready)
        st.caption(QUOTA_NOTE)
    if not clicked:
        return None
    log_bytes = upload.getvalue() if upload is not None else None
    return ReportRequest(log_bytes, shift_start, shift_end, LANGUAGES[language_name])


def run_report(request: ReportRequest) -> ReportOutcome:
    tracker = StepTracker()
    streamed: list[str] = []
    live = st.empty()
    with live.container():
        st.subheader("Steps")
        steps_box = st.empty()
        st.subheader("Report")
        report_box = st.empty()

    def on_event(event: TraceEvent) -> None:
        tracker.on_event(event)
        steps_box.markdown(tracker.to_markdown())

    def on_token(text: str) -> None:
        streamed.append(text)
        report_box.markdown("".join(streamed))

    with tempfile.TemporaryDirectory() as directory:
        log_path = SAMPLE_LOG
        if request.log_bytes is not None:
            log_path = Path(directory) / UPLOAD_FILE_NAME
            log_path.write_bytes(request.log_bytes)
        try:
            shift = ShiftWindow.for_log(log_path, request.shift_start, request.shift_end)
            agent = build_agent(Settings.from_env(), log_path, shift, on_token=on_token, on_event=on_event)
            result = agent.run(report_task(request.language, shift.start, shift.end))
            downtime = downtime_by_machine(log_path, shift)
        # The page shows every failure as a message, never a traceback.
        except Exception as error:  # noqa: BLE001
            live.empty()
            return ReportOutcome(tracker.to_markdown(), error=describe_error(error))
    live.empty()

    if result.stop_reason is not StopReason.FINAL_ANSWER:
        return ReportOutcome(tracker.to_markdown(), error=f"Run stopped without a report: {result.answer}")
    return ReportOutcome(
        tracker.to_markdown(),
        report=result.answer,
        downtime=downtime,
        file_name=report_file_name(request.language, datetime.now()),
    )


def render_outcome(outcome: ReportOutcome) -> None:
    if outcome.steps_markdown:
        with st.expander("Agent steps"):
            st.markdown(outcome.steps_markdown)
    if outcome.error is not None or outcome.report is None:
        st.error(outcome.error or "No report was produced.")
        return
    st.markdown(outcome.report)
    st.subheader("Downtime per machine")
    chart_data = pd.DataFrame({"Downtime (min)": list(outcome.downtime.values())}, index=list(outcome.downtime))
    st.bar_chart(chart_data, color=CHART_COLOR)
    st.download_button("Download report", data=outcome.report, file_name=outcome.file_name, mime="text/markdown")


def main() -> None:
    st.set_page_config(page_title="Maestro Agent", page_icon=str(LOGO_PATH), layout="wide")
    st.title("Maestro shift report")
    request = render_sidebar()
    if request is not None:
        st.session_state[OUTCOME_KEY] = run_report(request)
    outcome = st.session_state.get(OUTCOME_KEY)
    if outcome is None:
        st.info("Choose a fault log in the sidebar and click Generate report.")
        return
    render_outcome(outcome)


if __name__ == "__main__":
    main()
