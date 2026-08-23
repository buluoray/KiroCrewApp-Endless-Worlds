# Watercolor — transparent washes, bleeding edges, paper grain

The style for lyrical, atmospheric, emotional pages: memory, weather, gardens,
rivers, dawn/dusk, tenderness, loss. Read `../svg-style-core/SKILL.md` first —
solid shapes come before any filter.

## The look

Transparent overlapping color washes; edges that bleed and wobble like wet paint
on paper; slightly darker edge lines where pigment settled; visible paper tooth.
Colors stay luminous because white paper glows through them.

## Composition rules (before the filter)

- Fill shapes at 0.75–0.92 opacity over a warm paper-white base (`#f6f2e9`-ish),
  so overlaps darken naturally like layered washes.
- Prefer a few LARGE washes (sky, ground, water) plus a small number of solid
  subjects; watercolor dies under clutter.
- Leave some paper untouched — highlights in watercolor are UNPAINTED paper, not
  white strokes.

## The filter recipe (ranges — tune by eye, never copy blindly)

```xml
<filter id="wc" x="-12%" y="-12%" width="124%" height="124%">
  <!-- soften the vector edges like wet paint: stdDeviation 3–6
       (3 = tight controlled wash, 6 = very loose and wet) -->
  <feGaussianBlur in="SourceGraphic" stdDeviation="4" result="blur"/>
  <!-- water movement: baseFrequency 0.01–0.02 (lower = broader billows),
       numOctaves 2–4; vary seed per page so no two pages share water marks -->
  <feTurbulence type="fractalNoise" baseFrequency="0.015" numOctaves="3" seed="4" result="wn"/>
  <!-- bleed: scale 18–30 (18 = damp paper, 30 = soaked; past ~35 objects dissolve) -->
  <feDisplacementMap in="blur" in2="wn" scale="26" xChannelSelector="R" yChannelSelector="G" result="disp"/>
  <!-- pigment settling at edges: alpha slope 1.3–1.8 with intercept -0.08 to -0.15;
       stronger values harden the dried-edge line -->
  <feColorMatrix in="disp" type="matrix"
      values="1 0 0 0 0  0 1 0 0 0  0 0 1 0 0  0 0 0 1.6 -0.12" result="edge"/>
  <!-- paper tooth: high-frequency grain clipped to the paint, alpha 0.2–0.45 -->
  <feTurbulence type="fractalNoise" baseFrequency="0.5" numOctaves="2" seed="9" result="paper"/>
  <feColorMatrix in="paper" type="matrix"
      values="0 0 0 0 0  0 0 0 0 0  0 0 0 0 0  0 0 0 0.35 0" result="papera"/>
  <feComposite in="papera" in2="edge" operator="in" result="grain"/>
  <feMerge><feMergeNode in="edge"/><feMergeNode in="grain"/></feMerge>
</filter>
```

Apply to the whole scene group (`<g filter="url(#wc)">`). For a subject that must
stay crisp (a face, an emblem), draw it in a SEPARATE group outside the filtered
one, or give it its own filter instance with a gentler scale (8–14).

## Pattern-based motifs: mostly hands off

A motif built on pattern or geometric repetition keeps its precision — crisp
edges and exact rhythm ARE its beauty, and displacement destroys them. Express
watercolor there through PALETTE (transparent overlapping tints, paper-white
ground) with NO filter — or, when a hint of wash is genuinely earned, the very
lowest values: blur ≤ 1.5, scale 4–8, no paper grain over fine lines.

## Judging the preview

- GOOD: edges wobble organically, washes melt into each other, grain reads as
  paper, the subject still reads at a glance.
- Too tame (looks like blurred vector): raise displacement scale, or lower
  baseFrequency for broader billows.
- Dissolving (subject unrecognizable): lower scale below 22, or raise
  baseFrequency slightly so distortion is finer.
- Muddy: your underlying fills are too dark or too many hues — fix the paint,
  not the filter.

## Notes

- The filter must stay inside the SVG (`<defs>`), reference only `#id`s, and use
  no external resources — same hard rules as all backdrop art.
- SMIL/CSS animation composes fine over the filtered group; animate a separate
  overlay group, not the filter parameters.
