"""Guards on UI state that must not outlive what it describes.

Three defects, one shape: a piece of local state kept on after the thing it was
about had changed or been only briefly unreachable.

- The play page was not keyed by the life it shows, so entering another life kept
  the previous life's typed words, armed choice and outstanding ask, and a read of
  the old life still in flight painted it over the new one for good.
- The draft review latched "this draft is gone" on ONE dropped poll of a compile
  that runs for minutes, and nothing ever took it back.
- The settings panel let Save run before (or after a failed) read of the player's
  settings, writing the panel's defaults over every field they had chosen, and a
  failed save said nothing at all.

These scan the source, like the other UI guards (see ``uisrc``), because the app
has no JS test runner. Each assertion names the property it protects so a
refactor that keeps the property keeps the test green.
"""

from __future__ import annotations

import re

import uisrc


def _play_page_element() -> str:
    src = uisrc.module("main.tsx")
    m = re.search(r"<PlayPage\b(.*?)/>", src, re.S)
    assert m, "main.tsx no longer renders the play page"
    return m.group(1)


def test_the_play_page_is_one_page_per_life():
    """Remounting per life is what clears every life-scoped piece of local state at
    once — and what makes a stale read of the previous life land on an unmounted
    page instead of the new one. Resetting state by hand would have to name every
    field, and the next field added would leak."""
    el = _play_page_element()
    key = re.search(r"\bkey=\{([^}]*)\}", el)
    assert key, "the play page is not keyed, so a new life inherits the old one's state"
    run = re.search(r"\brunId=\{([^}]*)\}", el)
    assert run and key.group(1).strip() == run.group(1).strip(), (
        "the play page must be keyed by the same value it is given as runId; "
        f"found key={{{key.group(1)}}} runId={{{run.group(1) if run else '?'}}}"
    )


def _review_source() -> str:
    src = uisrc.module("create-world.tsx")
    start = src.index("export function WorldDraftReview")
    return src[start:]


def test_one_dropped_poll_does_not_declare_a_draft_gone():
    """Only the server saying 404 makes a draft gone once it has been seen."""
    src = _review_source()
    load = re.search(r"const load = async \(\) => \{(.*?)\n  \}\n", src, re.S)
    assert load, "the review screen has no load()"
    body = load.group(1)
    catch = body[body.index("catch") :]
    assert "review.gone" in catch, "a missing draft is no longer reported at all"
    gone_at = catch.index("review.gone")
    guard = catch[:gone_at]
    assert re.search(r"\bif\s*\(", guard), (
        "every failed read is declared 'gone' — one dropped poll of a long compile "
        "becomes a dead end the next poll cannot undo"
    )
    assert "404" in guard, "the 'gone' verdict is not tied to the server saying so"


def _settings_source() -> str:
    return uisrc.module("settings.tsx")


def test_save_waits_for_the_players_settings_to_be_read():
    """Save writes every field. Before the read lands the fields are this panel's
    defaults, so a save then replaces the player's real choices with them."""
    src = _settings_source()
    save = re.search(r"const save = async \(\) => \{(.*?)\n  \}\n", src, re.S)
    assert save, "the settings panel has no save()"
    head = save.group(1).split("try", 1)[0]
    assert re.search(r"if \(\w+ !== 'ok'\) return", head), (
        "save() runs without the player's settings having been read"
    )
    label = src.index("{t('settings.save')}")
    button = src[src.rindex("<button", 0, label) : label]
    gate = re.search(r"disabled=\{([^}]*)\}", button)
    assert gate, "the Save button carries no disabled gate"
    assert "!== 'ok'" in gate.group(1), (
        "the Save button is enabled before the player's settings were read"
    )


def test_a_failed_read_or_save_is_said_out_loud():
    """A failed read pauses saving and says so (with a way to try again); a failed
    save says so instead of re-enabling the button silently."""
    src = _settings_source()
    reader = re.search(r"\.settings\(\)(.*?)\}, \[", src, re.S)
    assert reader, "the settings read is not found"
    assert re.search(r"\.catch\(\(\) => \{\s*if \(alive\) set\w+\('failed'\)", reader.group(1)), (
        "a failed settings read is swallowed, leaving Save writing defaults"
    )
    save = re.search(r"const save = async \(\) => \{(.*?)\n  \}\n", src, re.S)
    assert save and "catch" in save.group(1), "a failed save is not caught"
    for key in ("settings.saveFailed", "settings.readFailed", "settings.readRetry"):
        assert f"t('{key}')" in src, f"{key} is not shown"
