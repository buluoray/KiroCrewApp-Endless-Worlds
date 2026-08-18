"""The world library — what the Library page lists.

Seeds ship in the install tree and are **copied** into ``data/worlds/`` on first
enable. After that the installed copy is authoritative: an app update rebuilds the
install tree but never touches ``data/`` (design §1.5), so a world the user edited
or played is safe. A newer seed is reported, never applied (R1.6).

One broken world must never hide the others (R1.8, R14.13), so listing collects
per-file failures as unusable rows instead of raising.

Removal needs a GRAVESTONE, not just an unlink. ``ensure_seeds_installed`` runs on
every read of the Library page, so a deleted seed-backed world would be copied
back in the moment the player returned to the shelf — deletion without a record of
it is not deletion, it is a flicker. The record doubles as the undo: the seed is
still in the install tree, so dropping the gravestone reinstalls the world on the
next listing.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from template import TemplateError
from world import (
    ContractTooNew,
    WorldError,
    WorldPack,
    install_seed,
    read_world,
    summarize,
)

#: World ids come from file names, so they are validated before ever touching a
#: path — a world file is user-supplied content and its name is part of that.
_WORLD_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")


class LibraryError(ValueError):
    pass


@dataclass
class SeedReport:
    installed: list[str]
    already_present: list[str]
    newer_seed_available: list[dict[str, str]]
    failed: list[dict[str, str]]
    #: Worlds the player removed. Reported so the shelf can say a seed-backed
    #: world is gone *and restorable*, rather than silently omitting it and
    #: leaving the player to wonder whether the app lost it.
    removed: list[str]


class WorldLibrary:
    def __init__(self, data_dir: Path, seeds_dir: Path) -> None:
        self._data = data_dir
        self._worlds = data_dir / "worlds"
        self._seeds = seeds_dir

    # -- paths ------------------------------------------------------------

    def _check_id(self, world_id: str) -> str:
        if not isinstance(world_id, str) or not _WORLD_ID_RE.match(world_id):
            raise LibraryError(f"not a world id: {world_id!r}")
        return world_id

    def path_for(self, world_id: str) -> Path:
        return self._worlds / f"{self._check_id(world_id)}.md"

    def seed_path_for(self, world_id: str) -> Path:
        return self._seeds / f"{self._check_id(world_id)}.md"

    # -- gravestones ------------------------------------------------------

    def _removed_path(self) -> Path:
        return self._data / "removed.json"

    def removed(self) -> set[str]:
        """Worlds the player deleted.

        An unreadable gravestone file reads as EMPTY rather than raising. The file
        exists to suppress reinstallation, and failing the whole Library page
        because that record is damaged would trade a cosmetic problem (a deleted
        world reappears) for a total one (no worlds at all).
        """
        try:
            raw = json.loads(self._removed_path().read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return set()
        ids = raw.get("worlds") if isinstance(raw, dict) else None
        if not isinstance(ids, list):
            return set()
        return {i for i in ids if isinstance(i, str) and _WORLD_ID_RE.match(i)}

    def _write_removed(self, ids: set[str]) -> None:
        """Atomic tmp+rename, like every other record this app keeps.

        A half-written gravestone file parses as absent, which resurrects a world
        the player deleted — the one outcome this whole mechanism exists to stop.
        """
        self._data.mkdir(parents=True, exist_ok=True)
        tmp = self._removed_path().with_suffix(".json.tmp")
        tmp.write_text(
            json.dumps({"worlds": sorted(ids)}, ensure_ascii=False), encoding="utf-8"
        )
        os.replace(tmp, self._removed_path())

    def remove(self, world_id: str) -> None:
        """Delete a world's file and record that it was deliberate.

        ORDER IS LOAD-BEARING: the gravestone is written BEFORE the unlink. Write
        first and fail to unlink, and the world is still on the shelf marked for
        removal — visible, wrong, and fixed by pressing delete again. Unlink first
        and fail to write, and the next visit to the Library page copies the seed
        back in: the deletion silently undoes itself, which is the failure the
        player cannot diagnose.
        """
        self._check_id(world_id)
        self._write_removed(self.removed() | {world_id})
        self.path_for(world_id).unlink(missing_ok=True)

    def restore(self, world_id: str) -> None:
        """Drop the gravestone so the next listing reinstalls the seed.

        Only ever recovers the SEED — a world the player had edited comes back as
        it shipped, not as they left it. Callers must say so; this method cannot.
        """
        self._check_id(world_id)
        self._write_removed(self.removed() - {world_id})

    # -- seeds ------------------------------------------------------------

    def ensure_seeds_installed(self) -> SeedReport:
        """Idempotent. Never overwrites an installed world (R1.6).

        Skips worlds the player removed. Without that check this method is an
        automatic undo for every deletion, because it runs on each read of the
        Library page — the very screen the player lands on after deleting.
        """
        report = SeedReport([], [], [], [], [])
        gone = self.removed()
        report.removed = sorted(gone)
        if not self._seeds.is_dir():
            return report
        self._worlds.mkdir(parents=True, exist_ok=True)

        for seed_path in sorted(self._seeds.glob("*.md")):
            try:
                seed_text = seed_path.read_text(encoding="utf-8")
                seed_pack = read_world(seed_text)
            except (TemplateError, WorldError, ContractTooNew, OSError) as exc:
                report.failed.append({"seed": seed_path.name, "problem": str(exc)})
                continue

            try:
                target = self.path_for(seed_pack.id)
            except LibraryError as exc:
                report.failed.append({"seed": seed_path.name, "problem": str(exc)})
                continue

            if seed_pack.id in gone:
                continue

            if target.exists():
                report.already_present.append(seed_pack.id)
                newer = self._newer_seed(target, seed_pack)
                if newer:
                    report.newer_seed_available.append(newer)
                continue

            try:
                target.write_text(install_seed(seed_text), encoding="utf-8")
            except (TemplateError, WorldError, OSError) as exc:
                report.failed.append({"seed": seed_path.name, "problem": str(exc)})
                continue
            report.installed.append(seed_pack.id)

        return report

    def _newer_seed(self, installed_path: Path, seed_pack: WorldPack) -> dict[str, str] | None:
        """Report a newer seed version without touching the installed copy."""
        try:
            installed = read_world(installed_path.read_text(encoding="utf-8"))
        except (TemplateError, WorldError, ContractTooNew, OSError):
            return None
        if installed.template.version == seed_pack.template.version:
            return None
        return {
            "worldId": seed_pack.id,
            "installed": installed.template.version,
            "available": seed_pack.template.version,
        }

    # -- reading ----------------------------------------------------------

    def read(self, world_id: str) -> WorldPack:
        path = self.path_for(world_id)
        if not path.is_file():
            raise LibraryError(f"no such world: {world_id}")
        return read_world(path.read_text(encoding="utf-8"))

    def list_worlds(self) -> list[dict[str, Any]]:
        """Every world, newest-titled first, with unusable ones listed too.

        A world that cannot be parsed appears as a row carrying its problem
        rather than vanishing — otherwise a typo in one file looks like the app
        losing a world.

        Deliberately NOT filtered by the gravestone list. A file on disk is a world
        on the shelf: if a removal wrote its gravestone and then failed to unlink,
        hiding the row would leave a world that is present, playable, and invisible.
        Listing it is what makes the failure visible and the retry obvious.
        """
        if not self._worlds.is_dir():
            return []
        rows: list[dict[str, Any]] = []
        for path in sorted(self._worlds.glob("*.md")):
            world_id = path.stem
            try:
                rows.append({**summarize(read_world(path.read_text(encoding="utf-8"))),
                             "usable": True})
            except ContractTooNew as exc:
                rows.append({
                    "worldId": world_id, "title": world_id, "usable": False,
                    "problem": str(exc),
                    "needsCore": exc.needed, "localCore": exc.local,
                })
            except TemplateError as exc:
                rows.append({
                    "worldId": world_id, "title": world_id, "usable": False,
                    "problem": f"{exc.field}: {exc.expected}", "field": exc.field,
                })
            except (WorldError, OSError, UnicodeDecodeError) as exc:
                rows.append({
                    "worldId": world_id, "title": world_id, "usable": False,
                    "problem": str(exc),
                })
        return rows

    def count(self) -> int:
        return len(list(self._worlds.glob("*.md"))) if self._worlds.is_dir() else 0
