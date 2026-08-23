# Minimal — restraint, silhouette, and negative space (no texture filter)

The style for austere, formal, or symbol-heavy pages: rituals, thrones, codes and
laws, cosmic scale, silence. Read `../svg-style-core/SKILL.md` first — its
solidify/depth/light principles still apply; this style simply expresses them
through restraint instead of texture.

## The look

Few colors, large flat or gently-gradient shapes, strong silhouettes, generous
empty space. Beauty comes from PROPORTION and PLACEMENT, not surface effects.
This is not "unfinished vector" — it is deliberate flatness, like a woodcut
poster or a folded-paper landscape.

## Rules

- Palette of 3–5 related hues plus one accent, period. If two adjacent shapes
  are close in value, merge them or push one — never add an outline.
- Every object is a clean solid silhouette; test each: would it still read as a
  black paper cutout? If not, simplify its shape until it does.
- Negative space is a subject: let at least a third of the canvas rest. Place
  the dominant image off-center (rule of thirds) and let emptiness answer it.
- Depth by 2–4 flat distance planes (far = lightest/coolest), not by texture.
- One gradient per large area at most (sky, water); everything else flat.
- Edge-crop the composition: let big shapes run off the canvas edges so the
  frame feels like a window, not a diagram.
- No filters needed. At most: a single soft vignette or a whisper of grain
  (feTurbulence alpha ≤ 0.06) if the flat fields band visibly on gradients.

## Judging the preview

- GOOD: reads instantly at thumbnail size; feels composed, calm, intentional.
- Feels empty/cheap: the silhouettes are weak — improve the SHAPES (more
  characterful outlines, better overlaps), never add texture to compensate.
- Feels cluttered: remove elements until only the dominant image and one or two
  supporting masses remain.

## Notes

- Same hard rules as all backdrop art: everything inline, `#id` references only.
- Minimal pairs beautifully with subtle SMIL/CSS motion (a drifting band, a
  slow pulse) because nothing competes with it.
