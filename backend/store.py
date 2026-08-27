"""Run store: the only writer of run state.

Layout (design §3). Whole-value records go through ``AppStorage`` — it already
gives atomic tmp+rename and rejects path traversal in keys — while the chronicle
is a plain append-only file, because a KV store rewrites a whole value and
read-modify-writing a 300-turn chronicle every turn would be both slow and a
corruption risk.

    kv/run.<runId>.state.json     current world state
    kv/run.<runId>.prev.json      last known good (rollback target)
    kv/index.json                 run list for the Lives view
    runs/<runId>/chronicle.jsonl  append-only, one line per turn

Key shape is constrained by AppStorage._key_path: no ``..``, ``/`` or ``\\``, and
no leading ``.`` or ``~``. Single dots are fine, and ``Path.stem`` strips only the
final suffix, so ``run.<id>.state`` round-trips through ``list_keys()``.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import time
import uuid
from pathlib import Path
from typing import Any

from kiro_crew.apps.app_storage import AppStorage

#: Run ids are minted here and never taken from a request, so a strict shape can
#: be enforced. Anything else is a caller bug, not user input to be sanitised.
_RUN_ID_RE = re.compile(r"^[0-9a-f]{32}$")

_INDEX_KEY = "index"


class StoreError(RuntimeError):
    """Raised for a caller mistake — bad run id, missing run, corrupt record."""


class CorruptRunState(StoreError):
    """The stored state could not be parsed.

    Carries the key so the caller can report *which* file to look at. The store
    never rewrites a record it could not read (R16.2).
    """

    def __init__(self, key: str) -> None:
        super().__init__(f"run state is unreadable: {key}")
        self.key = key


def new_run_id() -> str:
    return uuid.uuid4().hex


#: The brief's first line declares its lane. Parsed leniently — a lane the narrator
#: spelled oddly, or omitted, becomes ``""`` rather than a refusal: the brief is art
#: direction, and losing a page's art over a header is a worse outcome than not
#: enforcing the lane on that one page.
_LANE_RE = re.compile(r"^\s*LANE\s*:\s*(scene|motif)\b", re.IGNORECASE | re.MULTILINE)

#: The brief may also declare a painting STYLE. ``photo`` is the traced-photograph
#: pipeline (the historical scene path, now just one style among several);
#: ``watercolor``/``oil``/``minimal`` are hand-drawn painterly styles whose
#: technique lives in a per-style skill file the illustrator reads before drawing.
#: Parsed as leniently as the lane, and unknown spellings become ``""`` (no style)
#: rather than a refusal, for the same reason: losing a page's art over a header
#: is worse than not enforcing it on that one page.
_STYLE_RE = re.compile(
    r"^\s*STYLE\s*:\s*(photo|watercolor|oil|minimal)\b", re.IGNORECASE | re.MULTILINE
)


def brief_lane(brief: str) -> str:
    """``"scene"``, ``"motif"``, or ``""`` when the brief declares no usable lane."""
    match = _LANE_RE.search(brief or "")
    return match.group(1).lower() if match else ""


def brief_style(brief: str) -> str:
    """The declared painting style, or ``""`` when the brief names none usable."""
    match = _STYLE_RE.search(brief or "")
    return match.group(1).lower() if match else ""


def rewrite_brief_style(brief: str, enabled: list[str], substitute: str) -> str:
    """The brief with any DISABLED style replaced by the player's ``substitute``.

    This is where the settings' style allowlist is enforced: the rewrite happens
    once, at request time, so the stored brief — the only thing the illustrator
    ever reads — already carries an enabled style. Three cases:

    - The declared style is enabled (or the substitute itself): unchanged.
    - The declared style is disabled: the STYLE line's value is replaced in place,
      keeping the rest of the brief (the narrator's art direction) verbatim.
    - No style is declared but the brief is a SCENE and ``photo`` is disabled: a
      STYLE line is appended, because a style-less scene brief MEANS the photo
      pipeline (the historical default) and would otherwise route to a search the
      player switched off.

    A motif brief with no style is left alone — motifs are hand-drawn and never
    touch the photo pipeline.
    """
    declared = brief_style(brief)
    if declared and declared not in enabled:
        return _STYLE_RE.sub(lambda m: m.group(0)[: -len(m.group(1))] + substitute, brief, count=1)
    if not declared and brief_lane(brief) == "scene" and "photo" not in enabled:
        return f"{brief.rstrip()}\nSTYLE: {substitute}"
    return brief


def _check_run_id(run_id: str) -> None:
    if not _RUN_ID_RE.match(run_id):
        raise StoreError(f"malformed run id: {run_id!r}")


class RunStore:
    """Per-app run persistence. One instance per app, shared across requests."""

    def __init__(self, storage: AppStorage, data_dir: Path) -> None:
        self._kv = storage
        self._runs_dir = data_dir / "runs"

    # -- keys -------------------------------------------------------------

    @staticmethod
    def _state_key(run_id: str) -> str:
        return f"run.{run_id}.state"

    @staticmethod
    def _prev_key(run_id: str) -> str:
        return f"run.{run_id}.prev"

    @property
    def data_dir(self) -> Path:
        """The app data root this store writes under — for sibling per-run
        ledgers (perf, backdrop timeline) that live beside the chronicle."""
        return self._runs_dir.parent

    def _chronicle_path(self, run_id: str) -> Path:
        return self._runs_dir / run_id / "chronicle.jsonl"

    # -- state ------------------------------------------------------------

    def read_state(self, run_id: str) -> dict[str, Any]:
        _check_run_id(run_id)
        key = self._state_key(run_id)
        raw = self._kv.get(key)
        if raw is None:
            # AppStorage.get returns None both for "absent" and for
            # "unparseable JSON", so disambiguate before reporting.
            if (self._kv_file(key)).is_file():
                raise CorruptRunState(key)
            raise StoreError(f"no such run: {run_id}")
        if not isinstance(raw, dict):
            raise CorruptRunState(key)
        return raw

    def _kv_file(self, key: str) -> Path:
        # Mirrors AppStorage's own layout; used only to tell absent from corrupt.
        return self._runs_dir.parent / "kv" / f"{key}.json"

    def commit_state(self, run_id: str, state: dict[str, Any]) -> None:
        """Write ``state``, preserving the outgoing one as the rollback target.

        Order matters and is the whole crash story. The outgoing state is copied
        to ``prev`` *first*, then the new state is written. A crash between the
        two leaves both holding the outgoing state — consistent, and costing at
        most the turn in flight (R9.1). The write itself is atomic inside
        AppStorage, so ``state`` is never a half-written record.
        """
        _check_run_id(run_id)
        outgoing = self._kv.get(self._state_key(run_id))
        if isinstance(outgoing, dict):
            self._kv.set(self._prev_key(run_id), outgoing)
        self._kv.set(self._state_key(run_id), state)

    def rollback(self, run_id: str) -> dict[str, Any]:
        """Restore the last known good state and return it (R16.3)."""
        _check_run_id(run_id)
        prev = self._kv.get(self._prev_key(run_id))
        if not isinstance(prev, dict):
            raise StoreError(f"no rollback point for run {run_id}")
        self._kv.set(self._state_key(run_id), prev)
        return prev

    def read_prev(self, run_id: str) -> dict[str, Any]:
        """The state as of before the last commit, or empty if there is none.

        A read-only peek at the rollback point (never mutates current state, unlike
        :meth:`rollback`). Empty on a life's first turn, which is what lets a caller
        tell "just opened this month" from "open since birth".
        """
        _check_run_id(run_id)
        prev = self._kv.get(self._prev_key(run_id))
        return prev if isinstance(prev, dict) else {}

    # -- what changed since the narrator last looked ------------------------

    @staticmethod
    def fingerprint(state: dict[str, Any]) -> str:
        """A short, stable name for exactly this state.

        The point of it is self-certification. The narrator holds the fingerprint it
        was given last turn and hands it back; if it can still produce one, it still
        holds the state that went with it. If its context was compacted away, the
        fingerprint went with it, so it asks with nothing and receives everything —
        no flag, no bookkeeping, and no way for the app to be wrong about whether the
        narrator's baseline survived.

        That is why this keys on the STATE and not on the slot. A slot-based check
        detects a replaced conversation and nothing else; compaction leaves the same
        slot holding less, which is invisible from outside and is the case that makes
        a delta dangerous.

        ``sort_keys`` because a dict's order is not part of its meaning, and two
        serialisations of one state must not read as two states.
        """
        raw = json.dumps(state, sort_keys=True, separators=(",", ":"), default=str)
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]

    @staticmethod
    def diff(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
        """``{"changed": {...}, "same": [...], "gone": [...]}`` between two states.

        Top level only, and deliberately so. A per-leaf diff of a panel would send
        the narrator a shape that no longer resembles what it declared, and it has to
        reason about a panel as a whole anyway — "wealth went up but the rest of the
        household is as it was" is a sentence about one panel, not about a tree.
        """
        changed = {k: v for k, v in after.items() if k not in before or before[k] != v}
        same = sorted(k for k in after if k in before and before[k] == after[k])
        gone = sorted(k for k in before if k not in after)
        return {"changed": changed, "same": same, "gone": gone}

    @staticmethod
    def leaf_diff_paths(before: dict[str, Any], after: dict[str, Any]) -> list[str]:
        """Dotted paths of every LEAF that differs between two nested dicts.

        A leaf is any value that is not a dict on both sides; a key present on one
        side only is a leaf too. Lists compare as whole values — a reordered list
        is a change, and diffing inside one would invent an identity its items do
        not have. Dots inside a key are left as-is: these paths are matched only
        against paths produced by this same walk, never parsed back.
        """
        out: list[str] = []

        def walk(prefix: str, b: Any, a: Any) -> None:
            if isinstance(b, dict) and isinstance(a, dict):
                for key in sorted(set(b) | set(a)):
                    child = f"{prefix}.{key}" if prefix else str(key)
                    if key not in b or key not in a:
                        out.append(child)
                    else:
                        walk(child, b[key], a[key])
                return
            if b != a:
                out.append(prefix)

        walk("", before, after)
        return out

    # -- who wrote which leaf, per commit -----------------------------------
    #
    # The narrator declares the state; the backend then amends it (reserved keys,
    # digest/relations merge-forward, turn, milestones, systems). A delta read
    # wants to send back ONLY the amendments: the narrator remembers what it
    # itself declared, and re-sending its own words is the bulk of a delta on a
    # real life (measured: 4223 of 4696 bytes on turn 57 of one). One record per
    # commit is enough — ``baseline_for`` never resolves anything older than the
    # previous turn, so the only provenance a delta can need is the latest one.

    @staticmethod
    def _provenance_key(run_id: str) -> str:
        return f"provenance-{run_id}"

    def mark_provenance(self, run_id: str, *, turn: int, paths: list[str]) -> None:
        """Record which leaf paths the backend (not the narrator) wrote on ``turn``."""
        _check_run_id(run_id)
        self._kv.set(
            self._provenance_key(run_id),
            {"turn": int(turn), "paths": sorted(paths), "at": time.time()},
        )

    def provenance(self, run_id: str) -> tuple[int, list[str]]:
        """``(turn, backend-written leaf paths)`` of the latest commit, or ``(0, [])``.

        A reader must trust this only when the recorded turn equals the state's
        turn: an older record describes a commit whose amendments the narrator has
        already been shown, and using it would suppress leaves it never saw.
        """
        _check_run_id(run_id)
        raw = self._kv.get(self._provenance_key(run_id))
        if not isinstance(raw, dict):
            return 0, []
        paths = raw.get("paths")
        if not isinstance(paths, list):
            return 0, []
        try:
            turn = int(raw.get("turn") or 0)
        except (TypeError, ValueError):
            return 0, []
        return turn, [str(p) for p in paths]

    def baseline_for(self, run_id: str, fingerprint: str) -> dict[str, Any] | None:
        """The state that ``fingerprint`` names, if this store still holds it.

        Resolved against the two states already kept — the current one and the
        rollback copy of the outgoing one — and nothing else. No history of every
        state a life has passed through is stored for this, because the only baseline
        a delta is ever asked from is the previous turn: the narrator reads the
        runtime, a turn commits, and it reads again.

        A narrator further behind than that gets ``None`` and therefore a full
        snapshot. That is the correct answer rather than a limitation to apologise
        for — a delta against a baseline nobody can produce is exactly the thing that
        makes a narrator invent the parts it cannot see.
        """
        _check_run_id(run_id)
        for key in (self._state_key(run_id), self._prev_key(run_id)):
            candidate = self._kv.get(key)
            if isinstance(candidate, dict) and self.fingerprint(candidate) == fingerprint:
                return candidate
        return None

    def note_runtime_read(self, run_id: str, *, turn: int) -> None:
        """Record that the narrator looked before it narrated.

        Written, not enforced. A commit refused because the narrator skipped its
        reading would be a hard stop on a live life, and the honest order is to
        measure the behaviour before making it a rule.
        """
        _check_run_id(run_id)
        pending = self.read_pending(run_id)
        if isinstance(pending, dict):
            pending["readAt"] = time.time()
            pending["readTurn"] = int(turn)
            self._kv.set(self._pending_key(run_id), pending)

    def note_tool_call(self, run_id: str, tool: str) -> None:
        """Advance the in-flight turn's step count by one, naming the tool.

        Every tool call the narrator makes while a month is in flight is a unit of
        visible progress, so the play page can advance a cell per call rather than
        show one undifferentiated spinner. Only counts while a pending record
        exists — a call outside a turn has no turn to advance — and never raises:
        progress bookkeeping must not fail the tool it is counting.
        """
        _check_run_id(run_id)
        pending = self.read_pending(run_id)
        if isinstance(pending, dict):
            pending["steps"] = int(pending.get("steps") or 0) + 1
            pending["lastTool"] = str(tool)
            self._kv.set(self._pending_key(run_id), pending)

    # -- narrator installation generation ---------------------------------
    #
    # This is deliberately bookkeeping, not world state: updating the app may
    # replace the narrator conversation, but must not alter the life, rollback,
    # chronicle, worlds, or shelf rows.

    @staticmethod
    def _narrator_generation_key(run_id: str) -> str:
        return f"narrator-generation-{run_id}"

    def narrator_generation(self, run_id: str) -> str:
        """The app installation generation that owns this life's conversation."""
        _check_run_id(run_id)
        raw = self._kv.get(self._narrator_generation_key(run_id))
        return str(raw.get("generation") or "") if isinstance(raw, dict) else ""

    def mark_narrator_generation(self, run_id: str, generation: str) -> None:
        """Record a generation only after its replacement slot was created."""
        _check_run_id(run_id)
        self._kv.set(
            self._narrator_generation_key(run_id),
            {"generation": str(generation), "at": time.time()},
        )

    # -- the world's law, delivered once -----------------------------------
    #
    # The narrator's session is ONE conversation that spans every turn of a life:
    # measured on a live run, a single .jsonl held every turn of it, and every user
    # message in that file re-sent the whole 15,000-character rulebook. At turn four
    # the rulebook was 70% of a 21,700-character prompt, and it grows without bound
    # because nothing about it changes.
    #
    # So it is delivered once and then referred to. This marker is what "once" means;
    # it names the slot it was delivered to, because a rulebook read into a
    # conversation that no longer exists has not been delivered to the one that does.

    @staticmethod
    def _brief_key(run_id: str) -> str:
        return f"briefed-{run_id}"

    def mark_briefed(self, run_id: str, *, slot: str) -> None:
        """Record that this run's rulebook has been read into ``slot``.

        Called AFTER the prompt carrying it is dispatched, never before. Marking
        first and failing to send would leave a life whose narrator never saw its
        world; marking after and crashing costs one redundant re-send, which is the
        safe direction to be wrong in.
        """
        _check_run_id(run_id)
        self._kv.set(self._brief_key(run_id), {"slot": slot, "at": time.time()})

    def briefed_slot(self, run_id: str) -> str:
        """Which slot holds this run's rulebook, or "" if none does."""
        _check_run_id(run_id)
        raw = self._kv.get(self._brief_key(run_id))
        return str(raw.get("slot") or "") if isinstance(raw, dict) else ""

    def clear_briefed(self, run_id: str) -> None:
        """Forget that the rulebook was delivered — the next turn re-sends it.

        The companion to a conversation reset that KEEPS the slot: the marker
        names a slot, the slot survives, so without this the turn loop would
        conclude the (brand-new) conversation already holds the world's law.
        """
        _check_run_id(run_id)
        self._kv.delete(self._brief_key(run_id))

    # -- conversation rotation bookkeeping -----------------------------------
    #
    # One narrator conversation per life grows without bound (measured: 2.9 MB by
    # turn 57 on a real life), until the harness compacts it at an arbitrary point
    # and the narrator loses its baseline mid-scene. Rotation replaces that with a
    # PLANNED reset at a narratively clean point; this marker records the turn the
    # conversation last started fresh at, so one boundary triggers one reset even
    # when the same turn is requested twice (double-tap, retry, refresh).

    @staticmethod
    def _rotation_key(run_id: str) -> str:
        return f"rotation-{run_id}"

    def rotation_turn(self, run_id: str) -> int:
        """The committed turn the conversation last started fresh at (0 = never)."""
        _check_run_id(run_id)
        raw = self._kv.get(self._rotation_key(run_id))
        try:
            return int(raw.get("turn") or 0) if isinstance(raw, dict) else 0
        except (TypeError, ValueError):
            return 0

    def mark_rotation(self, run_id: str, *, turn: int) -> None:
        """Record that the conversation was fresh as of committed ``turn``."""
        _check_run_id(run_id)
        self._kv.set(self._rotation_key(run_id), {"turn": int(turn), "at": time.time()})

    # -- recall material already delivered in this conversation -------------
    #
    # Lore entries and recall candidates are re-SELECTED every turn (the same
    # keywords keep matching, the same old event keeps scoring), so a long life
    # re-sends the same bodies dozens of times to a narrator that already has them
    # in front of it. Measured on one life: a single lore entry delivered 26 times
    # and one 40-turn-old event 43 times, all byte-identical.
    #
    # The record is stamped with the rotation it was written under, so it
    # SELF-INVALIDATES: replacing the conversation makes every earlier id read as
    # unsent again without anyone having to remember to clear it. That is
    # load-bearing rather than tidy — THREE separate paths rotate a conversation
    # (an install change, a chapter boundary, the turn budget), and a clear wired
    # into two of them would leave the third suppressing a body the new
    # conversation never received.

    @staticmethod
    def _recall_sent_key(run_id: str) -> str:
        return f"recall-sent-{run_id}"

    def recall_sent(self, run_id: str) -> set[str]:
        """Ids whose full body was already delivered in the CURRENT conversation."""
        _check_run_id(run_id)
        raw = self._kv.get(self._recall_sent_key(run_id))
        if not isinstance(raw, dict):
            return set()
        try:
            stamped = int(raw.get("rotation") or 0)
        except (TypeError, ValueError):
            return set()
        if stamped != self.rotation_turn(run_id):
            return set()  # written under a conversation that no longer exists
        ids = raw.get("ids")
        return {str(i) for i in ids} if isinstance(ids, list) else set()

    def mark_recall_sent(self, run_id: str, ids: list[str], *, reset: bool = False) -> None:
        """Record that ``ids`` were delivered in full.

        ``reset=True`` REPLACES the set instead of adding to it, and is what a full
        read must pass. A full read means the narrator could not name a baseline — it
        was compacted, or this is the life's first turn — so it is holding nothing,
        and the rotation stamp cannot catch that case because a compaction does not
        rotate. Merging there would keep suppressing bodies the narrator has just
        demonstrably lost.
        """
        _check_run_id(run_id)
        fresh = {str(i) for i in ids}
        merged = fresh if reset else self.recall_sent(run_id) | fresh
        self._kv.set(
            self._recall_sent_key(run_id),
            {
                "rotation": self.rotation_turn(run_id),
                "ids": sorted(merged),
                "at": time.time(),
            },
        )

    # -- the turn in flight -----------------------------------------------
    #
    # A record that a turn was ASKED FOR, written before the narrator is spoken
    # to. It answers a question the state alone cannot: "is someone writing this
    # month right now?"
    #
    # Kept in its own key rather than inside the state, for two independent
    # reasons. ``commit_state`` copies the outgoing state to the rollback slot, so
    # a bookkeeping write through it would spend the ability to roll back to the
    # last NARRATED state on a note about waiting. And the narrator's own commit
    # replaces the state wholesale, carrying only RESERVED_STATE_KEYS forward — a
    # marker living in there would have its lifetime decided by the
    # content-carry-forward rule, which is about worlds, not about bookkeeping.

    @staticmethod
    def _pending_key(run_id: str) -> str:
        return f"pending-{run_id}"

    def mark_pending(self, run_id: str, *, turn: int, slot: str, action: str = "") -> None:
        """Record that ``turn`` was asked of ``slot``, before asking.

        The caller must do this BEFORE dispatching. Written after would leave open
        exactly the window it exists to close: the player leaves, the request dies
        mid-flight, and nothing on disk says a narrator is still working.
        """
        _check_run_id(run_id)
        self._kv.set(
            self._pending_key(run_id),
            {
                "turn": int(turn),
                "slot": slot,
                "askedAt": time.time(),
                # The player's own words, carried here so the narrator's commit can
                # fold them into the chronicle. Reviewing a past month is about
                # seeing the FORK, not only the outcome — and the commit path never
                # learns the action any other way, because the narrator is told the
                # intent in prose and does not echo it back.
                "action": action,
            },
        )

    def read_pending(self, run_id: str) -> dict[str, Any] | None:
        """The in-flight record, or ``None``.

        Advisory by construction: a gateway that died between the mark and the
        commit leaves one behind, so every reader has to judge it (by age, and by
        whether its slot still exists) rather than trust it.
        """
        _check_run_id(run_id)
        raw = self._kv.get(self._pending_key(run_id))
        return raw if isinstance(raw, dict) else None

    def clear_pending(self, run_id: str) -> None:
        """Forget the in-flight record. Safe when there is none."""
        _check_run_id(run_id)
        self._kv.delete(self._pending_key(run_id))

    # -- slot self-heal bookkeeping -----------------------------------------

    @staticmethod
    def _heal_key(run_id: str) -> str:
        return f"slot-heals-{run_id}"

    def count_slot_heals(self, run_id: str, turn: int) -> int:
        """How many times ``turn`` already replaced this life's narrator slot.

        Keyed per turn so the counter resets itself the moment the life moves on:
        the cap protects against a heal LOOP (a fresh slot that is also broken
        must surface as a failure, not churn a new conversation every deadline),
        never against healing a later turn.
        """
        _check_run_id(run_id)
        raw = self._kv.get(self._heal_key(run_id))
        if not isinstance(raw, dict) or int(raw.get("turn") or -1) != int(turn):
            return 0
        return int(raw.get("count") or 0)

    def note_slot_heal(self, run_id: str, turn: int) -> None:
        """Record one slot replacement for ``turn``."""
        _check_run_id(run_id)
        self._kv.set(
            self._heal_key(run_id),
            {"turn": int(turn), "count": self.count_slot_heals(run_id, turn) + 1},
        )

    # -- backdrop request (the narrator's brief for the illustrator) -------

    @staticmethod
    def _backdrop_request_key(run_id: str) -> str:
        return f"backdrop-request-{run_id}"

    def request_backdrop(self, run_id: str, *, turn: int, brief: str) -> None:
        """Record the narrator's BRIEF until that page's art actually commits.

        A first request starts a recovery record. If the narrator is later asked to
        recover a failed illustration and supplies a simpler brief for the SAME turn,
        the server keeps the fallback gate but resets illustrator attempts for the
        replacement direction. The record is cleared by a successful commit, never
        merely by dispatching an agent.

        The brief's declared LANE is parsed once, here, and stored beside it. Reading
        it at commit time instead would mean re-parsing prose at the gate, and the
        record is the only place the narrator's intent survives — a page whose brief
        asked for a SCENE and whose art arrived with no traced underlay was
        indistinguishable from a MOTIF page, so nothing noticed and nothing could be
        reconstructed afterwards (the brief is cleared on commit).
        """
        _check_run_id(run_id)
        prior = self.read_backdrop_request(run_id)
        recovering = bool(
            prior and int(prior.get("turn") or 0) == int(turn) and prior.get("fallbackAllowed")
        )
        self._kv.set(
            self._backdrop_request_key(run_id),
            {
                "turn": int(turn),
                "brief": str(brief),
                "lane": brief_lane(brief),
                "style": brief_style(brief),
                "askedAt": time.time(),
                "attempts": 0,
                "fallbackAllowed": recovering,
                "narratorNotified": recovering,
            },
        )

    def read_backdrop_request(self, run_id: str) -> dict[str, Any] | None:
        """The pending backdrop brief/recovery record, or ``None``."""
        _check_run_id(run_id)
        raw = self._kv.get(self._backdrop_request_key(run_id))
        return raw if isinstance(raw, dict) else None

    def update_backdrop_request(self, run_id: str, **changes: Any) -> dict[str, Any] | None:
        """Patch a live recovery record and return it; a missing record stays missing."""
        _check_run_id(run_id)
        current = self.read_backdrop_request(run_id)
        if current is None:
            return None
        current.update(changes)
        self._kv.set(self._backdrop_request_key(run_id), current)
        return current

    def clear_backdrop_request(self, run_id: str) -> None:
        """Forget the backdrop brief only after its page art commits."""
        _check_run_id(run_id)
        self._kv.delete(self._backdrop_request_key(run_id))

    # -- chronicle --------------------------------------------------------

    def append_turn(self, run_id: str, entry: dict[str, Any]) -> None:
        """Append one turn. A torn append costs the last line, never the file."""
        _check_run_id(run_id)
        path = self._chronicle_path(run_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(entry, ensure_ascii=False, separators=(",", ":"))
        with path.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")

    def read_chronicle(self, run_id: str) -> list[dict[str, Any]]:
        """Read every turn, skipping a torn trailing line rather than failing."""
        _check_run_id(run_id)
        path = self._chronicle_path(run_id)
        if not path.is_file():
            return []
        out: list[dict[str, Any]] = []
        for raw in path.read_text(encoding="utf-8").splitlines():
            if not raw.strip():
                continue
            try:
                out.append(json.loads(raw))
            except json.JSONDecodeError:
                continue
        return out

    # -- index ------------------------------------------------------------

    def read_index(self) -> list[dict[str, Any]]:
        raw = self._kv.get(_INDEX_KEY)
        if isinstance(raw, dict):
            runs = raw.get("runs")
            if isinstance(runs, list):
                return runs
        return []

    def upsert_index(self, summary: dict[str, Any]) -> None:
        """Record or refresh one run's Lives-view row.

        ``lastPlayed`` is rewritten on every call — it is what the shelf sorts by,
        so it must track the most recent month written. ``createdAt`` is written
        ONCE and then carried forward from the row already on file: a life's
        beginning does not change, and the shelf's "oldest first / by when I started
        it" ordering is only meaningful if this field stays put while `lastPlayed`
        moves. A row from before the field existed keeps `lastPlayed` as its
        stand-in, which orders it no worse than it was ordered before.
        """
        run_id = summary.get("runId")
        if not isinstance(run_id, str):
            raise StoreError("index summary needs a runId")
        _check_run_id(run_id)
        now = time.time()
        prior = next((r for r in self.read_index() if r.get("runId") == run_id), None)
        created = (prior or {}).get("createdAt") or summary.get("createdAt") or now
        summary = {**summary, "lastPlayed": now, "createdAt": float(created)}
        rows = [r for r in self.read_index() if r.get("runId") != run_id]
        rows.insert(0, summary)
        self._kv.set(_INDEX_KEY, {"runs": rows})

    def patch_index(self, run_id: str, changes: dict[str, Any]) -> bool:
        """Merge player-set metadata (label, archived) into a life's index row.

        Deliberately NOT :meth:`upsert_index`: it leaves ``lastPlayed`` and every
        other field alone, so renaming a life does not reorder the shelf by recency
        and does not clobber the row a turn commit never rewrites anyway. Returns
        False when the life is gone, so the route can answer 404 rather than
        silently succeeding on nothing.
        """
        _check_run_id(run_id)
        rows = self.read_index()
        for row in rows:
            if row.get("runId") == run_id:
                row.update(changes)
                self._kv.set(_INDEX_KEY, {"runs": rows})
                return True
        return False

    # -- lifecycle --------------------------------------------------------

    def create_run(self, state: dict[str, Any], summary: dict[str, Any]) -> str:
        run_id = new_run_id()
        state = {**state, "runId": run_id}
        self._kv.set(self._state_key(run_id), state)
        self.upsert_index({**summary, "runId": run_id})
        return run_id

    def deletable(self, run_id: str) -> str | None:
        """Why :meth:`delete_run` would fail for this life, or ``None`` if it
        should succeed.

        The non-destructive half of a bulk delete's all-or-nothing story: a world
        delete erases lives one at a time and cannot roll one back, so every life
        is checked HERE before the first is touched. Covers the systematic
        failure modes — a malformed id and an unwritable run directory tree; a
        failure between the check and the delete is still possible but is a
        race, not the common case.
        """
        try:
            _check_run_id(run_id)
        except StoreError as exc:
            return str(exc)
        run_dir = self._runs_dir / run_id
        if not run_dir.is_dir():
            return None  # nothing on disk to fail on
        # rmdir/unlink of a child needs WRITE on its parent directory; the tree
        # is small (a run holds a handful of files), so walking it is cheap.
        dirs = [run_dir] + [p for p in run_dir.rglob("*") if p.is_dir()]
        for d in dirs:
            if not os.access(d, os.W_OK | os.X_OK):
                return f"no permission to clear {d.name}"
        return None

    def delete_run(self, run_id: str) -> None:
        """Erase one life: state, rollback point, bookkeeping, chronicle, index row.

        Every key this class writes is dropped here, not just the two obvious ones.
        ``briefed-`` and ``pending-`` were left behind by an earlier version, which
        stayed invisible while nothing could delete a life — a leaked ``pending-``
        record makes :func:`turn.generating` report a month in flight for a life
        that no longer exists.
        """
        _check_run_id(run_id)
        self._kv.delete(self._state_key(run_id))
        self._kv.delete(self._prev_key(run_id))
        self._kv.delete(self._narrator_generation_key(run_id))
        self._kv.delete(self._brief_key(run_id))
        self._kv.delete(self._provenance_key(run_id))
        self._kv.delete(self._rotation_key(run_id))
        self._kv.delete(self._pending_key(run_id))
        self._kv.delete(self._backdrop_request_key(run_id))
        rows = [r for r in self.read_index() if r.get("runId") != run_id]
        self._kv.set(_INDEX_KEY, {"runs": rows})
        run_dir = self._runs_dir / run_id
        if run_dir.is_dir():
            for child in sorted(run_dir.rglob("*"), reverse=True):
                child.unlink() if child.is_file() else child.rmdir()
            run_dir.rmdir()
