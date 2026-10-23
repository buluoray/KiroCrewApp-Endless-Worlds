"""The throwaway gateway must outlive the `uishot up` that started it.

Found by playing: `up` printed "gateway ready", returned, and seconds later the
instance was gone. Its stdout was a pipe read by `up` itself; once `up` exited the
gateway's next print ("Checking for updates…") raised BrokenPipeError and took the
whole process down, so every later `shot` or browser session found nothing
listening. stdout now goes to a file that `up` polls for the ready line.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "devtools"))

import instance  # noqa: E402


def test_the_gateway_stdout_is_never_a_pipe(tmp_path, monkeypatch):
    seen: dict = {}

    class _Spawned(Exception):
        pass

    def fake_popen(argv, **kw):
        seen.update(kw)
        raise _Spawned

    monkeypatch.setattr(instance, "gateway_interpreter", lambda: Path(sys.executable))
    monkeypatch.setattr(instance, "_install_into", lambda home, interp: None)
    monkeypatch.setattr(instance, "_assert_untouched", lambda before, home: None)
    monkeypatch.setattr(instance, "_shared_agent_specs", lambda: {})
    monkeypatch.setattr(instance.subprocess, "Popen", fake_popen)

    with pytest.raises(_Spawned):
        instance.start(tmp_path / "home", tmp_path / "gateway.log")

    assert seen["stdout"] is not subprocess.PIPE, (
        "the gateway's stdout is a pipe owned by `up`; it breaks the moment `up` "
        "exits and the next print kills the instance"
    )
    assert getattr(seen["stdout"], "name", "") == str(tmp_path / "gateway.stdout")


def test_the_ready_line_is_read_from_the_file(tmp_path):
    out = tmp_path / "gateway.stdout"
    assert instance.read_ready_line(out) is None
    out.write_text('👻 starting…\nKIROCREW_READY:{"port": 4242, "token": "t"}\n', encoding="utf-8")
    assert instance.read_ready_line(out) == {"port": 4242, "token": "t"}


def test_a_half_flushed_ready_line_is_not_misread(tmp_path):
    out = tmp_path / "gateway.stdout"
    out.write_text('KIROCREW_READY:{"port": 42', encoding="utf-8")
    assert instance.read_ready_line(out) is None
