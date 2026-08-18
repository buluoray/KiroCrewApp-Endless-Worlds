"""Cutting a rulebook into the parts a life actually needs.

A 15,000-character rulebook is not uniformly relevant. Most of the flagship
describes institutions a given life never touches — the academy's grading system
matters to a student and to nobody else — so sending all of it on turn one buys
context the life will never use, and hands the narrator material it may start
reaching for merely because it is there.

Two decisions shape everything here.

**The split is declared, never detected.** This world marks its chapters with
``第N章 · …``; another might use ``Chapter N``, or a rule of thumb no regex can
express. A pattern in this module would be the first world-specific line in the app,
which is precisely what the primitives exist to prevent. So a world names its own
headings, verbatim, and this module finds them.

**A gate is the world's law, not a hint.** Asking for a chapter whose condition does
not hold is refused. If it merely warned, disclosure would be advisory, and a
narrator that reads everything on turn one is the state we started from.
"""

from __future__ import annotations

from typing import Any

from template import Chapter, Template


class ChapterError(LookupError):
    """A chapter that cannot be served, and the machine reason why."""

    def __init__(self, chapter_id: str, reason: str) -> None:
        super().__init__(f"{chapter_id}: {reason}")
        self.chapter_id = chapter_id
        self.reason = reason


#: The text before the first declared heading — a world's title, its epigraph, its
#: opening framing. Synthetic, because no world should have to declare a chapter for
#: the top of its own file, and because losing it is silent: the pack still loads and
#: the narrator simply never sees what the book opens with.
PREAMBLE = "(preamble)"


def bodies(template: Template) -> dict[str, str]:
    """Chapter id → its text, cut at the declared headings.

    A chapter runs from its own heading to the start of the next declared one, in the
    order the PROSE puts them rather than the order the header lists them — a header
    that lists the academy before the church does not reorder the book.

    The heading line stays with its body. It is the chapter's own title in the world's
    own words, and a body arriving without it reads as an excerpt from nowhere.

    **Every character of the prose lands in exactly one body.** Undeclared text
    between two declared headings belongs to the chapter above it, and text before the
    first heading becomes ``PREAMBLE``. That is not tidiness: a world need not declare
    all 165 of its headings to benefit from declaring six, and material that fell
    between the declared ones would be unreachable — a rulebook with holes the pack
    author never asked for and cannot see.
    """
    if not template.chapters:
        return {}

    prose = template.prose
    marks: list[tuple[int, Chapter]] = []
    for chapter in template.chapters:
        at = prose.find(chapter.heading)
        if at < 0:
            # parse_template refuses this at read time; reaching here means a pack was
            # built by hand around the validator.
            raise ChapterError(chapter.id, "heading not found in prose")
        marks.append((at, chapter))
    marks.sort(key=lambda m: m[0])

    out: dict[str, str] = {}
    head = prose[: marks[0][0]].strip()
    if head:
        out[PREAMBLE] = head
    for i, (at, chapter) in enumerate(marks):
        end = marks[i + 1][0] if i + 1 < len(marks) else len(prose)
        out[chapter.id] = prose[at:end].strip()
    return out


def brief(template: Template) -> str:
    """The part of the rulebook that goes out unasked.

    A world with no declared chapters briefs with its whole prose — which is exactly
    how every pack behaved before chapters existed, and is why adding chapters to a
    pack is a change to that pack and to nothing else.

    The preamble is always briefed. A world's own opening lines are not a chapter the
    narrator can be expected to go and ask for by name.
    """
    if not template.chapters:
        return template.prose
    texts = bodies(template)
    parts: list[str] = []
    if PREAMBLE in texts:
        parts.append(texts[PREAMBLE])
    parts += [texts[c.id] for c in template.chapters if c.always and c.id in texts]
    return "\n\n".join(parts)


def contents(template: Template, state: dict[str, Any]) -> list[dict[str, Any]]:
    """The table of contents, as the narrator needs to see it.

    Sent on every runtime read, and cheap — a heading and two booleans per chapter.
    It has to be sent, because a narrator cannot ask for a chapter whose existence it
    was never told about, and "read the whole book to find out what is in it" is the
    behaviour being removed.

    ``available`` is the world's own answer about relevance right now. ``brief`` marks
    what the narrator was given without asking, so it does not spend a call
    re-fetching what it already holds.
    """
    return [
        {
            "id": c.id,
            "heading": c.heading,
            "brief": c.always,
            "available": c.available(state),
            # The condition in the world's words, so a narrator can see WHY a chapter
            # is closed and what would open it, rather than only that it is closed.
            "when": c.when.source if c.when is not None else "",
        }
        for c in template.chapters
    ]


def read_chapter(template: Template, state: dict[str, Any], chapter_id: str) -> str:
    """One chapter's text, or a refusal with a reason.

    Refusing rather than returning empty: an empty body is indistinguishable from a
    world that has nothing to say on the subject, and a narrator that reads it that
    way will narrate the absence as a fact.
    """
    chapter = next((c for c in template.chapters if c.id == chapter_id), None)
    if chapter is None:
        raise ChapterError(chapter_id, "no such chapter in this world")
    if not chapter.available(state):
        raise ChapterError(
            chapter_id,
            "this world does not disclose that yet"
            + (f"; it opens when {chapter.when.source}" if chapter.when else ""),
        )
    texts = bodies(template)
    body = texts.get(chapter_id, "")
    if not body:
        raise ChapterError(chapter_id, "heading found but the chapter is empty")
    return body


def opened_since(
    template: Template, before: dict[str, Any], after: dict[str, Any]
) -> list[str]:
    """Chapter ids the world has just opened.

    The table of contents is static per world and costs real tokens — measured on the
    flagship it is about a fifth of the book, so sending it every turn costs more than
    the book itself by the fifth turn. It therefore goes out once, with the brief and
    with any full snapshot, and a turn that receives only a delta receives only this:
    the chapters that were shut at the narrator's baseline and are open now.

    Nothing is reported as closing. A world that revokes a chapter has taken away
    something the narrator has already read, and pretending otherwise would be the
    app deciding what the narrator remembers.
    """
    return [
        c.id
        for c in template.chapters
        if c.available(after) and not c.available(before)
    ]
