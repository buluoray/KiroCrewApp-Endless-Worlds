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
