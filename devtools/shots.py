"""Named shot recipes — the surfaces worth a screenshot, and how to reach each.

A recipe is data, not a script, so a reviewer can read what a shot claims to show
without running it. `steps` are executed by ``driver.mjs`` in order; `measure` names
the elements whose geometry is reported ALONGSIDE the image, because a screenshot
cannot prove a number and most of this app's layout defects were numbers (a frame
stuck at its fallback height, a sheet as tall as the story behind it).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

#: Wide desktop, and the phone the app is actually read on.
DESKTOP = (1440, 900)
PHONE = (390, 844)


@dataclass(frozen=True)
class Shot:
    key: str
    describe: str
    #: Which seeded scenario this shot needs on screen (see fixtures.SCENARIOS).
    scenario: str = "rich"
    steps: list[dict[str, Any]] = field(default_factory=list)
    #: Extra steps for one width only. The app is not one layout at two sizes: on a
    #: phone the mounted scenes live behind a region tab and the star map is a tab
    #: rather than a control in the aside, so a single step list cannot reach the same
    #: surface at both widths.
    desktop_steps: list[dict[str, Any]] = field(default_factory=list)
    phone_steps: list[dict[str, Any]] = field(default_factory=list)
    measure: tuple[str, ...] = (".ew-root",)
    sizes: tuple[tuple[int, int], ...] = (DESKTOP, PHONE)
    themes: tuple[str, ...] = ("dark", "light")
    full_page: bool = False


#: The star map's own control is labelled "人生星图" in the desktop aside and "星图" on
#: the phone tab bar, so a shot that runs at both widths has to address the shorter one
#: as a prefix rather than pick one and fail at the other width.
_STAR_TAB = "星图"


#: Opening a seeded life from the shelf. Addressed by the life's LABEL, which is the
#: card's heading and unique per scenario — the card's `title` is the world's name and
#: is shared by every life in it, and it also matches the world's own card, so a title
#: click lands on whichever the shelf happens to render first.
def _open(label: str) -> list[dict[str, Any]]:
    # `home` first: the app resumes the life you last read, so without it a shot
    # inherits whatever the previous shot opened.
    return [{"home": True}, {"click": label}, {"wait": ".ew-play-root"}]


SHOTS: list[Shot] = [
    Shot(
        "shelf",
        "the app's landing page with five seeded lives and both bundled worlds",
        measure=(".ew-root",),
        full_page=True,
    ),
    Shot(
        "play",
        "a life mid-story: prose, choices, the status aside",
        steps=_open("第三天 · 井边"),
        measure=(".ew-play-root", ".ew-prose", ".ew-aside"),
        full_page=True,
    ),
    Shot(
        "scene-ledger",
        "the mounted keyvalue ledger — the scene whose rows rendered empty from a "
        "stale compiled-bytes cache, and whose frame reported no height",
        steps=_open("第三天 · 井边"),
        # Desktop shows every mounted scene below the story; a phone files them under
        # the region tab the scene was mounted with ("物资" here).
        desktop_steps=[{"scrollTo": ".ew-slot-on"}, {"seconds": 1}],
        # The phone tab is named by the scene's REGION (as the app's own content names
        # it — "背包" for `pack`), not by the label the scene was mounted with.
        phone_steps=[{"click": "背包"}, {"wait": ".ew-slot-on:visible"}, {"seconds": 1}],
        measure=(".ew-slot-on", ".ew-scenes-clear"),
    ),
    Shot(
        "starmap",
        "the life star map as an in-panel sheet: it must cover the app and nothing "
        "outside it, and bring itself into view when opened",
        steps=[
            *_open("第三天 · 井边"),
            {"click": _STAR_TAB, "exact": False},
            {"wait": ".ews-overlay"},
            {"seconds": 1},
        ],
        measure=(".ews-overlay", ".ews-lens-pane", ".ew-root"),
    ),
    Shot(
        "starmap-people",
        "the relations lens — a canvas layout, the one lens whose geometry is computed",
        steps=[
            *_open("第三天 · 井边"),
            {"click": _STAR_TAB, "exact": False},
            {"wait": ".ews-overlay"},
            {"click": "人物"},
            {"seconds": 1},
        ],
        measure=(".ews-overlay", ".ews-lens-pane"),
    ),
    Shot(
        "keepsakes",
        "the keepsakes lens with two seeded keepsakes and their story-card controls",
        steps=[
            *_open("第三天 · 井边"),
            {"click": _STAR_TAB, "exact": False},
            {"wait": ".ews-overlay"},
            {"click": "纪念"},
            {"seconds": 1},
        ],
        measure=(".ews-overlay", ".ews-lens-pane"),
    ),
    Shot(
        "short-turn",
        "a one-turn life: the geometry that exposes anything sized from the story "
        "rather than from itself",
        scenario="short",
        steps=_open("一回合"),
        measure=(".ew-play-root", ".ew-prose"),
    ),
    Shot(
        "ended",
        "a closed life's page — the epilogue, with no action controls",
        scenario="ended",
        # The ending page is NOT a `.ew-play-root`: a closed life renders its own plain
        # container, so it is waited for by the badge that only it shows.
        steps=[{"home": True}, {"click": "撑不到雨季"}, {"wait": ".ew-note-live"}],
        measure=(".ew-root", ".ew-note-live"),
    ),
    Shot(
        "long-title",
        "a shelf card carrying a title no card was designed for",
        scenario="longtitle",
        measure=(".ew-root",),
    ),
    Shot(
        "english",
        "the English pack: the same surfaces with wider labels",
        scenario="english",
        steps=_open("Day Three"),
        measure=(".ew-play-root", ".ew-prose"),
    ),
]

BY_KEY = {s.key: s for s in SHOTS}
