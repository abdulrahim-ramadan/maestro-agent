from enum import Enum


class ReportLanguage(Enum):
    ENGLISH = "en"
    GERMAN = "de"

    @property
    def display_name(self) -> str:
        return {"en": "English", "de": "German"}[self.value]
