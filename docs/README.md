# Endless Worlds — documentation

Endless Worlds is an external Kiro Crew app: a text life-simulation
where a player lives out one life at a time inside a world, and an LLM
**narrator** writes each turn. This tree records **why the app is built the way
it is** — the design decisions and the invariants that keep them true — in the
same change-control style Kiro Crew uses for its own subsystems.

## How to use these docs

- **Read the spec for the subsystem you are about to change before you change
  it**, and update that spec in the same commit when you change what it
  documents. A spec that disagrees with the code is worse than no spec.
- Specs describe **current** behavior in present tense. No changelog lines, no
  "previously / used to / we now" narration, no PR or commit markers — git holds
  that history.
- Every load-bearing claim names the **enforcing function** and the **pinning
  test**, so the next reader can verify it against the code instead of trusting
  prose. Where a test pins a number, the spec names the test rather than copying
  the number (a copied constant goes stale silently).

## Map

| Doc | What it covers |
|---|---|
| [architecture.md](architecture.md) | How the pieces fit: the two agents, the backend split (HTTP surface vs MCP server), the data flow of one turn, and the app-wide invariants every module leans on. |
| [modules/README.md](modules/README.md) | One spec per subsystem — the on-demand load target when you touch that subsystem. |
| [conventions.md](conventions.md) | Cross-cutting rules every module obeys: English-only code, content in language-keyed data files, the prompt-injection discipline for player text, and the test disciplines the specs rely on. |
| [design/README.md](design/README.md) | Design notes and the product roadmap — planning artifacts, not change-control specs. Where a decision was argued, not where its current contract lives. |

## The one-sentence architecture

A single Python backend exposes a **player-facing HTTP surface** (called by the
SPA) and a **separate agent-facing MCP server**; two app-owned agents — a
**narrator** that lives one turn at a time and a **worldsmith** that compiles a
pasted rulebook into a world — drive it, and both processes operate on the same
on-disk data directory. See [architecture.md](architecture.md).
