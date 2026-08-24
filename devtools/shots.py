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
#: A real external monitor. Not a third breakpoint — the app has two layouts — but the
#: only width where the reading track is wider than the prose measure (66ch, ~604px).
#: At 1440 the aside and the rails leave the track NARROWER than that, so every cap on
#: the story is inert there and a shot at 1440 cannot see one: the geometry that made
#: the story stop short of its own column only exists past this width.
WIDE = (1920, 1000)


@dataclass(frozen=True)
class Expect:
    """One assertion about where a surface is, checked against the measured boxes.

    Screenshots are for a person; these are for CI. They are deliberately about
    RELATIONSHIPS and presence, not pixel values: `.ews-overlay` covering the app
    panel is a property the layout must keep, while its exact height is a number that
    changes for legitimate reasons every time content does. A pinned pixel value would
    fail on every innocent edit and teach everyone to ignore the gate.
    """

    #: The element this expectation is about.
    selector: str
    #: `present` / `absent` — is it in the DOM and visible at all.
    presence: str = "present"
    #: Must be at least this wide/tall (px). A frame collapsed to its fallback height
    #: or a pane squeezed to zero is the failure this catches.
    min_w: int = 0
    min_h: int = 0
    #: Must horizontally cover this other element (same left/right within tolerance):
    #: how "the sheet covers the app panel" is stated without pinning a width.
    covers_x: str = ""
    why: str = ""


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
    #: What must hold about those boxes. Empty means "this shot is for looking at",
    #: which is a legitimate choice; a shot with expectations is also a test.
    expects: tuple[Expect, ...] = ()
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
        measure=(".ew-play-root", ".ew-prose", ".ew-turnpage", ".ew-aside"),
        sizes=(WIDE, DESKTOP, PHONE),
        expects=(
            Expect(
                ".ew-prose",
                covers_x=".ew-turnpage",
                why="the default reading width is `fluid`, which promises the story "
                "the track. A measure left on the prose alone does not narrow the "
                "recap, the digest or the echoes around it, so the story ends up the "
                "one block that stops short — a dead margin down its right side that "
                "reads as a broken layout rather than as a measure",
            ),
        ),
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
        expects=(
            Expect(
                ".ew-slot-on",
                min_h=140,
                why="a scene frame near 320px tall is sitting at the stylesheet's "
                "FALLBACK height, which means the document never reported its own — "
                "the signature of a frame that never ran our script",
            ),
        ),
    ),
    Shot(
        "starmap",
        "the life star map as an in-panel sheet: it must cover the app and nothing "
        "outside it, and take the scene frames off the page while it is up",
        steps=[
            *_open("第三天 · 井边"),
            {"click": _STAR_TAB, "exact": False},
            {"wait": ".ews-overlay"},
            {"seconds": 1},
        ],
        measure=(
            ".ews-overlay",
            ".ews-lens-pane",
            ".ew-root",
            ".ew-play-root",
            ".ew-slot-on",
            ".ew-turnpage",
        ),
        expects=(
            Expect(
                ".ews-overlay",
                min_w=280,
                min_h=300,
                covers_x=".ew-play-root",
                why="the sheet must span the column it covers; narrower means it is "
                "anchored to something else and the story shows past its edge",
            ),
            Expect(
                ".ew-turnpage",
                presence="absent",
                why="the sheet is transparent on purpose so the world's art shows "
                "through it, which also let the month's prose read through its "
                "negative space; the story has to go with the column, the way a "
                "phone's region tab replaces it",
            ),
            Expect(
                ".ew-slot-on",
                presence="absent",
                why="the mounted scene frames render OUTSIDE the play column, so a "
                "sheet anchored to that column cannot cover them — they have to step "
                "aside while it is open, or the story's widgets stay on screen "
                "underneath the star map",
            ),
        ),
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
    Shot(
        "heir",
        "the next generation: an inherited person and heirloom carried across from a "
        "finished life, on the heir's own first page",
        scenario="heir",
        steps=_open("银环的下一代"),
        measure=(".ew-play-root", ".ew-prose"),
        expects=(Expect(".ew-play-root", min_w=280, min_h=200),),
    ),
    Shot(
        "heir-starmap",
        "the heir's star map — an inheritance is only visible to a player as graph "
        "nodes that predate the life",
        scenario="heir",
        steps=[
            *_open("银环的下一代"),
            {"click": _STAR_TAB, "exact": False},
            {"wait": ".ews-overlay"},
            {"seconds": 1},
        ],
        measure=(".ews-overlay", ".ews-lens-pane"),
        expects=(
            Expect(
                ".ews-lens-pane",
                min_h=160,
                why="an heir whose inherited graph renders empty is the failure mode "
                "worth a shot of its own",
            ),
        ),
    ),
    Shot(
        "lineage-ending",
        "the finished life an heir inherits from: its epilogue is where the bridge is offered",
        scenario="lineage-ended",
        steps=[{"home": True}, {"click": "石桥那一夜"}, {"wait": ".ew-note-live"}],
        measure=(".ew-root", ".ew-note-live"),
        expects=(Expect(".ew-note-live", min_h=20),),
    ),
]

BY_KEY = {s.key: s for s in SHOTS}
