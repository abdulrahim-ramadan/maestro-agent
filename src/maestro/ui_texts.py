from enum import Enum, auto
from typing import Any

from maestro.prompts import ReportLanguage

LANGUAGE_TOGGLE_LABEL = "Sprache / Language"
LANGUAGE_CHOICES = {"Deutsch": ReportLanguage.GERMAN, "English": ReportLanguage.ENGLISH}
DEFAULT_LANGUAGE_CHOICE = "Deutsch"


class Text(Enum):
    PAGE_TAB_TITLE = auto()
    PAGE_TITLE = auto()
    FAULT_LOG = auto()
    SOURCE_UPLOAD = auto()
    SOURCE_SAMPLE = auto()
    UPLOAD_LABEL = auto()
    SHIFT = auto()
    SHIFT_START = auto()
    SHIFT_END = auto()
    SHIFT_EARLY = auto()
    SHIFT_LATE = auto()
    SHIFT_NIGHT = auto()
    SHIFT_CUSTOM = auto()
    GENERATE_REPORT = auto()
    QUOTA_NOTE = auto()
    CONFIRM_EMPTY_REPORT = auto()
    NO_EVENTS_IN_SHIFT = auto()
    PREVIEW_HEADING = auto()
    METRIC_EVENTS = auto()
    METRIC_MACHINES = auto()
    METRIC_IN_SHIFT = auto()
    PREVIEW_DETAILS = auto()
    DATE_TIME_FORMAT = auto()
    INFO_CHOOSE_LOG = auto()
    AGENT_STEPS = auto()
    SHIFT_REPORT = auto()
    STEP_LINE = auto()
    WAIT_LINE = auto()
    WAIT_REASON_PACING = auto()
    WAIT_REASON_RETRY_HINT = auto()
    TECHNICAL_DETAILS = auto()
    RATE_LIMIT_SUMMARY = auto()
    QUOTA_SUMMARY = auto()
    CONFIG_ERROR = auto()
    FAULT_LOG_ERROR = auto()
    API_ERROR = auto()
    INVALID_INPUT = auto()
    UNEXPECTED_ERROR = auto()
    RUN_STOPPED = auto()
    NO_REPORT = auto()
    DOWNTIME_PER_MACHINE = auto()
    DOWNTIME_MINUTES = auto()
    MACHINE = auto()
    DOWNLOAD_REPORT = auto()
    REPORT_FILE_NAME = auto()


GERMAN_TEXTS: dict[Text, str] = {
    Text.PAGE_TAB_TITLE: "Maestro – Schichtbericht",
    Text.PAGE_TITLE: "Maestro Schichtbericht",
    Text.FAULT_LOG: "Störungsprotokoll",
    Text.SOURCE_UPLOAD: "CSV hochladen",
    Text.SOURCE_SAMPLE: "Beispieldaten verwenden",
    Text.UPLOAD_LABEL: "Störungsprotokoll (CSV)",
    Text.SHIFT: "Schicht",
    Text.SHIFT_START: "Schichtbeginn",
    Text.SHIFT_END: "Schichtende",
    Text.SHIFT_EARLY: "Frühschicht {start}–{end}",
    Text.SHIFT_LATE: "Spätschicht {start}–{end}",
    Text.SHIFT_NIGHT: "Nachtschicht {start}–{end}",
    Text.SHIFT_CUSTOM: "Benutzerdefiniert",
    Text.GENERATE_REPORT: "Bericht erstellen",
    Text.QUOTA_NOTE: "Im kostenlosen Tarif sind etwa 5 Berichte pro Tag möglich.",
    Text.CONFIRM_EMPTY_REPORT: "Ich möchte trotzdem einen Bericht ohne Ereignisse erstellen",
    Text.NO_EVENTS_IN_SHIFT: (
        "Keine Ereignisse in dieser Schicht. Bitte prüfen Sie Schichtbeginn und Schichtende "
        "oder bestätigen Sie in der Seitenleiste, dass Sie einen leeren Bericht erstellen möchten."
    ),
    Text.PREVIEW_HEADING: "Vorschau des Störungsprotokolls",
    Text.METRIC_EVENTS: "Ereignisse",
    Text.METRIC_MACHINES: "Maschinen",
    Text.METRIC_IN_SHIFT: "In dieser Schicht",
    Text.PREVIEW_DETAILS: "Maschinen: {machines} · erstes Ereignis {first}, letztes Ereignis {last} · Schicht {start} bis {end}",
    Text.DATE_TIME_FORMAT: "%d.%m.%Y %H:%M",
    Text.INFO_CHOOSE_LOG: "Bitte wählen Sie in der Seitenleiste ein Störungsprotokoll und klicken Sie auf „Bericht erstellen“.",
    Text.AGENT_STEPS: "Arbeitsschritte des Agenten",
    Text.SHIFT_REPORT: "Schichtbericht",
    Text.STEP_LINE: "{icon} Schritt {step} **{tool}** `{arguments}`",
    Text.WAIT_LINE: "🕒 Warte {seconds} s wegen des Ratenlimits ({reason})",
    Text.WAIT_REASON_PACING: "Token-Limit pro Minute",
    Text.WAIT_REASON_RETRY_HINT: "Wartezeit laut KI-Dienst",
    Text.TECHNICAL_DETAILS: "Technische Details",
    Text.RATE_LIMIT_SUMMARY: "Das Limit des KI-Dienstes ist erreicht. Bitte eine Minute warten und erneut versuchen.",
    Text.QUOTA_SUMMARY: "Das Tageskontingent ist aufgebraucht. Bitte morgen erneut versuchen.",
    Text.CONFIG_ERROR: "Konfigurationsfehler: {message}",
    Text.FAULT_LOG_ERROR: "Fehler im Störungsprotokoll: {message}",
    Text.API_ERROR: "Fehler des KI-Dienstes ({error_type}): {message}",
    Text.INVALID_INPUT: "Ungültige Eingabe: {message}",
    Text.UNEXPECTED_ERROR: "Unerwarteter Fehler ({error_type}): {message}",
    Text.RUN_STOPPED: "Die Berichterstellung wurde ohne Ergebnis beendet: {answer}",
    Text.NO_REPORT: "Es wurde kein Bericht erstellt.",
    Text.DOWNTIME_PER_MACHINE: "Stillstand pro Maschine",
    Text.DOWNTIME_MINUTES: "Stillstand (min)",
    Text.MACHINE: "Maschine",
    Text.DOWNLOAD_REPORT: "Bericht herunterladen",
    Text.REPORT_FILE_NAME: "schichtbericht_{timestamp}.md",
}

ENGLISH_TEXTS: dict[Text, str] = {
    Text.PAGE_TAB_TITLE: "Maestro – Shift report",
    Text.PAGE_TITLE: "Maestro shift report",
    Text.FAULT_LOG: "Fault log",
    Text.SOURCE_UPLOAD: "Upload CSV",
    Text.SOURCE_SAMPLE: "Use sample data",
    Text.UPLOAD_LABEL: "Fault log (CSV)",
    Text.SHIFT: "Shift",
    Text.SHIFT_START: "Shift start",
    Text.SHIFT_END: "Shift end",
    Text.SHIFT_EARLY: "Early shift (Frühschicht) {start}–{end}",
    Text.SHIFT_LATE: "Late shift (Spätschicht) {start}–{end}",
    Text.SHIFT_NIGHT: "Night shift (Nachtschicht) {start}–{end}",
    Text.SHIFT_CUSTOM: "Custom",
    Text.GENERATE_REPORT: "Generate report",
    Text.QUOTA_NOTE: "About 5 reports per day are possible on the free plan.",
    Text.CONFIRM_EMPTY_REPORT: "I want to create a report without events anyway",
    Text.NO_EVENTS_IN_SHIFT: (
        "No events in this shift. Please check the shift start and end "
        "or confirm in the sidebar that you want to create an empty report."
    ),
    Text.PREVIEW_HEADING: "Fault log preview",
    Text.METRIC_EVENTS: "Events",
    Text.METRIC_MACHINES: "Machines",
    Text.METRIC_IN_SHIFT: "In this shift",
    Text.PREVIEW_DETAILS: "Machines: {machines} · first event {first}, last event {last} · shift {start} to {end}",
    Text.DATE_TIME_FORMAT: "%Y-%m-%d %H:%M",
    Text.INFO_CHOOSE_LOG: "Choose a fault log in the sidebar and click Generate report.",
    Text.AGENT_STEPS: "Agent steps",
    Text.SHIFT_REPORT: "Shift report",
    Text.STEP_LINE: "{icon} step {step} **{tool}** `{arguments}`",
    Text.WAIT_LINE: "🕒 waiting {seconds} s for the rate limit ({reason})",
    Text.WAIT_REASON_PACING: "token pacing",
    Text.WAIT_REASON_RETRY_HINT: "provider retry hint",
    Text.TECHNICAL_DETAILS: "Technical details",
    Text.RATE_LIMIT_SUMMARY: "The AI service limit was reached. Wait one minute and try again.",
    Text.QUOTA_SUMMARY: "Today's quota is used up. Try again tomorrow.",
    Text.CONFIG_ERROR: "Configuration error: {message}",
    Text.FAULT_LOG_ERROR: "Fault log error: {message}",
    Text.API_ERROR: "API error ({error_type}): {message}",
    Text.INVALID_INPUT: "Invalid input: {message}",
    Text.UNEXPECTED_ERROR: "Unexpected error ({error_type}): {message}",
    Text.RUN_STOPPED: "Run stopped without a report: {answer}",
    Text.NO_REPORT: "No report was produced.",
    Text.DOWNTIME_PER_MACHINE: "Downtime per machine",
    Text.DOWNTIME_MINUTES: "Downtime (min)",
    Text.MACHINE: "Machine",
    Text.DOWNLOAD_REPORT: "Download report",
    Text.REPORT_FILE_NAME: "shift_report_{timestamp}.md",
}

TEXTS: dict[ReportLanguage, dict[Text, str]] = {
    ReportLanguage.GERMAN: GERMAN_TEXTS,
    ReportLanguage.ENGLISH: ENGLISH_TEXTS,
}


def t(key: Text, lang: ReportLanguage, **kwargs: Any) -> str:
    return TEXTS[lang][key].format(**kwargs)


def report_language_for(choice: str | None) -> ReportLanguage:
    return LANGUAGE_CHOICES.get(choice or DEFAULT_LANGUAGE_CHOICE, ReportLanguage.GERMAN)
