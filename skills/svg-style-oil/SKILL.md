# Oil (matte impasto) — dragged brushstrokes, canvas tooth, NO gloss

The style for weighty, material, dramatic pages: battle aftermath, stone halls,
storm light, harvest fields, portraits of hard lives. Read
`../svg-style-core/SKILL.md` first — solid shapes come before any filter.

## The look

Thick opaque paint dragged in visible directional strokes; colors mixing at the
boundaries where strokes pull each other; a faint canvas texture underneath.
MATTE, always: this style must never shine. Do NOT use `feSpecularLighting` or
any specular/gloss pass — reflections read as plastic and dominate the scene
instead of serving it. Light lives in the paint: the lit side of an object is a
lighter, warmer MIX of its own color, the shadow side darker and cooler.

## Composition rules (before the filter)

- Fully opaque fills (oil is opaque, unlike watercolor) in rich, saturated,
  layered color families.
- Build objects from stacked stroke-like shapes: a foliage mass is 3–5
  overlapping blobs from shadowed to sunlit green; a wall is 2–3 broad tone
  bands, not one flat fill.
- Commit to one light direction and paint it into every fill pair (lit/shadow).

## The filter recipe (ranges — tune by eye, never copy blindly)

```xml
<filter id="oil" x="-8%" y="-8%" width="116%" height="116%">
  <!-- brush noise: X/Y baseFrequency asymmetry stretches strokes along a
       direction — 0.02 0.05 gives horizontal drag; swap to 0.05 0.02 for
       vertical strokes; 0.01–0.03 vs 0.04–0.08 is the useful band.
       numOctaves 2–4; vary seed per page. -->
  <feTurbulence type="fractalNoise" baseFrequency="0.02 0.05" numOctaves="3" seed="7" result="noise"/>
  <!-- paint drag: scale 10–18 (10 = tight strokes, 18 = bravura; past ~22
       silhouettes smear). -->
  <feDisplacementMap in="SourceGraphic" in2="noise" scale="15" xChannelSelector="R" yChannelSelector="G" result="disp"/>
  <!-- wet-mix softening at boundaries: stdDeviation 0.4–0.8 only -->
  <feGaussianBlur in="disp" stdDeviation="0.5" result="soft"/>
  <!-- canvas tooth: faint DARK specks clipped to the paint, alpha 0.08–0.18.
       This is the whole texture pass — no lighting, no highlights. -->
  <feColorMatrix in="noise" type="matrix"
      values="0 0 0 0 0  0 0 0 0 0  0 0 0 0 0  0 0 0 0.13 0" result="tooth"/>
  <feComposite in="tooth" in2="soft" operator="in" result="toothclip"/>
  <feMerge><feMergeNode in="soft"/><feMergeNode in="toothclip"/></feMerge>
</filter>
```

Apply to the whole scene group. Crisp subjects (a face, lettering) go in an
unfiltered sibling group or one with scale 6–10.

## Pattern-based motifs: mostly hands off

A motif built on pattern or geometric repetition keeps its precision — crisp
edges and exact rhythm ARE its beauty, and paint-drag displacement destroys
them. Express oil there through PALETTE (rich, saturated, layered hues) with NO
filter — or, when a hint of material is genuinely earned, the very lowest
values: scale 4–8, tooth alpha ≤ 0.08, no blur.

## Judging the preview

- GOOD: stroke direction is visible in broad areas, boundaries mix like dragged
  paint, canvas tooth is felt rather than seen, nothing shines.
- Looks like flat vector: raise scale toward 18, or exaggerate the X/Y frequency
  asymmetry for longer strokes.
- Smearing: lower scale below 12; check that key silhouettes survived.
- Any glossy/reflective patch: you added a lighting pass — remove it. Matte is
  the contract, not a preference.

## Notes

- Same hard rules as all backdrop art: filter in `<defs>`, `#id` references
  only, no external resources.
- Stroke direction can carry meaning: horizontal drag calms, vertical drag
  monumentalizes, diagonal unsettles. Choose it from the page's mood.
