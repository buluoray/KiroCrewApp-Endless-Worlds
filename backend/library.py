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

#: A language tag, e.g. ``en``, ``zh``, ``pt-br``. A world id can never contain a
#: dot, so a dotted file stem is unambiguously a language VARIANT of a base world:
#: ``jianhuo-jiyuan.en.md`` is the English rendering of ``jianhuo-jiyuan``. Each
#: variant is a complete, ordinary pack (its own header + prose) whose ``id``
#: equals the base id and whose ``language`` equals the tag — so the whole render
#: and narrate pipeline is untouched; only which FILE a run reads changes.
_LANG_RE = re.compile(r"^[a-z]{2,3}(?:-[a-z0-9]{2,8})?$")


def _split_variant(stem: str) -> tuple[str, str] | None:
    """``("jianhuo-jiyuan", "en")`` for a variant stem, ``None`` for a base world.

    The base id is everything before the last dot; the language tag is the part
    after it. Returns ``None`` unless BOTH halves validate, so a base world (no
    dot) and any malformed name fall through to being treated as a world of their
    own rather than silently hidden as someone's variant.
    """
    base, dot, lang = stem.rpartition(".")
    if not dot:
        return None
    if _WORLD_ID_RE.match(base) and _LANG_RE.match(lang):
        return base, lang
    return None


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

    def _check_lang(self, language: str) -> str:
        if not isinstance(language, str) or not _LANG_RE.match(language):
            raise LibraryError(f"not a language tag: {language!r}")
        return language

    def path_for(self, world_id: str, language: str | None = None) -> Path:
        """The file a run reads. With no ``language`` (or none matching a variant)
        this is the base ``<id>.md``, whose header language is the world's primary
        one; a language with a sibling ``<id>.<lang>.md`` on disk resolves there.

        Falls back to the base rather than raising for an absent variant: the base
        IS the default-language rendering, so a run tagged with the primary
        language, or one whose variant was removed, still reads a real world.
        """
        self._check_id(world_id)
        if language:
            variant = self._worlds / f"{world_id}.{self._check_lang(language)}.md"
            if variant.is_file():
                return variant
        return self._worlds / f"{world_id}.md"

    def languages_for(self, world_id: str, primary: str | None = None) -> list[str]:
        """The languages a world can be played in — its primary first, then each
        sibling variant on disk.

        ``primary`` lets a caller that already parsed the BASE pack skip a re-read;
        pass it ONLY from the base ``<id>.md``, never from a variant (a variant's
        language is not the world's primary). When omitted, the primary is read
        from the base file so a caller holding only a variant still gets the full,
        correctly-ordered set rather than one that drops the base language.
        """
        self._check_id(world_id)
        langs: list[str] = []
        if primary:
            langs.append(primary)
        else:
            base = self._worlds / f"{world_id}.md"
            try:
                langs.append(read_world(base.read_text(encoding="utf-8")).template.language)
            except (TemplateError, WorldError, ContractTooNew, OSError):
                pass
        for path in sorted(self._worlds.glob(f"{world_id}.*.md")):
            split = _split_variant(path.stem)
            if split and split[0] == world_id and split[1] not in langs:
                langs.append(split[1])
        return langs

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
        # A world is one shelf entry across all its languages, so removing it takes
        # every ``<id>.<lang>.md`` rendering with it — otherwise a deleted world's
        # English text would linger and, worse, reinstall the base on the next
        # listing when the gravestone only guards the id.
        for path in self._worlds.glob(f"{world_id}.*.md"):
            split = _split_variant(path.stem)
            if split and split[0] == world_id:
                path.unlink(missing_ok=True)

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
            variant = _split_variant(seed_path.stem)
            try:
                seed_text = seed_path.read_text(encoding="utf-8")
                seed_pack = read_world(seed_text)
            except (TemplateError, WorldError, ContractTooNew, OSError) as exc:
                report.failed.append({"seed": seed_path.name, "problem": str(exc)})
                continue

            try:
                if variant:
                    # A variant installs beside its base under the language-tagged
                    # name, keyed for the gravestone on the base id it shares.
                    base_id, lang = variant
                    target = self._worlds / (
                        f"{self._check_id(base_id)}.{self._check_lang(lang)}.md"
                    )
                else:
                    base_id = seed_pack.id
                    target = self.path_for(base_id)
            except LibraryError as exc:
                report.failed.append({"seed": seed_path.name, "problem": str(exc)})
                continue

            if base_id in gone:
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

    def read(self, world_id: str, language: str | None = None) -> WorldPack:
        path = self.path_for(world_id, language)
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

        Language variants (``<id>.<lang>.md``) are NOT rows of their own — they are
        the same world in another language. Each base row carries a ``languages``
        list so the shelf can offer the choice.
        """
        if not self._worlds.is_dir():
            return []
        rows: list[dict[str, Any]] = []
        for path in sorted(self._worlds.glob("*.md")):
            if _split_variant(path.stem):
                continue
            world_id = path.stem
            try:
                pack = read_world(path.read_text(encoding="utf-8"))
                rows.append({
                    **summarize(pack), "usable": True,
                    "languages": self.languages_for(world_id, pack.template.language),
                })
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
        if not self._worlds.is_dir():
            return 0
        return sum(1 for p in self._worlds.glob("*.md") if not _split_variant(p.stem))
