"""Narrator settings store: defaults, round-trip, and effort validation."""

from __future__ import annotations

import sys
from pathlib import Path

_BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_BACKEND))

from settings import read_settings, write_settings  # noqa: E402


def test_defaults_when_nothing_saved(tmp_path: Path) -> None:
    assert read_settings(tmp_path) == {"model": "", "reasoningEffort": ""}


def test_round_trip(tmp_path: Path) -> None:
    write_settings(tmp_path, model="some-model", reasoning_effort="high")
    assert read_settings(tmp_path) == {"model": "some-model", "reasoningEffort": "high"}


def test_an_unknown_effort_is_coerced_to_default(tmp_path: Path) -> None:
    # It becomes a subprocess argument downstream, so an unknown value is dropped
    # rather than stored.
    saved = write_settings(tmp_path, model="", reasoning_effort="turbo")
    assert saved["reasoningEffort"] == ""
    assert read_settings(tmp_path)["reasoningEffort"] == ""


def test_a_damaged_file_reads_as_default(tmp_path: Path) -> None:
    (tmp_path / "settings.json").write_text("{not json", encoding="utf-8")
    assert read_settings(tmp_path) == {"model": "", "reasoningEffort": ""}
