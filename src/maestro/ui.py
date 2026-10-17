import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
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
    ErrorMessage,
    LogPreview,
    ShiftPreset,
    StepTracker,
    describe_error,
    downtime_by_machine,
    preset_label,
    preview_log,
    report_file_name,
    shift_times,
)

LOGO_PATH = PROJECT_DIR / "docs" / "logo.png"
SAMPLE_LOG = DATA_DIR / "fault_log.csv"
UPLOAD_FILE_NAME = "uploaded_fault_log.csv"
QUOTA_NOTE = "About 5 reports per day are possible on the free plan."
SOURCE_UPLOAD = "Upload CSV"
SOURCE_SAMPLE = "Use sample data"
LANGUAGES = {"English": ReportLanguage.ENGLISH, "German": ReportLanguage.GERMAN}
OUTCOME_KEY = "report_outcome"
CHART_COLOR = "#F59E0B"
TIME_STEP_SECONDS = 900
DATE_TIME_FORMAT = "%d.%m.%Y %H:%M"


@dataclass(frozen=True)
class Selection:
    log_bytes: bytes | None
    log_chosen: bool
    shift_start: time
    shift_end: time
    language: ReportLanguage
    preview: LogPreview | None
    preview_error: ErrorMessage | None
    clicked: bool


@dataclass(frozen=True)
class ReportOutcome:
    steps_markdown: str
    report: str | None = None
    downtime: dict[str, float] = field(default_factory=dict)
    file_name: str = ""
    error: ErrorMessage | None = None


@contextmanager
def fault_log_file(log_bytes: bytes | None) -> Iterator[Path]:
    if log_bytes is None:
        yield SAMPLE_LOG
        return
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / UPLOAD_FILE_NAME
        path.write_bytes(log_bytes)
        yield path


def load_preview(log_bytes: bytes | None, shift_start: time, shift_end: time) -> tuple[LogPreview | None, ErrorMessage | None]:
    with fault_log_file(log_bytes) as log_path:
        try:
            return preview_log(log_path, shift_start, shift_end), None
        # A broken upload is shown as a message, never a traceback.
        except Exception as error:  # noqa: BLE001
            return None, describe_error(error)


def render_sidebar() -> Selection:
    with st.sidebar:
        st.image(str(LOGO_PATH), width=120)
        source = st.radio("Fault log", [SOURCE_UPLOAD, SOURCE_SAMPLE])
        upload = st.file_uploader("Fault log CSV", type=["csv"]) if source == SOURCE_UPLOAD else None
        preset = st.segmented_control(
            "Shift", list(ShiftPreset), default=ShiftPreset.EARLY, required=True, format_func=preset_label, width="stretch"
        )
        custom_start, custom_end = time(6, 0), time(14, 0)
        if preset is ShiftPreset.CUSTOM:
            custom_start = st.time_input("Shift start", custom_start, step=TIME_STEP_SECONDS)
            custom_end = st.time_input("Shift end", custom_end, step=TIME_STEP_SECONDS)
        shift_start, shift_end = shift_times(preset, custom_start, custom_end)
        language_name = st.radio("Report language", list(LANGUAGES), horizontal=True)

        log_chosen = source == SOURCE_SAMPLE or upload is not None
        log_bytes = upload.getvalue() if upload is not None else None
        preview, preview_error = load_preview(log_bytes, shift_start, shift_end) if log_chosen else (None, None)
        clicked = st.button("Generate report", type="primary", disabled=preview is None)
        st.caption(QUOTA_NOTE)
    return Selection(log_bytes, log_chosen, shift_start, shift_end, LANGUAGES[language_name], preview, preview_error, clicked)


def render_error(message: ErrorMessage) -> None:
    st.error(message.summary)
    if message.details:
        with st.expander("Technical details"):
            st.code(message.details, language=None, wrap_lines=True)


def render_preview(preview: LogPreview) -> None:
    with st.container(border=True):
        st.markdown("**Fault log preview**")
        with st.container(horizontal=True):
            st.metric("Events", preview.event_count)
            st.metric("Machines", len(preview.machine_ids))
            st.metric("In this shift", preview.events_in_shift)
        st.caption(
            f"Machines: {', '.join(preview.machine_ids)} · "
            f"first event {preview.first_event:{DATE_TIME_FORMAT}}, last event {preview.last_event:{DATE_TIME_FORMAT}} · "
            f"shift {preview.shift.start:{DATE_TIME_FORMAT}} to {preview.shift.end:{DATE_TIME_FORMAT}}"
        )


def run_report(selection: Selection) -> ReportOutcome:
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

    def on_wait(seconds: float, reason: str) -> None:
        tracker.on_wait(seconds, reason)
        steps_box.markdown(tracker.to_markdown())

    def on_token(text: str) -> None:
        streamed.append(text)
        report_box.markdown("".join(streamed))

    with fault_log_file(selection.log_bytes) as log_path:
        try:
            shift = ShiftWindow.for_log(log_path, selection.shift_start, selection.shift_end)
            agent = build_agent(Settings.from_env(), log_path, shift, on_token=on_token, on_event=on_event, on_wait=on_wait)
            result = agent.run(report_task(selection.language, shift.start, shift.end))
            downtime = downtime_by_machine(log_path, shift)
        # The page shows every failure as a message, never a traceback.
        except Exception as error:  # noqa: BLE001
            live.empty()
            return ReportOutcome(tracker.to_markdown(), error=describe_error(error))
    live.empty()

    if result.stop_reason is not StopReason.FINAL_ANSWER:
        return ReportOutcome(tracker.to_markdown(), error=ErrorMessage(f"Run stopped without a report: {result.answer}"))
    return ReportOutcome(
        tracker.to_markdown(),
        report=result.answer,
        downtime=downtime,
        file_name=report_file_name(selection.language, datetime.now()),
    )


def render_outcome(outcome: ReportOutcome) -> None:
    if outcome.steps_markdown:
        with st.expander("Agent steps"):
            st.markdown(outcome.steps_markdown)
    if outcome.error is not None or outcome.report is None:
        render_error(outcome.error or ErrorMessage("No report was produced."))
        return
    st.markdown(outcome.report)
    st.subheader("Downtime per machine")
    chart_data = pd.DataFrame({"Downtime (min)": list(outcome.downtime.values())}, index=list(outcome.downtime))
    st.bar_chart(chart_data, color=CHART_COLOR)
    st.download_button("Download report", data=outcome.report, file_name=outcome.file_name, mime="text/markdown")


def main() -> None:
    st.set_page_config(page_title="Maestro Agent", page_icon=str(LOGO_PATH), layout="wide")
    st.title("Maestro shift report")
    selection = render_sidebar()
    if selection.preview_error is not None:
        render_error(selection.preview_error)
    elif selection.preview is not None:
        render_preview(selection.preview)
    if selection.clicked and selection.preview is not None:
        st.session_state[OUTCOME_KEY] = run_report(selection)
    outcome = st.session_state.get(OUTCOME_KEY)
    if outcome is not None:
        render_outcome(outcome)
    elif not selection.log_chosen:
        st.info("Choose a fault log in the sidebar and click Generate report.")


if __name__ == "__main__":
    main()
