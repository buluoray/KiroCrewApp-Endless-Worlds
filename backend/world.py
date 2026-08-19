"""World packs — one file per world.

A world pack holds everything about one world: its prose rulebook, its compiled
header, the capability packs generated for it, and the widget specs that proved
reusable. Shipping a world is copying that file (design §4.2).

    ---
    { header … , compiledFrom: {…}, capabilityPacks: […], widgetSpecs: […] }
    ---
    《剑火纪元…》            ← prose, byte for byte, never parsed

Two rules that shape this module:

**Prose is never touched.** Read-modify-write must return the prose byte for byte.
Everything here treats it as an opaque blob measured only by its digest.

**Serialisation emits JSON, and that is why seeds keep their comments elsewhere.**
Writing a generated pack back into a world means re-emitting its front matter,
which would drop YAML comments. So a hand-maintained world (the flagship seed, with
its per-chapter citations) lives in ``seeds/`` and is *normalised* into
``data/worlds/`` on install: the comments stay in the repo for whoever maintains
them, and the runtime file is machine-managed JSON. This is the same split as
"a person may write YAML, an agent emits JSON" (design §4.4), one level up.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field as dc_field
from datetime import datetime, timezone
from typing import Any

from template import Template, TemplateError, parse_template, split_front_matter

#: Core contract this build speaks. A pack declaring a higher one is refused with
#: both numbers named (R14.9) rather than failing somewhere mid-play.
CONTRACT = 1

#: Bumped when the compiler's output would materially differ, so an old pack can
#: be recognised as improvable (R14.4).
COMPILER_VERSION = 1

#: Marks a header a person wrote rather than the agent compiling one.
HAND_COMPILED = "hand"


class WorldError(ValueError):
    """A world pack could not be used. Names what and why."""


class ContractTooNew(WorldError):
    def __init__(self, needed: int, local: int) -> None:
        super().__init__(
            f"this world needs core contract {needed}, this build speaks {local}"
        )
        self.needed = needed
        self.local = local


def prose_digest(prose: str) -> str:
    return hashlib.sha256(prose.encode("utf-8")).hexdigest()


@dataclass
class Provenance:
    """Where a header came from, so staleness is detectable (R14.4)."""

    prose_sha256: str
    compiler: str = HAND_COMPILED
    compiled_at: str = ""
    contract: int = CONTRACT

    @staticmethod
    def for_prose(prose: str, compiler: str = HAND_COMPILED) -> "Provenance":
        return Provenance(
            prose_sha256=prose_digest(prose),
            compiler=compiler,
            compiled_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
            contract=CONTRACT,
        )

    @staticmethod
    def from_dict(raw: Any) -> "Provenance | None":
        if not isinstance(raw, dict):
            return None
        digest = raw.get("proseSha256")
        if not isinstance(digest, str) or not digest:
            return None
        contract = raw.get("contract", CONTRACT)
        return Provenance(
            prose_sha256=digest,
            compiler=str(raw.get("compiler") or HAND_COMPILED),
            compiled_at=str(raw.get("compiledAt") or ""),
            contract=contract if isinstance(contract, int) else CONTRACT,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "proseSha256": self.prose_sha256,
            "compiler": self.compiler,
            "compiledAt": self.compiled_at,
            "contract": self.contract,
        }


@dataclass
class WorldPack:
    template: Template
    provenance: Provenance | None = None
    capability_packs: list[dict[str, Any]] = dc_field(default_factory=list)
    widget_specs: list[dict[str, Any]] = dc_field(default_factory=list)
    #: The header exactly as parsed, so serialisation can round-trip declarations
    #: this build does not know about instead of silently dropping them.
    raw_header: dict[str, Any] = dc_field(default_factory=dict)

    @property
    def id(self) -> str:
        return self.template.id

    @property
    def prose(self) -> str:
        return self.template.prose

    # -- provenance ------------------------------------------------------

    def is_stale(self) -> bool:
        """True when the prose has moved since the header was written (R14.5).

        A pack with no provenance at all is NOT stale — it predates the field, and
        calling it stale would flag every older world at once with nothing to act
        on.
        """
        if self.provenance is None:
            return False
        return self.provenance.prose_sha256 != prose_digest(self.prose)

    def staleness_note(self) -> str | None:
        """One plain sentence in the world's language, or None when fresh."""
        if self.provenance is None:
            return None
        if not self.is_stale():
            return None
        if self.template.language == "zh":
            return (
                "这个世界的设定在面板生成后有过改动，"
                "面板内容可能已经和设定对不上了。"
            )
        return (
            "This world's rulebook changed after its panels were generated, "
            "so the panels may no longer match it."
        )

    def is_improvable(self) -> bool:
        """True when a newer compiler could do better (R14.4)."""
        if self.provenance is None:
            return True
        if self.provenance.compiler == HAND_COMPILED:
            return False
        try:
            return int(self.provenance.compiler) < COMPILER_VERSION
        except (TypeError, ValueError):
            return False

    # -- generated content ------------------------------------------------

    def upsert_capability_pack(self, pack: dict[str, Any]) -> None:
        pack_id = pack.get("packId")
        if not isinstance(pack_id, str) or not pack_id:
            raise WorldError("a capability pack needs a packId")
        self.capability_packs = [
            p for p in self.capability_packs if p.get("packId") != pack_id
        ] + [pack]

    def upsert_widget_spec(self, spec: dict[str, Any]) -> None:
        """Promote a reusable widget's SPEC into the world (R14.8).

        Compiled HTML is never stored here: it is produced by the receiving
        machine at mount time, which is what keeps "widget bytes are always
        locally produced" true even for a pack that arrived from someone else.
        """
        widget_id = spec.get("widgetId")
        if not isinstance(widget_id, str) or not widget_id:
            raise WorldError("a widget spec needs a widgetId")
        if "html" in spec:
            raise WorldError(
                "a widget spec must not carry compiled html — store the spec only "
                "so the receiving machine compiles it locally"
            )
        self.widget_specs = [
            s for s in self.widget_specs if s.get("widgetId") != widget_id
        ] + [spec]


_GENERATED_KEYS = ("compiledFrom", "capabilityPacks", "widgetSpecs")


def read_world(text: str, *, local_contract: int = CONTRACT) -> WorldPack:
    """Parse a world file. Refuses a pack needing a newer core (R14.9)."""
    header, _prose = split_front_matter(text)

    raw_prov = header.get("compiledFrom")
    if isinstance(raw_prov, dict):
        needed = raw_prov.get("contract")
        if isinstance(needed, int) and needed > local_contract:
            raise ContractTooNew(needed, local_contract)

    template = parse_template(text)

    packs = header.get("capabilityPacks") or []
    specs = header.get("widgetSpecs") or []
    if not isinstance(packs, list):
        raise WorldError("capabilityPacks must be a list")
    if not isinstance(specs, list):
        raise WorldError("widgetSpecs must be a list")

    return WorldPack(
        template=template,
        provenance=Provenance.from_dict(raw_prov),
        capability_packs=[p for p in packs if isinstance(p, dict)],
        widget_specs=[s for s in specs if isinstance(s, dict)],
        raw_header={k: v for k, v in header.items() if k not in _GENERATED_KEYS},
    )


def serialize_world(pack: WorldPack) -> str:
    """Emit a world file. Prose is appended verbatim.

    The header is JSON: this is a machine-managed runtime file, and JSON avoids
    the YAML 1.1 traps that silently corrupt values (design §4.4).
    """
    header = dict(pack.raw_header)
    prov = pack.provenance or Provenance.for_prose(pack.prose)
    header["compiledFrom"] = prov.to_dict()
    if pack.capability_packs:
        header["capabilityPacks"] = pack.capability_packs
    if pack.widget_specs:
        header["widgetSpecs"] = pack.widget_specs

    body = json.dumps(header, ensure_ascii=False, indent=2, sort_keys=False)
    return f"---\n{body}\n---\n{pack.prose}"


def install_seed(seed_text: str) -> str:
    """Normalise a seed into the runtime form written to ``data/worlds/``.

    The seed may be hand-written YAML with comments; the installed copy is JSON,
    because the app will rewrite it whenever it stores a generated pack. Comments
    remain in the seed file for whoever maintains it.

    A seed that already carries provenance keeps it; one that does not is stamped
    as hand-compiled against its own prose, so it becomes recompilable later on
    the same footing as an imported world.
    """
    pack = read_world(seed_text)
    if pack.provenance is None:
        pack.provenance = Provenance.for_prose(pack.prose, compiler=HAND_COMPILED)
    return serialize_world(pack)


def summarize(pack: WorldPack) -> dict[str, Any]:
    """One Library row (R1.1) plus the staleness marker of R14.5.

    A pack may describe its emotional shelf entrance with ``card.promise`` and up
    to three ``card.possibilities``. These are presentation hints, not simulation
    rules, so older packs need no migration. Treat malformed hints as absent rather
    than making an otherwise playable world disappear from the Library.
    """
    t = pack.template
    raw_card = pack.raw_header.get("card")
    card = raw_card if isinstance(raw_card, dict) else {}
    raw_promise = card.get("promise")
    promise = raw_promise.strip() if isinstance(raw_promise, str) else ""
    raw_possibilities = card.get("possibilities")
    possibilities = (
        [
            item.strip()
            for item in raw_possibilities
            if isinstance(item, str) and item.strip()
        ][:3]
        if isinstance(raw_possibilities, list)
        else []
    )
    return {
        "worldId": t.id,
        "title": t.title,
        "version": t.version,
        "language": t.language,
        "lineage": t.lineage,
        "clockUnit": t.clock_unit,
        "styles": [s.label for s in t.styles],
        "panelCount": len(t.panels),
        "openingGroups": len(t.opening),
        "cardPromise": promise,
        "cardPossibilities": possibilities,
        "capabilityPacks": len(pack.capability_packs),
        "widgetSpecs": len(pack.widget_specs),
        "stale": pack.is_stale(),
        "stalenessNote": pack.staleness_note(),
        "improvable": pack.is_improvable(),
    }


__all__ = [
    "CONTRACT",
    "COMPILER_VERSION",
    "HAND_COMPILED",
    "ContractTooNew",
    "Provenance",
    "TemplateError",
    "WorldError",
    "WorldPack",
    "install_seed",
    "prose_digest",
    "read_world",
    "serialize_world",
    "summarize",
]
