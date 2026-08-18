"""Guards on the shaped-field merge.

The bug these come from, measured on the live flagship rather than guessed:

``build_play_view`` builds each field as the world's own declaration —
``{"id", "label", "primitive", "options"}`` — and then spreads the shaped value over
it. So any key the shaper emits that COLLIDES with one of those four does not add
information, it destroys the world's. ``_shape`` for a ``rank`` returned
``{"kind": "rank", "label": <the value>}``, and the collision meant:

* the world declares ``standing`` with the label 社会地位 and nine tiers;
* the narrator wrote the free phrase "边地平民，普通一户" into it;
* the play page showed that phrase where the label belongs, with the field's real
  name gone entirely;
* and the UI rendered an EMPTY accent chip, because it read ``label_`` / ``value``
  and this branch sent neither — the meaningless little dot in the screenshot.

One key collision, two symptoms, and a key name that reads as completely harmless
at the line where it is written. That is why the test below is not about ``rank``:
it is about the merge, for every primitive, so the next shaper cannot reintroduce
the same shape under a different name.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

_BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_BACKEND))

from srcguard import code_only  # noqa: E402
from view import _shape, build_play_view  # noqa: E402
from world import read_world  # noqa: E402

FLAGSHIP = _BACKEND.parent / "seeds" / "jianhuo-jiyuan.md"

#: The keys ``build_play_view`` writes from the world's OWN declaration, before the
#: shaped value is spread over them. A shaper emitting any of these overwrites what
#: the world said.
DECLARED_KEYS = ("id", "label", "primitive", "options")

#: Every primitive a world may declare.
PRIMITIVES = (
    "field", "stat", "rank", "people", "trend", "resource", "inventory", "threads",
)


@pytest.fixture(scope="module")
def pack():
    if not FLAGSHIP.is_file():
        pytest.skip("flagship seed not present")
    return read_world(FLAGSHIP.read_text(encoding="utf-8"))


@pytest.mark.parametrize("primitive", PRIMITIVES)
@pytest.mark.parametrize(
    "raw",
    [
        "some prose the narrator wrote",
        {"label": "a nested label", "note": "n"},
        {"value": 3, "max": 10},
        ["a", "b"],
        42,
        None,
    ],
)
def test_no_shaper_can_overwrite_what_the_world_declared(primitive, raw):
    """The general rule, checked for every primitive against every input shape.

    Written as the general case on purpose. Testing only ``rank`` would leave the
    next shaper free to emit ``label`` — and the name looks harmless right up until
    a field loses its own.
    """
    shaped = _shape(primitive, raw)
    clashes = sorted(set(shaped) & set(DECLARED_KEYS))
    assert not clashes, (
        f"_shape({primitive!r}) emits {clashes}, which the merge spreads OVER the "
        f"world's own declaration — a field would lose its {clashes[0]}"
    )


def test_a_rank_keeps_the_label_the_world_gave_it(pack):
    """The live case, end to end on the real flagship template.

    The narrator's value is deliberately NOT one of the declared tiers, because that
    is what actually happened: a rank is a ladder and the narrator wrote a sentence.
    The field must still be recognisable as the thing the world named.
    """
    status = pack.template.panels[0]
    rank_fields = [f for f in status.fields if f.primitive == "rank"]
    assert rank_fields, "the flagship's status panel has no rank; this proves nothing"
    first = rank_fields[0]

    prose = "a phrase that is not any declared tier"
    view = build_play_view(
        pack.template,
        {"turn": 1, status.id: {first.id: prose}},
        chronicle=[{"turn": 1, "prose": "p"}],
        scenes=[],
    )
    shown = next(f for f in view["panels"][0]["fields"] if f["id"] == first.id)

    assert shown["label"] == first.label, (
        f"the field's declared label {first.label!r} was replaced by "
        f"{shown['label']!r} — the player sees prose where a name belongs"
    )
    assert shown["tier"] == prose, "the narrator's words must survive as the value"


def test_a_rank_the_narrator_said_nothing_about_shows_no_tier(pack):
    """An empty tier must be visibly empty. The old code produced an empty accent
    chip — a small coloured pill with no text, which reads as a broken widget rather
    than as "nothing has been said about this yet"."""
    status = pack.template.panels[0]
    first = next(f for f in status.fields if f.primitive == "rank")

    view = build_play_view(
        pack.template,
        {"turn": 1, status.id: {}},
        chronicle=[{"turn": 1, "prose": "p"}],
        scenes=[],
    )
    shown = next(f for f in view["panels"][0]["fields"] if f["id"] == first.id)
    assert shown["label"] == first.label
    assert not shown.get("tier"), "a rank nobody has spoken about must not claim one"


def test_the_ui_reads_the_key_the_backend_sends():
    """The other half of the same defect. The chip read ``label_``, which no shaper
    has ever emitted, and a type assertion is what kept the compiler quiet about it —
    so the pill rendered empty and the mismatch was invisible on both sides."""
    import uisrc

    ui = code_only(uisrc.module("ui.tsx"), lang="ts")
    api = code_only(uisrc.module("api.ts"), lang="ts")

    assert "label_" not in ui, "the chip is still reading a key nothing sends"
    assert "label_" not in api, "the dead field is still declared"
    assert "f.tier" in ui, "the tier is not rendered from the key the backend sends"
    assert "tier?: string" in api, "PlayView's field shape does not declare the tier"
