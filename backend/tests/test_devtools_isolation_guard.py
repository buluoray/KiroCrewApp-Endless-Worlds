"""The throwaway instance must not capture the operator's real agent specs.

Enabling an app registers its agents into kiro-cli's OWN directory, which no data-home
override moves. A harness instance that let that write through repointed the operator's
live specs at its scratch install; because the app's MCP server resolves its data dir
from its own file location, the operator's next session read fixture data and reported
their own save as missing. Nothing connected the two, which is what makes this worth a
guard and worth a test of the guard.

What is under test is the guard's DISCRIMINATION, not that it can fail. It shares a
machine with the gateway that drives it, and the host rewrites every spec at once when
it re-registers agents — so a guard keyed on "did these files change" stops the harness
dead on a working machine, and one keyed on "do these files now lead into this instance"
answers the question the bug actually poses.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_ROOT / "devtools"))

import instance  # noqa: E402


@pytest.fixture()
def shared(tmp_path, monkeypatch) -> Path:
    """A stand-in for the operator's `~/.kiro/agents`, with one live spec in it."""
    agents = tmp_path / "kiro-shared" / "agents"
    agents.mkdir(parents=True)
    (agents / "mine.json").write_text(
        json.dumps({"mcpServers": {"x": {"command": "/opt/real/app/server.py"}}}),
        encoding="utf-8",
    )
    monkeypatch.setenv("KIRO_HOME", str(tmp_path / "kiro-shared"))
    return agents


def test_a_spec_repointed_at_the_instance_is_refused(shared, tmp_path) -> None:
    """The bug itself: a shared spec that now leads into the ephemeral install."""
    home = tmp_path / "uishot-home"
    home.mkdir()
    before = instance._shared_agent_specs()
    (shared / "mine.json").write_text(
        json.dumps({"mcpServers": {"x": {"command": str(home / "apps/ew/backend/mcp.py")}}}),
        encoding="utf-8",
    )
    with pytest.raises(instance.InstanceError) as caught:
        instance._assert_untouched(before, home)
    # The message has to name the file and the path, because the remedy is per-file
    # and the operator is reading this instead of the debugging session it replaces.
    assert "mine.json" in str(caught.value)
    assert str(home) in str(caught.value)


def test_a_spec_rewritten_by_someone_else_is_reported_not_fatal(shared, tmp_path, capsys) -> None:
    """Another process re-registering agents is not this instance's write to refuse.

    Measured on a real machine: the operator's own gateway rewrote 17 specs — for
    apps this instance never installs — inside the install window, and an
    mtime-keyed guard called that broken isolation and refused to start.
    """
    home = tmp_path / "uishot-home"
    home.mkdir()
    before = instance._shared_agent_specs()
    (shared / "mine.json").write_text(
        json.dumps({"mcpServers": {"x": {"command": "/opt/real/app/server.py", "v": 2}}}),
        encoding="utf-8",
    )
    (shared / "someone-elses.json").write_text(json.dumps({"name": "atlas"}), encoding="utf-8")

    instance._assert_untouched(before, home)

    said = capsys.readouterr().out
    assert "none point at this instance" in said, "a silent pass teaches nobody anything"
    assert "mine.json" in said or "someone-elses.json" in said


def test_an_untouched_shared_dir_passes_quietly(shared, tmp_path, capsys) -> None:
    home = tmp_path / "uishot-home"
    home.mkdir()
    instance._assert_untouched(instance._shared_agent_specs(), home)
    assert capsys.readouterr().out == ""


def test_a_spec_appearing_where_there_were_none_still_reads_as_a_change(
    tmp_path, monkeypatch, capsys
) -> None:
    """No "both sides empty, nothing to check" escape.

    An empty first reading is either a machine with no shared specs — where an
    appearing one is exactly the write to look at — or a broken resolver. Treating
    either as a pass is how the first version of this guard stayed silent through
    the bug it was written for.
    """
    agents = tmp_path / "kiro-shared" / "agents"
    agents.mkdir(parents=True)
    monkeypatch.setenv("KIRO_HOME", str(tmp_path / "kiro-shared"))
    home = tmp_path / "uishot-home"
    home.mkdir()
    before = instance._shared_agent_specs()
    assert before == {}
    (agents / "appeared.json").write_text(json.dumps({"name": "new"}), encoding="utf-8")
    instance._assert_untouched(before, home)
    assert "appeared.json" in capsys.readouterr().out


def test_capture_is_caught_even_when_it_predates_the_snapshot(shared, tmp_path) -> None:
    """Strictly stronger than comparing two readings.

    A content snapshot only sees writes inside its own window; the ownership
    reading does not need a window at all, so a spec already pointing at this
    instance when the snapshot is taken is still refused.
    """
    home = tmp_path / "uishot-home"
    home.mkdir()
    (shared / "mine.json").write_text(
        json.dumps({"mcpServers": {"x": {"command": str(home / "apps/ew/backend/mcp.py")}}}),
        encoding="utf-8",
    )
    before = instance._shared_agent_specs()
    with pytest.raises(instance.InstanceError):
        instance._assert_untouched(before, home)
