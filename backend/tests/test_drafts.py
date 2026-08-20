"""DraftStore status resolution — the record is judged, not trusted.

A draft's stored status can lie in two ways, and both must self-heal at read
time rather than wedge the review screen on a progress bar forever:

* ``generating`` past ``STALE_SECS`` — the worldsmith (or the whole gateway)
  died between the dispatch and the commit.
* ``new`` past ``STALE_SECS`` — the compile dispatch itself was lost (the
  client navigated away mid-fire, or the chat runtime refused the slot before
  ``mark_pending`` ran), so nothing ever moved the record.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest

_BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_BACKEND))

from drafts import STALE_SECS, DraftStore  # noqa: E402


@pytest.fixture()
def store(tmp_path):
    return DraftStore(tmp_path)


def _age(store: DraftStore, draft_id: str, field: str, secs: float) -> None:
    record = store._read_record(draft_id)
    record[field] = time.time() - secs
    store._write_record(draft_id, record)


def test_a_fresh_new_draft_reads_as_new(store):
    draft_id = store.create("a world about tide pools")
    assert store.record(draft_id)["status"] == "new"


def test_a_draft_stranded_at_new_reads_as_failed_after_the_stale_bound(store):
    """The compile dispatch was lost; without this the review screen polls a
    frozen 12% progress bar forever with no error and no retry."""
    draft_id = store.create("a world about tide pools")
    _age(store, draft_id, "createdAt", STALE_SECS + 60)
    resolved = store.record(draft_id)
    assert resolved["status"] == "failed"
    assert resolved["problem"]


def test_a_generating_draft_past_the_bound_reads_as_failed(store):
    draft_id = store.create("a world about tide pools")
    store.mark_pending(draft_id)
    _age(store, draft_id, "askedAt", STALE_SECS + 60)
    resolved = store.record(draft_id)
    assert resolved["status"] == "failed"
    assert resolved["problem"]


def test_resolution_never_writes_back(store):
    """Self-heal is a read-side judgement: a retry dispatch must still find the
    raw record it can move to ``generating``, not a poisoned ``failed``."""
    draft_id = store.create("a world about tide pools")
    _age(store, draft_id, "createdAt", STALE_SECS + 60)
    assert store.record(draft_id)["status"] == "failed"
    assert store._read_record(draft_id)["status"] == "new"


def test_a_recent_generating_draft_is_left_alone(store):
    draft_id = store.create("a world about tide pools")
    store.mark_pending(draft_id)
    assert store.record(draft_id)["status"] == "generating"
