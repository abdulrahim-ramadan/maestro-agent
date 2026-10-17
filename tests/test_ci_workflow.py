import re
from pathlib import Path

WORKFLOW = Path(__file__).resolve().parent.parent / ".github" / "workflows" / "ci.yml"


def test_ci_token_is_read_only() -> None:
    assert re.search(r"^permissions:\n  contents: read$", WORKFLOW.read_text(encoding="utf-8"), re.MULTILINE)
