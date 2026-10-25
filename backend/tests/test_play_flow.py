"""What surrounds the story when a month lands while the reader is on the page.

Source-test style (see uisrc.py). The rendered behaviour is walked by
``devtools/play-flow.test.mjs`` in a seeded disposable pod.
"""

import re

from uisrc import module, styles


def test_the_open_lifes_rail_row_is_re_read_when_its_facts_move():
    play = module("play.tsx")
    # The signature carries exactly what the row shows, so an unchanged poll is free.
    assert "v.turn}|${v.awaitingOpening ? 1 : 0}|${v.ended ? 1 : 0}|${v.generating ? 1 : 0}" in play
    assert "onRowState?.(rowSig)" in play
    main = module("main.tsx")
    assert "onRowState={refreshRuns}" in main
    body = main.split("const refreshRuns = useCallback(", 1)[1].split("}, [])", 1)[0]
    assert ".runs()" in body
    # Only the newest read may land, or a late older list puts the row back.
    assert "seq === runsSeq.current" in body


def test_the_entry_recap_closes_when_a_newer_month_lands():
    play = module("play.tsx")
    load = play.split("const load = useCallback(async () => {", 1)[1].split("}, [runId])", 1)[0]
    closes = load.index("next.turn > recapTurn.current")
    opens = load.index("loadedRun.current !== runId")
    assert closes < opens, "a later load must be able to close the recap it opened"
    assert "setRecapOpen(false)" in load[closes:opens]
    assert "recapTurn.current = next.turn" in load[opens:]


def test_the_first_page_hint_does_not_climb_onto_the_prose():
    assert 'className="ew-hint ew-first-turn-hint"' in module("play.tsx")
    css = styles()
    assert re.search(r"\.ew-hint \{[^}]*margin-top: -10px", css), "premise: the shared pull"
    m = re.search(r"\.ew-hint\.ew-first-turn-hint \{\s*margin-top: (\d+)px", css)
    assert m and int(m.group(1)) >= 0


def _strings(lang: str) -> dict:
    import json

    from uisrc import WEB_SRC

    return json.loads((WEB_SRC / "strings" / f"{lang}.json").read_text("utf-8"))


def test_the_wait_shows_time_since_the_ask_without_reading_every_second_aloud():
    """A month takes 45-260s, so the wait names how long it has run. The clock
    counts from the server's ``askedAt`` (a reload keeps the real time), and sits
    OUTSIDE every live region: inside one, a screen reader reads each tick."""
    play = module("play.tsx")
    body = play.split("function TurnProgress", 1)[1].split("\nfunction ", 1)[0]
    assert "const askedAt = g?.askedAt ?? 0" in body
    assert "now / 1000 - askedAt" in body, "the clock must count from the ask, not the mount"
    assert '<span className="ew-progress-elapsed">{formatElapsed(elapsed)}</span>' in body
    # The wrapper is no longer a live region; only the label and the stage are.
    assert '<div className="ew-progress">' in body
    assert 'className="ew-progress" role=' not in body
    clock = body.index("ew-progress-elapsed")
    stage = body.index('<span role="status">{stage}</span>')
    assert stage < clock, "the stage's live region must close before the clock"
    fmt = play.split("function formatElapsed(", 1)[1].split("\n}\n", 1)[0]
    assert "Math.max(0, Math.floor(seconds))" in fmt, "a clock behind the server reads -0:02"
    assert "padStart(2, '0')" in fmt
    # Reduced motion: the clock is a text change, never an animation.
    css = styles()
    m = re.search(r"\.ew-progress-elapsed \{([^}]*)\}", css)
    assert m and "animation" not in m.group(1) and "transition" not in m.group(1)


def test_a_hidden_recap_can_be_reopened_from_the_pager():
    play = module("play.tsx")
    close = play.split('className="ew-story-moment-close"', 1)[1].split("</button>", 1)[0]
    assert "setRecapHidden(true)" in close, "hiding the recap must light the Recap button"
    assert "recapFocus.current = 'reopen'" in close
    pager = play.split("const pager =", 1)[1].split("const main =", 1)[0]
    assert "isLive && recapHidden && !recapOpen ?" in pager
    reopen = pager.split('className="ew-pager-recap"', 1)[1].split("</button>", 1)[0]
    assert "setRecapOpen(true)" in reopen and "t('play.recapReopen')" in reopen
    assert "recapFocus.current = 'close'" in reopen, "keyboard focus must not fall to body"
    # A newer month retires the recap AND its button: it no longer says where
    # the reader came back in.
    load = play.split("const load = useCallback(async () => {", 1)[1].split("}, [runId])", 1)[0]
    closes = load.index("next.turn > recapTurn.current")
    opens = load.index("loadedRun.current !== runId")
    assert "setRecapHidden(false)" in load[closes:opens]
    assert re.search(r"\.ew-pager-recap \{[^}]*min-height: 44px", styles())
    for lang in ("en", "zh"):
        assert _strings(lang).get("play.recapReopen"), f"{lang} lacks play.recapReopen"


def test_each_echo_line_names_its_own_event():
    """Two echoes of one page used to fold to the same line twice."""
    play = module("play.tsx")
    mark = play.split("function EchoMark(", 1)[1].split("\nexport function ", 1)[0]
    line = mark.split('className="ew-echo-line"', 1)[1].split("</button>", 1)[0]
    assert (
        "t('play.echoLineTitled', { title: e.title || e.sourceTitle, turn: e.sourceTurn })" in line
    )
    for lang in ("en", "zh"):
        s = _strings(lang).get("play.echoLineTitled", "")
        assert "{title}" in s and "{turn}" in s, f"{lang} echo line lacks its title"
