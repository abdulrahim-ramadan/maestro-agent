import ast
import re
import string
from pathlib import Path

import pytest

from maestro.prompts import ReportLanguage
from maestro.ui_texts import (
    DEFAULT_LANGUAGE_CHOICE,
    ENGLISH_TEXTS,
    GERMAN_TEXTS,
    LANGUAGE_CHOICES,
    LANGUAGE_TOGGLE_LABEL,
    Text,
    report_language_for,
    t,
)

SOURCE_DIR = Path(__file__).resolve().parent.parent / "src" / "maestro"
SCANNED_FILES = ["ui.py", "ui_model.py"]
LETTER = re.compile(r"[A-Za-zÄÖÜäöüß]")
ALLOWED_KEYWORDS = {"key", "type", "mime", "width", "language", "layout"}
ALLOWED_CONSTANT_SUFFIXES = ("_KEY", "_FORMAT")
ALLOWED_LITERALS = {
    "__main__",
    "Sprache / Language",
    "docs",
    "logo.png",
    "fault_log.csv",
    "uploaded_fault_log.csv",
    "#F59E0B",
    "csv",
    "primary",
    "stretch",
    "text/markdown",
}


def placeholders(template: str) -> set[str]:
    return {field for _, field, _, _ in string.Formatter().parse(template) if field}


def test_both_languages_have_every_key() -> None:
    assert set(GERMAN_TEXTS) == set(Text)
    assert set(ENGLISH_TEXTS) == set(Text)


@pytest.mark.parametrize("texts", [GERMAN_TEXTS, ENGLISH_TEXTS], ids=["de", "en"])
def test_no_text_is_empty(texts: dict[Text, str]) -> None:
    assert [key for key, value in texts.items() if not value.strip()] == []


@pytest.mark.parametrize("key", list(Text), ids=lambda key: key.name)
def test_placeholders_match_in_both_languages(key: Text) -> None:
    assert placeholders(GERMAN_TEXTS[key]) == placeholders(ENGLISH_TEXTS[key])


@pytest.mark.parametrize(
    "lang, expected",
    [
        (ReportLanguage.GERMAN, "🕒 Warte 12 s wegen des Ratenlimits (Token-Limit pro Minute)"),
        (ReportLanguage.ENGLISH, "🕒 waiting 12 s for the rate limit (token pacing)"),
    ],
)
def test_t_formats_placeholders(lang: ReportLanguage, expected: str) -> None:
    reason = t(Text.WAIT_REASON_PACING, lang)

    assert t(Text.WAIT_LINE, lang, seconds=12, reason=reason) == expected


def test_t_raises_for_a_missing_placeholder() -> None:
    with pytest.raises(KeyError, match="seconds"):
        t(Text.WAIT_LINE, ReportLanguage.GERMAN, reason="x")


@pytest.mark.parametrize(
    "choice, expected",
    [("Deutsch", ReportLanguage.GERMAN), ("English", ReportLanguage.ENGLISH), (None, ReportLanguage.GERMAN)],
)
def test_toggle_maps_to_report_language(choice: str | None, expected: ReportLanguage) -> None:
    assert report_language_for(choice) == expected


def test_toggle_label_options_and_default() -> None:
    assert LANGUAGE_TOGGLE_LABEL == "Sprache / Language"
    assert list(LANGUAGE_CHOICES) == ["Deutsch", "English"]
    assert DEFAULT_LANGUAGE_CHOICE == "Deutsch"


@pytest.mark.parametrize(
    "key, german",
    [
        (Text.FAULT_LOG, "Störungsprotokoll"),
        (Text.SOURCE_SAMPLE, "Beispieldaten verwenden"),
        (Text.SOURCE_UPLOAD, "CSV hochladen"),
        (Text.SHIFT, "Schicht"),
        (Text.SHIFT_START, "Schichtbeginn"),
        (Text.SHIFT_END, "Schichtende"),
        (Text.SHIFT_CUSTOM, "Benutzerdefiniert"),
        (Text.GENERATE_REPORT, "Bericht erstellen"),
        (Text.SHIFT_REPORT, "Schichtbericht"),
        (Text.METRIC_EVENTS, "Ereignisse"),
        (Text.METRIC_MACHINES, "Maschinen"),
        (Text.METRIC_IN_SHIFT, "In dieser Schicht"),
        (Text.DOWNTIME_PER_MACHINE, "Stillstand pro Maschine"),
        (Text.DOWNTIME_MINUTES, "Stillstand (min)"),
        (Text.AGENT_STEPS, "Arbeitsschritte des Agenten"),
        (Text.TECHNICAL_DETAILS, "Technische Details"),
        (Text.DOWNLOAD_REPORT, "Bericht herunterladen"),
        (Text.QUOTA_NOTE, "Im kostenlosen Tarif sind etwa 5 Berichte pro Tag möglich."),
        (Text.WAIT_REASON_PACING, "Token-Limit pro Minute"),
        (Text.WAIT_REASON_RETRY_HINT, "Wartezeit laut KI-Dienst"),
        (Text.RUN_STOPPED, "Die Berichterstellung wurde ohne Ergebnis beendet: {answer}"),
    ],
)
def test_german_glossary(key: Text, german: str) -> None:
    assert GERMAN_TEXTS[key] == german


def test_shift_names_stay_german_in_english() -> None:
    assert ENGLISH_TEXTS[Text.SHIFT_EARLY].startswith("Early shift (Frühschicht)")
    assert ENGLISH_TEXTS[Text.SHIFT_LATE].startswith("Late shift (Spätschicht)")
    assert ENGLISH_TEXTS[Text.SHIFT_NIGHT].startswith("Night shift (Nachtschicht)")


def test_german_texts_use_the_formal_form() -> None:
    informal = re.compile(r"\b(du|dein|deine|dir|dich)\b", re.IGNORECASE)

    assert [key for key, value in GERMAN_TEXTS.items() if informal.search(value)] == []


class HardCodedTextFinder(ast.NodeVisitor):
    def __init__(self) -> None:
        self.findings: list[str] = []
        self._skipped: set[int] = set()

    def visit_Subscript(self, node: ast.Subscript) -> None:
        self._skip(node.slice)
        self.generic_visit(node)

    def visit_keyword(self, node: ast.keyword) -> None:
        if node.arg in ALLOWED_KEYWORDS:
            self._skip(node.value)
        self.generic_visit(node)

    def visit_Assign(self, node: ast.Assign) -> None:
        names = [target.id for target in node.targets if isinstance(target, ast.Name)]
        if names and all(name.endswith(ALLOWED_CONSTANT_SUFFIXES) for name in names):
            self._skip(node.value)
        self.generic_visit(node)

    def visit_Constant(self, node: ast.Constant) -> None:
        if (
            id(node) not in self._skipped
            and isinstance(node.value, str)
            and LETTER.search(node.value)
            and node.value not in ALLOWED_LITERALS
        ):
            self.findings.append(f"line {node.lineno}: {node.value!r}")

    def _skip(self, node: ast.AST) -> None:
        self._skipped.update(id(child) for child in ast.walk(node))


@pytest.mark.parametrize("file_name", SCANNED_FILES)
def test_no_hard_coded_user_visible_text(file_name: str) -> None:
    finder = HardCodedTextFinder()
    finder.visit(ast.parse((SOURCE_DIR / file_name).read_text(encoding="utf-8")))

    assert finder.findings == []


def test_scanner_catches_hard_coded_widget_text() -> None:
    finder = HardCodedTextFinder()
    finder.visit(ast.parse('st.button("Generate report", key="generate")\nst.caption(f"Machines: {count}")'))

    assert finder.findings == ["line 1: 'Generate report'", "line 2: 'Machines: '"]
