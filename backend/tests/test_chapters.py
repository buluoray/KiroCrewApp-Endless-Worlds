"""Guards on cutting a rulebook into the parts a life needs.

A 15,000-character rulebook is not uniformly relevant. Most of the flagship describes
institutions a given life never enters — the academy's grading system matters to a
student and to nobody else — so briefing all of it buys context the life will never
use and hands the narrator material it may reach for merely because it is there.

Measured on the flagship after declaring 31 chapter boundaries: the opening brief is
6,081 characters instead of 15,063, and a marsh-village child cannot read the chapters
on nobility, guilds, magic, the academy, the church, or holding a domain at all.

Three properties carry the design, and each has a way of failing quietly:

* **The split is declared, never detected.** A regex for ``第N章`` in the app would be
  its first world-specific line, and it would silently do nothing for the next world.
* **No prose is unreachable.** Declaring 31 of 174 headings must not create holes; a
  chapter that fell between two declared ones would be missing from the book with
  nobody able to tell.
* **A gate is law, not a hint.** A refused chapter must be refused, or disclosure is
  advisory and a narrator that reads everything on turn one is where we started.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

_BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_BACKEND))

from chapters import PREAMBLE, ChapterError, bodies, brief, contents, read_chapter  # noqa: E402
from srcguard import code_only  # noqa: E402
from template import Chapter, TemplateError, parse_template  # noqa: E402
from world import read_world  # noqa: E402

FLAGSHIP = _BACKEND.parent / "seeds" / "jianhuo-jiyuan.md"


@pytest.fixture(scope="module")
def pack():
    if not FLAGSHIP.is_file():
        pytest.skip("flagship seed not present")
    return read_world(FLAGSHIP.read_text(encoding="utf-8"))


# ── the split belongs to the world ──────────────────────────────────────────


def test_the_app_carries_no_pattern_for_any_worlds_headings():
    """The load-bearing constraint. This world marks chapters with ``第N章 · …``;
    another might use ``Chapter N`` or a convention no regex can express. A pattern
    here would be the app's first world-specific line, and it would silently do
    nothing for every other world.
    """
    src = code_only((_BACKEND / "chapters.py").read_text(encoding="utf-8"))
    # The CONVENTIONS, not the word "Chapter" — `Chapter` and `ChapterError` are this
    # app's own identifiers and say nothing about how any world marks a section. An
    # earlier version of this test forbade the identifier and failed on its own import
    # line, which is a guard objecting to itself.
    for convention in ("第", "章", "節", "Chapter ", "CHAPTER", "#{1,3}"):
        assert convention not in src, (
            f"chapters.py knows how {convention!r} marks a section — that is one "
            "world's convention, not a fact about rulebooks"
        )
    # And no regex is applied to the prose at all.
    assert "re.match" not in src and "re.search" not in src, (
        "the prose is being pattern-matched instead of searched for declared headings"
    )


def test_a_heading_that_is_not_in_the_prose_is_refused_at_read_time(tmp_path):
    """Refused when the pack loads, not when the chapter is asked for twelve months
    in. The late failure looks like a world having nothing to say about its own
    academy."""
    text = (
        "---\n"
        'id: w\ntitle: W\nversion: "1"\nlanguage: en\n'
        "clock: {unit: month, label: Month}\n"
        "styles: [{id: s, label: S, default: true}]\n"
        "opening: [{id: o, label: O, kind: text}]\n"
        "panels: [{id: p, always: true, fields: [{id: f, label: F, primitive: field}]}]\n"
        "endings: [{id: e, when: state.dead == true}]\n"
        "digest: {categories: [c]}\nsave: [turn]\n"
        "chapters:\n  - {id: ghost, heading: A Chapter Nobody Wrote}\n"
        "---\n"
        "Only this line of prose.\n"
    )
    with pytest.raises(TemplateError) as caught:
        parse_template(text)
    assert "ghost" in str(caught.value)


def test_a_pack_with_no_chapters_behaves_exactly_as_before(pack):
    """Adding chapters to a pack is a change to that pack and to nothing else. A world
    that declares none briefs with its whole prose, which is how every pack behaved
    before any of this existed."""
    from dataclasses import replace

    plain = replace(pack.template, chapters=[])
    assert brief(plain) == plain.prose
    assert bodies(plain) == {}
    assert contents(plain, {}) == []


# ── nothing becomes unreachable ─────────────────────────────────────────────


def test_every_character_of_the_prose_lands_in_exactly_one_chapter(pack):
    """31 declarations partition 174 headings. Undeclared ones belong to the chapter
    above them and the text before the first belongs to the preamble — so a pack
    author who declares six boundaries does not thereby delete the rest of the book.
    """
    texts = bodies(pack.template)
    covered = sum(len(v) for v in texts.values())
    whole = len(pack.template.prose.strip())
    # The only loss is the whitespace between chapters, which `strip` removes.
    assert whole - covered < len(texts) * 3, (
        f"{whole - covered} characters of prose belong to no chapter"
    )


def test_the_text_above_the_first_declared_heading_is_not_lost(pack):
    """A world's title, epigraph and framing come before any chapter. Nobody should
    have to declare a chapter for the top of their own file, and losing it is silent:
    the pack still loads and the narrator simply never sees how the book opens."""
    texts = bodies(pack.template)
    assert PREAMBLE in texts
    assert texts[PREAMBLE].strip(), "the preamble was found but is empty"
    assert texts[PREAMBLE] in brief(pack.template), (
        "the world's own opening lines are not in the opening brief"
    )


def test_a_chapter_keeps_its_own_heading(pack):
    """A body arriving without its title reads as an excerpt from nowhere."""
    texts = bodies(pack.template)
    for chapter in pack.template.chapters:
        assert texts[chapter.id].startswith(chapter.heading), (
            f"{chapter.id} lost its heading"
        )


# ── a gate is law ───────────────────────────────────────────────────────────


def test_a_closed_chapter_is_refused_not_emptied(pack):
    """An empty body is indistinguishable from a world with nothing to say on the
    subject, and a narrator that reads it that way narrates the absence as a fact."""
    gated = next(c for c in pack.template.chapters if c.when is not None)
    with pytest.raises(ChapterError) as caught:
        read_chapter(pack.template, {"turn": 1}, gated.id)
    assert gated.id in str(caught.value)


def test_a_refusal_says_what_would_open_it(pack):
    """Otherwise the narrator learns only that a door is shut, which it can do nothing
    with."""
    gated = next(c for c in pack.template.chapters if c.when is not None)
    with pytest.raises(ChapterError) as caught:
        read_chapter(pack.template, {"turn": 1}, gated.id)
    assert gated.when is not None
    assert gated.when.source in str(caught.value)


def test_a_chapter_opens_when_its_condition_holds(pack):
    """The other half. A gate that never opens is not disclosure, it is deletion."""
    magic = next(c for c in pack.template.chapters if c.id == "magic")
    assert magic.when is not None

    shut = {"turn": 1, "magic": {"awakened": False}}
    with pytest.raises(ChapterError):
        read_chapter(pack.template, shut, "magic")

    open_now = {"turn": 1, "magic": {"awakened": True}}
    body = read_chapter(pack.template, open_now, "magic")
    assert body.startswith(magic.heading)


def test_an_ungated_chapter_is_readable_without_being_briefed(pack):
    """The third kind, and the reason the brief is small: ordinary life is texture the
    narrator reaches for when a month touches it, not law it must hold at all times.
    """
    on_request = [
        c for c in pack.template.chapters if not c.always and c.when is None
    ]
    assert on_request, "the pack declares nothing as available-on-request"
    body = read_chapter(pack.template, {"turn": 1}, on_request[0].id)
    assert body.strip()
    assert body not in brief(pack.template), (
        "a chapter meant to be fetched is already in the brief"
    )


def test_asking_for_a_chapter_this_world_does_not_have_is_refused(pack):
    with pytest.raises(ChapterError):
        read_chapter(pack.template, {"turn": 1}, "no-such-chapter")


# ── the table of contents ───────────────────────────────────────────────────


def test_the_contents_names_what_is_shut_and_why(pack):
    """A narrator cannot ask for a chapter it was never told exists, and "read the
    whole book to find out what is in it" is the behaviour being removed."""
    toc = contents(pack.template, {"turn": 1})
    assert len(toc) == len(pack.template.chapters)

    shut = [c for c in toc if not c["available"]]
    assert shut, "no chapter is gated; the disclosure is decorative"
    for row in shut:
        assert row["when"], f"{row['id']} is shut with no stated condition"


def test_the_contents_is_not_sent_every_turn(pack):
    """Measured, and it is the reason this rule exists: the flagship's contents is
    about a fifth of its book, so re-sending it every turn costs more than the book
    itself by the fifth turn. An earlier version of this test asserted the contents
    was small; it is not, and the honest fix was to stop repeating it rather than to
    loosen the threshold.
    """
    import json

    size = len(json.dumps(contents(pack.template, {"turn": 1}), ensure_ascii=False))
    assert size > len(pack.template.prose) // 10, (
        "this test is pointless if the contents is cheap — re-check the premise"
    )

    src = (_BACKEND / "mcp_server.py").read_text(encoding="utf-8")
    read = src[src.index("def _read_runtime") : src.index("def _mount_scene")]
    assert "if baseline is None:" in read, (
        "the contents is sent unconditionally; on a delta turn it should not be"
    )
    assert "chaptersOpened" in read, (
        "a delta turn never learns that the world opened a chapter"
    )


def test_a_chapter_the_world_just_opened_is_announced(pack):
    """The narrator is not expected to re-derive availability from a condition it
    cannot see the state for. Newly opened is pushed; the body is still pulled."""
    from chapters import opened_since

    before = {"turn": 1, "magic": {"awakened": False}}
    after = {"turn": 2, "magic": {"awakened": True}}
    assert "magic" in opened_since(pack.template, before, after)
    assert opened_since(pack.template, after, after) == []


def test_a_chapter_that_closed_again_is_not_announced(pack):
    """A world that revokes a chapter has taken away something already read. Reporting
    it would be the app deciding what the narrator remembers."""
    from chapters import opened_since

    was_open = {"turn": 1, "magic": {"awakened": True}}
    now_shut = {"turn": 2, "magic": {"awakened": False}}
    assert opened_since(pack.template, was_open, now_shut) == []


def test_the_brief_is_a_fraction_of_the_book(pack):
    """The measurement that justifies all of it. Not an assertion about a specific
    number — a pack author may reasonably brief more or less — but the property that
    briefing is a choice rather than the default of "everything"."""
    b = brief(pack.template)
    assert b.strip(), "the brief is empty; a narrator would have no world at all"
    assert len(b) < len(pack.template.prose) * 0.8, (
        f"the brief is {len(b)} of {len(pack.template.prose)} characters — declaring "
        "chapters bought nothing"
    )


def test_the_worlds_own_law_is_never_something_to_ask_for(pack):
    """The reality protocols and the anti-halo rules are why this world does not
    revolve around the player. A narrator that has to request them is a narrator that
    can forget to."""
    always = {c.id for c in pack.template.chapters if c.always}
    for essential in ("principles", "protections", "restraint"):
        assert essential in always, (
            f"{essential} is not in the opening brief — the narrator would have to "
            "know to ask for the rules that restrain it"
        )


def test_a_gate_reuses_the_flag_vocabulary_the_panels_already_use(pack):
    """Two vocabularies for one world is how a narrator ends up setting
    `magic.awakened` for the panel and `magic.unlocked` for the chapter, with one of
    them silently never true."""
    panel_paths: set[str] = set()
    for panel in pack.template.panels:
        if panel.when is not None:
            panel_paths.update(re.findall(r"state\.([\w.]+)", panel.when.source))
    chapter_paths: set[str] = set()
    for chapter in pack.template.chapters:
        if chapter.when is not None:
            chapter_paths.update(re.findall(r"state\.([\w.]+)", chapter.when.source))

    shared = panel_paths & chapter_paths
    assert shared, (
        f"chapters gate on {sorted(chapter_paths)} and panels on "
        f"{sorted(panel_paths)} — no flag is shared, so one set is dead"
    )


# ── what the compiler is told, and what it is told back ──────────────────────


def test_the_compiler_brief_explains_the_three_kinds():
    """A compiler that does not know `when` refuses reading and `always` is unasked
    will emit a split that looks right and discloses nothing."""
    from compile import COMPILER_BRIEF

    assert "chapters" in COMPILER_BRIEF
    for idea in ("VERBATIM", "always", "when", "BOUNDARIES"):
        assert idea in COMPILER_BRIEF, f"the brief never mentions {idea}"
    # The judgement, not just the syntax: which parts are law and which are texture.
    assert "TEXTURE" in COMPILER_BRIEF
    assert "halo" in COMPILER_BRIEF.lower(), (
        "the brief does not say the restraining rules must be briefed"
    )


def test_the_compiler_is_told_to_reuse_the_panels_flags():
    """Two spellings of one concept means one of them is never true, and the chapter
    behind it is unreachable for the whole life."""
    from compile import COMPILER_BRIEF

    assert "SAME flags" in COMPILER_BRIEF


def test_a_brief_that_is_most_of_the_book_is_reported(pack):
    """Reported, never refused. A pack that briefs everything is wasteful, not broken,
    and refusing it would make chapters a hurdle — a compiler that cannot get its
    split accepted stops declaring one."""
    from dataclasses import replace

    from compile import BRIEF_SHARE_WARN, _chapter_warnings

    greedy = replace(
        pack.template,
        chapters=[replace(c, always=True, when=None) for c in pack.template.chapters],
    )
    warnings = _chapter_warnings(
        type(pack)(template=greedy), set()
    )
    assert any("opening brief is" in w for w in warnings), (
        f"briefing the whole book drew no warning (threshold {BRIEF_SHARE_WARN}%)"
    )

    # And the real pack, which does choose, draws none.
    panel_paths = {
        p for panel in pack.template.panels if panel.when is not None
        for p in panel.when.referenced_paths()
    }
    assert not any(
        "opening brief is" in w for w in _chapter_warnings(pack, panel_paths)
    )


def test_a_gate_on_a_flag_nothing_sets_is_reported(pack):
    """Not a syntax error, and the pack plays. The material is simply unreachable for
    every life, which nobody notices until they go looking for it."""
    from compile import _chapter_warnings

    warnings = _chapter_warnings(pack, {"magic.awakened"})
    assert any("can never be read" in w for w in warnings), (
        "a chapter gated on a flag no panel uses drew no warning"
    )


def test_the_preview_shows_the_split_in_the_worlds_own_words(pack):
    """A person skims this before accepting a world. A split they cannot see is a
    split they cannot disagree with."""
    from compile import preview

    rows = preview(pack)["chapters"]
    assert len(rows) == len(pack.template.chapters)
    assert any(r["brief"] for r in rows), "nothing is shown as briefed"
    assert any(r["when"] for r in rows), "nothing is shown as held back"
    for row in rows:
        assert row["heading"] in pack.template.prose, (
            "the preview shows a heading the rulebook does not contain"
        )
