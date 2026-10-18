from dataclasses import dataclass
from datetime import datetime

from maestro.language import ReportLanguage

TIMESTAMP_FORMATS = {ReportLanguage.ENGLISH: "%Y-%m-%d %H:%M", ReportLanguage.GERMAN: "%d.%m.%Y %H:%M"}
DATE_FORMATS = {ReportLanguage.ENGLISH: "%Y-%m-%d", ReportLanguage.GERMAN: "%d.%m.%Y"}


@dataclass(frozen=True)
class ReportFormatter:
    language: ReportLanguage = ReportLanguage.ENGLISH

    def number(self, value: float) -> str:
        text = f"{value:.1f}"
        if self.language is ReportLanguage.GERMAN:
            return text.removesuffix(".0").replace(".", ",")
        return text

    def timestamp(self, value: datetime) -> str:
        return value.strftime(TIMESTAMP_FORMATS[self.language])

    def date(self, value: datetime) -> str:
        return value.strftime(DATE_FORMATS[self.language])
