# Design notes and roadmap

These are **not** change-control specs. Unlike [`../modules/`](../modules/README.md)
— which describes current behavior in present tense — the documents here are
planning artifacts: a roadmap of what to build next, and the design reasoning
behind a subsystem. They may contain proposed-but-unbuilt ideas and historical
narration. When a decision here ships, its behavior belongs in the module spec
that owns it; this folder is where it was argued, not where its contract lives.

| Doc | What it is |
|---|---|
| [product-audit.md](product-audit.md) | Living roadmap of player-facing feature gaps, priorities (P0/P1/N-tiers), and what has shipped. Historically updated in place as items land. |
| [memory-graph-design.md](memory-graph-design.md) | The design doc behind the world-memory system (fact graph, echoes, keepsakes, star lenses). The shipped behavior is specified in [../modules/memory-graph.md](../modules/memory-graph.md) and [../modules/meaning-layer.md](../modules/meaning-layer.md). |
| [turn-feedback-spec.md](turn-feedback-spec.md) | The design of the per-turn feedback the narrator receives (density/attribution/restraint readings). The shipped behavior is specified in [../modules/character-creation.md](../modules/character-creation.md) (halo instruments) and [../modules/turn-loop.md](../modules/turn-loop.md). |

