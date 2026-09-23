"""Source parsing contracts shared by runtime loading and managed files."""

from pathlib import Path

import pytest

from apprc.user_files.env_files.layers import read_dotenv_file
from apprc.user_files.env_files._parsing import parse_dotenv_file


@pytest.mark.parametrize("read_values", [read_dotenv_file, parse_dotenv_file])
def test_interpolation_preserves_assignment_order(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, read_values
) -> None:
    """References see earlier assignments, including superseded duplicates."""
    monkeypatch.setenv("APPRC_PARSE_ROOT", "environment")
    path = tmp_path / "values.env"
    path.write_text(
        'FIRST="${APPRC_PARSE_ROOT}"\n'
        'APPRC_PARSE_ROOT="file"\n'
        'SECOND="${APPRC_PARSE_ROOT}"\n'
        'APPRC_PARSE_ROOT="last"\n'
        'THIRD="${APPRC_PARSE_ROOT}"\n',
        encoding="utf-8",
    )

    assert read_values(path) == {
        "FIRST": "environment",
        "APPRC_PARSE_ROOT": "last",
        "SECOND": "file",
        "THIRD": "last",
    }


@pytest.mark.parametrize("read_values", [read_dotenv_file, parse_dotenv_file])
def test_parser_distinguishes_absent_and_empty_values(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, read_values
) -> None:
    """Bare keys are absent; empty assignments and interpolation stay values."""
    monkeypatch.delenv("APPRC_PARSE_MISSING", raising=False)
    path = tmp_path / "values.env"
    path.write_text(
        'BARE\nEMPTY=""\nDEFAULT="${APPRC_PARSE_MISSING:-fallback}"\n'
        'MISSING="${APPRC_PARSE_MISSING}"\nLITERAL="$APPRC_PARSE_MISSING"\n',
        encoding="utf-8",
    )

    assert read_values(path) == {
        "EMPTY": "",
        "DEFAULT": "fallback",
        "MISSING": "",
        "LITERAL": "$APPRC_PARSE_MISSING",
    }
