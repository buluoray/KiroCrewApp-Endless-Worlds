# Library and lineage

`library.py` is the world shelf: it manages the world-pack files on disk, installs
the shipped seeds, and lists what is playable. `legacy.py` is the inheritance
bridge — it carries a chosen subgraph from a finished life into a new one at
creation time. The two are largely orthogonal (one owns world-pack files, the other
owns run chronicle records) and meet only when a new run is created in a world that
declares lineage. `legacy.py` is *not* file-format migration: world-pack
backward-compatibility (provenance defaults, unknown-key round-trip) lives in
`world.py` and `template.py`. Both modules treat the on-disk artifact as the single
source of truth and keep no drifting secondary index.

## Layout

| Path | What it is |
|---|---|
| `backend/library.py` | The world shelf. `WorldLibrary` over `data/worlds/<id>.md` (with `<id>.<lang>.md` variants); the directory listing *is* the index |
| `backend/library.py::WorldLibrary.list_worlds` | Lists every world file as a row, usable or not, carrying any staleness note or load problem |
| `backend/library.py::WorldLibrary.ensure_seeds_installed` | Installs shipped seeds once; never overwrites an installed or edited world; reports a newer seed rather than applying it |
| `backend/library.py::WorldLibrary.remove`, `restore`, `removed`, `_write_removed` | Deletion via gravestones (`removed.json`), and restore from seed |
| `backend/library.py::WorldLibrary._check_id`, `_check_lang`, `path_for` | Id/lang validation that runs before any path is touched |
| `backend/library.py::WorldLibrary._newer_seed`, `_split_variant` | Seed-version comparison; language-variant filename split |
| `backend/legacy.py::candidates` | The inheritable set offered on the ending screen — only entities the story actually revealed |
| `backend/legacy.py::build_bridge_record` | Copies the selected subgraph into the heir's own turn-0 chronicle record |
| `backend/legacy.py::narrator_summary` | Names and one-liners of what was carried — never the source graph or the ancestor run id |
| `backend/tests/test_library.py`, `test_delete_world.py`, `test_legacy.py` | The pinning tests named below |

## Load-bearing contracts

- **The directory listing is the index.** One file per world, optional language
  variants alongside; there is no play-count and no index database. A world on disk
  is a world on the shelf. `test_listing_reports_usable_worlds` and
  `test_the_shipped_flagship_seed_installs_and_lists` pin the listing against the
  filesystem.

- **A world id is validated before any path is touched.** `_check_id` (via
  `_WORLD_ID_RE`) runs before `path_for` builds a path, so a malformed or traversing
  id can never reach the filesystem. `test_a_malformed_world_id_never_touches_a_path`
  pins it across a table of bad ids.

- **Seeds are installed once, then reported — not applied.** `ensure_seeds_installed`
  runs on every shelf visit but never overwrites an installed or edited world; a
  newer seed version is surfaced through `_newer_seed` as a note, not copied over the
  player's copy (R1.6). `test_an_edited_installed_world_survives_a_newer_seed` and
  `test_a_seed_is_installed_once_and_then_left_alone` pin the write-suppression;
  `test_a_world_needing_a_newer_core_lists_both_versions` pins the report.

- **One unusable world lists as a row, never as an exception.** Because
  `ensure_seeds_installed` and the listing run on every visit, a single broken world
  or a single broken seed must not blank the shelf. A world that fails to load lists
  as a row carrying its `problem`; a broken seed lands in the failure report and the
  good seeds still install. `test_one_unusable_world_appears_as_a_row_and_the_rest_still_list`
  and `test_a_broken_seed_does_not_stop_a_good_one` pin it. Listing is deliberately
  not filtered by the gravestone set — hiding an on-disk file would mask a failed
  unlink (`test_a_world_still_on_disk_is_still_listed_even_once_marked_removed`).

- **Staleness is a flag, not a load error.** A world whose seed has moved on stays
  playable and carries its note; it is never rejected at load. Pinned by
  `test_a_stale_world_is_still_usable_and_carries_its_note`.

- **Deletion is a gravestone, and the write order is load-bearing.** Because
  `ensure_seeds_installed` would otherwise re-copy a deleted seed on the next visit,
  `remove` records a gravestone in `removed.json` and only then unlinks the file. The
  order matters: gravestone-first with a failed unlink is visible and fixable, while
  unlink-first with a failed gravestone write is a silent self-undo. A corrupt
  gravestone reads as empty rather than blanking the shelf. `test_the_gravestone_is_written_before_the_file_is_unlinked`,
  `test_a_removed_world_is_not_reinstalled_by_the_next_shelf_visit`, and
  `test_an_unreadable_gravestone_does_not_take_the_library_down` pin it.

- **A language variant is one world, not two.** `<id>.<lang>.md` is a variant of the
  same world, resolved by the run's language; removing the world takes every variant
  with it. `test_a_language_variant_is_one_world_not_two`,
  `test_read_resolves_the_run_s_language`, and
  `test_removing_a_world_takes_every_language_with_it` pin it.

- **Only visibly-lived entities are inheritable.** `candidates` offers only entities
  the story actually revealed (`disclosure == "known"`); the ending screen must not
  hand the heir something the source life never surfaced. `test_candidates_group_the_visible_and_hide_the_unlived`
  pins the split.

- **The bridge is a normal turn-0 chronicle record.** `build_bridge_record` copies
  the selection into the heir's own canonical chronicle as an ordinary turn-0 entry
  with an ordinary `memory` block, so the memory graph stays rebuildable from the
  chronicle and deleting the heir erases everything with no residue. A relation
  crosses only when both of its endpoints crossed. `test_the_bridge_record_rebuilds_into_a_working_graph`
  and `test_deleting_the_heir_leaves_no_bridge_residue` pin it;
  `test_the_bridge_carries_the_selection_and_only_the_selection`,
  `test_every_copied_node_names_its_source`, and
  `test_relations_cross_only_when_everything_they_touch_did` pin the copy semantics,
  and `test_an_unlived_or_unknown_selection_is_refused_whole` pins whole-or-nothing
  validation.

- **`inheritsFrom` is stamped server-side only and refused from the narrator.**
  Provenance of an inherited entity is written by `build_bridge_record`, never
  accepted from the narrator: the `endless_advance_turn` entity schema closes its
  property list, so a narrator-declared inheritance is rejected at the tool gate.
  `test_the_tool_schema_refuses_a_narrator_declared_inheritance` pins the refusal.

- **The ancestor run id is never served, and parallel lives share zero graph.**
  `narrator_summary` returns names and one-liners only — never the source graph or
  the ancestor run id — and the source life's bytes are immutable across bridging and
  heir play. `test_parallel_lives_share_nothing`, `test_a_bridged_life_reads_only_what_was_carried`,
  and `test_the_source_life_is_never_modified_by_the_bridge_or_the_heir` pin it.
