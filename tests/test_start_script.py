import shutil
import subprocess
import sys
from pathlib import Path

import pytest

START_SCRIPT = Path(__file__).resolve().parent.parent / "start_maestro.bat"


def test_start_script_activates_venv_and_starts_the_ui() -> None:
    script = START_SCRIPT.read_bytes().decode("utf-8")

    assert 'cd /d "%~dp0"' in script
    assert 'call ".venv\\Scripts\\activate.bat"' in script
    assert "\nmaestro ui\r\n" in script
    assert script.count("goto :fail") == 3
    assert ":fail\r\necho.\r\npause\r\nexit /b 1" in script


def test_start_script_uses_windows_line_endings() -> None:
    content = START_SCRIPT.read_bytes()

    assert content.count(b"\n") == content.count(b"\r\n")


@pytest.mark.skipif(sys.platform != "win32", reason="batch files run only on Windows")
def test_start_script_without_venv_explains_and_waits(tmp_path: Path) -> None:
    copied_script = tmp_path / START_SCRIPT.name
    shutil.copy(START_SCRIPT, copied_script)

    result = subprocess.run(
        ["cmd", "/c", str(copied_script)],
        cwd=tmp_path,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 1
    assert b"Maestro is not installed yet: the folder .venv is missing." in result.stdout
    assert b"any key" in result.stdout or b"Taste" in result.stdout
