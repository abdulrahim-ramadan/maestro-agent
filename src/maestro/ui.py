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
    LogSource,
    ShiftPreset,
    StepTracker,
    can_generate,
    describe_error,
    downtime_by_machine,
    log_source_label,
    preset_label,
    preview_log,
    report_file_name,
    shift_times,
)
from maestro.ui_texts import (
    DEFAULT_LANGUAGE_CHOICE,
    LANGUAGE_CHOICES,
    LANGUAGE_TOGGLE_LABEL,
    Text,
    report_language_for,
    t,
)

LOGO_PATH = PROJECT_DIR / "docs" / "logo.png"
SAMPLE_LOG = DATA_DIR / "fault_log.csv"
UPLOAD_FILE_NAME = "uploaded_fault_log.csv"
CHART_COLOR = "#F59E0B"
TIME_STEP_SECONDS = 900
LANGUAGE_KEY = "ui_language"
SOURCE_KEY = "log_source"
UPLOAD_KEY = "fault_log_upload"
SHIFT_KEY = "shift_preset"
SHIFT_START_KEY = "shift_start"
SHIFT_END_KEY = "shift_end"
CONFIRM_EMPTY_KEY = "confirm_empty_report"
GENERATE_KEY = "generate_report"
DOWNLOAD_KEY = "download_report"
OUTCOME_KEY = "report_outcome"


@dataclass(frozen=True)
class Selection:
    language: ReportLanguage
    log_bytes: bytes | None
    log_chosen: bool
    shift_start: time
    shift_end: time
    preview: LogPreview | None
    preview_error: Exception | None
    empty_report_confirmed: bool
    clicked: bool


@dataclass(frozen=True)
class ReportOutcome:
    tracker: StepTracker
    report_language: ReportLanguage
    created_at: datetime
    report: str | None = None
    downtime: dict[str, float] = field(default_factory=dict)
    error: Exception | None = None
    stopped_answer: str | None = None


@contextmanager
def fault_log_file(log_bytes: bytes | None) -> Iterator[Path]:
    if log_bytes is None:
        yield SAMPLE_LOG
        return
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / UPLOAD_FILE_NAME
        path.write_bytes(log_bytes)
        yield path


def load_preview(log_bytes: bytes | None, shift_start: time, shift_end: time) -> tuple[LogPreview | None, Exception | None]:
    with fault_log_file(log_bytes) as log_path:
        try:
            return preview_log(log_path, shift_start, shift_end), None
        # A broken upload is shown as a message, never a traceback.
        except Exception as error:  # noqa: BLE001
            return None, error


def render_sidebar() -> Selection:
    with st.sidebar:
        choice = st.segmented_control(
            LANGUAGE_TOGGLE_LABEL,
            list(LANGUAGE_CHOICES),
            default=DEFAULT_LANGUAGE_CHOICE,
            required=True,
            key=LANGUAGE_KEY,
            width="stretch",
        )
        lang = report_language_for(choice)
        st.image(str(LOGO_PATH), width=120)
        source = st.radio(
            t(Text.FAULT_LOG, lang), list(LogSource), format_func=lambda option: log_source_label(option, lang), key=SOURCE_KEY
        )
        upload = st.file_uploader(t(Text.UPLOAD_LABEL, lang), type=["csv"], key=UPLOAD_KEY) if source is LogSource.UPLOAD else None
        preset = st.segmented_control(
            t(Text.SHIFT, lang),
            list(ShiftPreset),
            default=ShiftPreset.EARLY,
            required=True,
            format_func=lambda option: preset_label(option, lang),
            key=SHIFT_KEY,
            width="stretch",
        )
        custom_start, custom_end = time(6, 0), time(14, 0)
        if preset is ShiftPreset.CUSTOM:
            custom_start = st.time_input(t(Text.SHIFT_START, lang), custom_start, step=TIME_STEP_SECONDS, key=SHIFT_START_KEY)
            custom_end = st.time_input(t(Text.SHIFT_END, lang), custom_end, step=TIME_STEP_SECONDS, key=SHIFT_END_KEY)
        shift_start, shift_end = shift_times(preset, custom_start, custom_end)

        log_chosen = source is LogSource.SAMPLE or upload is not None
        log_bytes = upload.getvalue() if upload is not None else None
        preview, preview_error = load_preview(log_bytes, shift_start, shift_end) if log_chosen else (None, None)
        confirmed = False
        if preview is not None and preview.shift_is_empty:
            confirmed = st.checkbox(t(Text.CONFIRM_EMPTY_REPORT, lang), key=CONFIRM_EMPTY_KEY)
        clicked = st.button(
            t(Text.GENERATE_REPORT, lang), type="primary", disabled=not can_generate(preview, confirmed), key=GENERATE_KEY
        )
        st.caption(t(Text.QUOTA_NOTE, lang))
    return Selection(lang, log_bytes, log_chosen, shift_start, shift_end, preview, preview_error, confirmed, clicked)


def render_error(message: ErrorMessage, lang: ReportLanguage) -> None:
    st.error(message.summary)
    if message.details:
        with st.expander(t(Text.TECHNICAL_DETAILS, lang)):
            st.code(message.details, language=None, wrap_lines=True)


def render_preview(preview: LogPreview, lang: ReportLanguage) -> None:
    with st.container(border=True):
        st.markdown(f"**{t(Text.PREVIEW_HEADING, lang)}**")
        with st.container(horizontal=True):
            st.metric(t(Text.METRIC_EVENTS, lang), preview.event_count)
            st.metric(t(Text.METRIC_MACHINES, lang), len(preview.machine_ids))
            st.metric(t(Text.METRIC_IN_SHIFT, lang), preview.events_in_shift)
        st.caption(preview.details(lang))
    if preview.shift_is_empty:
        st.warning(t(Text.NO_EVENTS_IN_SHIFT, lang))


def run_report(selection: Selection) -> ReportOutcome:
    lang = selection.language
    tracker = StepTracker()
    streamed: list[str] = []
    live = st.empty()
    with live.container():
        st.subheader(t(Text.AGENT_STEPS, lang))
        steps_box = st.empty()
        st.subheader(t(Text.SHIFT_REPORT, lang))
        report_box = st.empty()

    def on_event(event: TraceEvent) -> None:
        tracker.on_event(event)
        steps_box.markdown(tracker.to_markdown(lang))

    def on_wait(seconds: float, reason: str) -> None:
        tracker.on_wait(seconds, reason)
        steps_box.markdown(tracker.to_markdown(lang))

    def on_token(text: str) -> None:
        streamed.append(text)
        report_box.markdown("".join(streamed))

    created_at = datetime.now()
    with fault_log_file(selection.log_bytes) as log_path:
        try:
            shift = ShiftWindow.for_log(log_path, selection.shift_start, selection.shift_end)
            agent = build_agent(Settings.from_env(), log_path, shift, on_token=on_token, on_event=on_event, on_wait=on_wait)
            result = agent.run(report_task(lang, shift.start, shift.end))
            downtime = downtime_by_machine(log_path, shift)
        # The page shows every failure as a message, never a traceback.
        except Exception as error:  # noqa: BLE001
            live.empty()
            return ReportOutcome(tracker, lang, created_at, error=error)
    live.empty()

    if result.stop_reason is not StopReason.FINAL_ANSWER:
        return ReportOutcome(tracker, lang, created_at, stopped_answer=result.answer)
    return ReportOutcome(tracker, lang, created_at, report=result.answer, downtime=downtime)


def render_outcome(outcome: ReportOutcome, lang: ReportLanguage) -> None:
    steps_markdown = outcome.tracker.to_markdown(lang)
    if steps_markdown:
        with st.expander(t(Text.AGENT_STEPS, lang)):
            st.markdown(steps_markdown)
    if outcome.error is not None:
        render_error(describe_error(outcome.error, lang), lang)
        return
    if outcome.stopped_answer is not None:
        render_error(ErrorMessage(t(Text.RUN_STOPPED, lang, answer=outcome.stopped_answer)), lang)
        return
    if outcome.report is None:
        render_error(ErrorMessage(t(Text.NO_REPORT, lang)), lang)
        return
    st.markdown(outcome.report)
    st.subheader(t(Text.DOWNTIME_PER_MACHINE, lang))
    machine_label, minutes_label = t(Text.MACHINE, lang), t(Text.DOWNTIME_MINUTES, lang)
    chart_data = pd.DataFrame(
        {minutes_label: list(outcome.downtime.values())}, index=pd.Index(list(outcome.downtime), name=machine_label)
    )
    st.bar_chart(chart_data, x_label=machine_label, y_label=minutes_label, color=CHART_COLOR)
    st.download_button(
        t(Text.DOWNLOAD_REPORT, lang),
        data=outcome.report,
        file_name=report_file_name(outcome.report_language, outcome.created_at),
        mime="text/markdown",
        key=DOWNLOAD_KEY,
    )


def main() -> None:
    lang = report_language_for(st.session_state.get(LANGUAGE_KEY))
    st.set_page_config(page_title=t(Text.PAGE_TAB_TITLE, lang), page_icon=str(LOGO_PATH), layout="wide")
    selection = render_sidebar()
    lang = selection.language
    st.title(t(Text.PAGE_TITLE, lang))
    if selection.preview_error is not None:
        render_error(describe_error(selection.preview_error, lang), lang)
    elif selection.preview is not None:
        render_preview(selection.preview, lang)
    if selection.clicked and can_generate(selection.preview, selection.empty_report_confirmed):
        st.session_state[OUTCOME_KEY] = run_report(selection)
    outcome = st.session_state.get(OUTCOME_KEY)
    if outcome is not None:
        render_outcome(outcome, lang)
    elif not selection.log_chosen:
        st.info(t(Text.INFO_CHOOSE_LOG, lang))


if __name__ == "__main__":
    main()
