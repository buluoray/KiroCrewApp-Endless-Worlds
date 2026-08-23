# Fate checks — giving a world a die the narrator cannot re-roll

**Status: design, not built.** Nothing in this document ships yet. The one piece of
it that has landed is defensive rather than new: gain-fed systems can no longer
collide on a shared path segment (see the gain-identity invariant in
[../modules/systems.md](../modules/systems.md)), which the design below leans on
when a check reads a number.

## The gap this closes

Every place the framework knows a model will drift, it puts a structure in the way,
and the structures are the reason a life here does not feel like a chat transcript:

| The model would… | What stops it |
|---|---|
| inflate a total it restates each turn | `systems` recomputes from the prior committed state |
| use setting it should not know yet | a `chapter` behind a `when` is refused, not discouraged |
| let the player pick what the world decides | an opening group marked `random` rejects a submitted value |
| forget what happened forty turns ago | the memory graph re-surfaces it as a candidate |
| retract a reached achievement | `state.milestones` is monotonic and app-owned |

Probability is the one remaining bias with no counterweight. A rulebook that says a
breakthrough succeeds one time in three currently survives cleaning as **prose** —
the compiler is told to keep the fiction and drop the math
(`compile.CLEANING_CONTRACT`) — so the odds become the narrator's judgement. An LLM
asked to honour long odds against the protagonist it is writing for does not hold
the line, and the anti-halo instruments in `halo.py` deliberately measure rather
than enforce ("the app measures, the narrator adjusts"), so nothing catches it.
The result is a world whose stated risks are decorative.

`opening.roll` already proves the opposite feels good: the app draws the value, the
player cannot touch it, and finding out at birth is one of the better moments the
game has. The design below is that contract extended past the first turn — and the
reason to build it is not "worlds should have dice", it is that **a world whose
odds are real is the only remaining source of surprise the narrator cannot author.**

## Shape: four decisions, split across two axes

The obvious framings — "declared by the world" versus "the agent decides", and
"binding" versus "advisory" — are each one axis of a two-axis question. Who may
*ask* for a check is not the same question as whether the answer *counts*.

### 1. Invocation is free, like `lore`

`endless_roll` is a tool the narrator may call whenever a moment deserves it. No
world-pack declaration is required to reach it.

Why: every other narrator tool is self-directed (`endless_paint_backdrop`,
`endless_mount_scene`, the memory block), so a permission-gated tool would be the
first of its kind. More substantively, the best moments for a check are emergent —
a player doing something the world's author never imagined — and gating on a
declaration locks fate inside compile-time imagination.

### 2. Declaration remains, as enhancement

A world MAY declare `checks` in its header, exactly the way it declares `systems`:

- odds may reference a `state.…` path, so accumulated experience can move a
  breakthrough's chance — the closed loop with `systems` that free invocation
  cannot give (the app owns the number *and* the die).
- like a system, a declared check is **inert until fed**: declaring one obliges the
  author to add a prose rule telling the narrator when the fiction calls for it.

This mirrors `lore` (free keyword trigger) alongside `chapters` (declared state
gate) — one concept, two mechanisms, neither a prerequisite for the other.

### 3. The result binds; advisory is worse than nothing

A check's **valence** is not re-openable once drawn. The failure mode of an
advisory die is specific and bad: the model rolls a failure, judges that success
reads better, narrates success — and now the player *sees* that a check happened
and therefore trusts an outcome the model actually chose. That launders the bias
instead of correcting it, and it dismantles the only reason to build the feature.

Mechanically:

- **deterministic seeding** from `(runId, turn, key)`, so the same check re-drawn
  within a turn returns the same face. This is what kills re-roll-to-success, and
  it also keeps `endless_advance_turn` idempotent per `(runId, turn)` and the run
  rebuildable from its chronicle — a bare RNG in the commit path would break both.
- **the draw is recorded before it is returned**, into the chronicle and into
  `state.checks.<key>`, so panels, endings and milestones can read it. A narrator
  that talks around a failure still leaves the world's data saying *failed*, and
  the contradiction is visible rather than silent — the same treatment an
  unsourced gain gets today ("marked, not refused").
- **narration stays the narrator's.** The check decides whether the door opened.
  It never decides what is behind it.

### 4. Frustration is controlled by density and blast radius, not by softness

The concern this design has to answer is real: nobody wants their life to be a
losing streak, and "you accepted a harsh setting" is not a defence a player feels.
But the answer is not a die that can be overruled — it is a die that is rare,
generous, and cannot take away what a life already earned.

- **Named odds tiers, not raw percentages.** Guidance biases generous:
  *safe* ≈ 90 / *favoured* ≈ 75 / *even* 50 / *desperate* ≈ 30, with the desperate
  tier reserved for a moment the fiction itself frames as a gamble. Naming also
  keeps the machinery out of the prose: a page says *this was a desperate bet*,
  never *30%*.
- **Three-valued outcomes, not pass/fail.** *Succeeded* / *succeeded at a cost* /
  *turned aside*. The rule the guidance states outright: a turned-aside check must
  **change the direction**, never **delete progress**. Failing to climb the wall is
  not "you do not get in"; it is "you are halfway up when the old servant sees you
  — and he knew your mother." Fail-forward is what separates a memorable loss from
  a wasted turn.
- **Fateful frequency.** Checks belong at the `fateful` choices the UI already
  marks and renders specially — five or six in a whole life, not one a turn. A soft
  per-turn cap (≤1–2, in the spirit of the existing 12-gain cap) stops the life
  becoming a slot machine. At that density a loss is a scar the player remembers,
  not attrition.
- **What a check cannot reach.** Progress is already structurally protected:
  milestones never revert, `systems` clamp to a `floor`, and the lineage bridge
  means death is not total loss when there is an heir. A check can only decide
  *where the next stretch goes* — never *what a life has already become*.

Worth saying plainly, because it is counter-intuitive: a fair die is a *shock
absorber*, not an amplifier. Players forgive fate far more readily than they
forgive a narrator that seemed to single them out, which is exactly why a
table GM rolls in the open. Today every reversal is the narrator's fiat and the
player's resentment has nowhere to sit; a check that can be found in the chronicle
afterwards gives it somewhere to go — and makes "try again" a story rather than a
grievance.

## What is deliberately out

- **Arithmetic in the `when` language.** It stays call-free and expression-free;
  the check tool is a separate surface, not a new node in the interpreter.
- **A d20 in the UI.** No dice face, no percentage, no roll log the player browses.
  The visible artefact is the `fateful` choice's existing treatment.
- **Per-event probability tables compiled out of prose.** The cleaning contract
  still drops those. What changes is one sentence of its guidance: a stated chance
  becomes a *declared check* rather than discarded math.
- **Player-visible re-rolls, luck stats, or a spend-to-retry currency.** Any of
  them re-opens the outcome and voids §3.

## Open questions before implementation

1. Where the recorded result lives relative to the memory graph — a check is an
   event, and an event with a cause is what an echo forty turns later wants.
2. Whether a declared check may name a `systems` gain as its consequence, closing
   the loop the other way (a desperate bet that costs experience on a miss).
3. Whether the per-turn cap should be a refusal or a warning, given the app's
   general preference for fail-soft on enrichment and fail-hard on the thing the
   player acts through.
