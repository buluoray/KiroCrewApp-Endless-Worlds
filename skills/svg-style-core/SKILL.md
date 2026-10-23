# From sketch to solid painting — the core principles behind every painterly style

Shared foundation for the per-style skills (`svg-style-watercolor`, `svg-style-oil`,
`svg-style-minimal`). Read the style skill first; it will send you here. Everything
below applies to hand-drawn scene AND motif art in any painterly style. The hard
safety rules of your own contract (pure SVG, no scripts, no external resources,
inline everything) always win over anything here.

## Why weak scenes happen

A weak SVG scene is almost always a LINE DRAWING: black outlines around empty
shapes, floating circles and triangles as symbols, thin strokes standing in for
objects. The cure is not more detail — it is making every object a SOLID PAINTED
THING.

## The three principles

### 1. Solidify every object (the most important step)

Never define an object by a black outline. Build it from filled shapes of real
material color, stacked like paint:

- A tree is not a stick and a circle: it is a solid trunk shape (dark bark colors)
  carrying overlapping leaf CLUMPS — several filled blobs in different greens
  (shadowed olive, mid green, sunlit yellow-green), not one flat green disc.
- A structure is not crossed lines: imagine it as carved stone, woven bronze,
  colored glass — solid filled shapes with a material's own colors.
- Circles and triangles may stay ONLY as deliberate ornament integrated into a
  solid object (a rose window in a wall, a pennant on a mast), never as floating
  sketch symbols.

### 2. Give the background depth and texture

- Sky and water are never one flat rectangle: layer 2–4 gradient or blob bands,
  and let water mirror the sky's hue family (a lighter, blurrier echo of what
  stands above it).
- Ground is never one beige block: it is grass/bank/soil built from several
  overlapping tones of the same family.
- Distant elements are lighter, bluer/grayer, and simpler than near ones
  (atmospheric perspective); near elements are darker, warmer, more detailed.

### 3. One unified style, one light source

- Edges are defined by COLOR MEETING COLOR, not by outlines. If two objects read
  as one blob, separate them by value (light vs dark), not by a stroke.
- Pick ONE light direction for the whole page. Every solid object gets a lit side
  (lighter, warmer mix of its own color) and a shadow side (darker, cooler mix).
  Light lives in the PAINT COLORS themselves — never in gloss or specular
  highlights, which read as cheap plastic.
- The style's filter (see the style skill) is a finishing pass over solid
  composition. A filter cannot rescue a line drawing; it can only make a solid
  painting breathe.

## Bleed past the frame

A displacement filter moves every pixel by up to its `scale`. At the canvas edge
it pulls in pixels from OUTSIDE your shapes, so a scene whose washes stop at
`0` and `800` gets a ragged strip of bare base paper along the frame — a pale torn
border around the whole page. Every painterly page audited had it. The page is a
background, never a sheet of paper on a table: no torn edge, no paper margin.

Paint the filtered scene past the canvas by at least the largest displacement
`scale` you use, on every side. The simplest way: wrap the filtered group's
CONTENT (not the group itself) in one transform that grows it by that margin —

```xml
<g filter="url(#wc)">
  <!-- desktop 800×600, scale 22: grow by 22 on each side -->
  <g transform="translate(-22 -22) scale(1.055 1.0733)">
    …the whole scene…
  </g>
</g>
```

(`scale` x = (W + 2·pad) / W, y = (H + 2·pad) / H; mobile 450×900 with pad 22 is
`scale(1.0978 1.0489)`.) Drawing the edge shapes out to `-pad` and `W + pad`
yourself works too. Check the four edges of every preview; any light strip there
means a shape still stops at the frame.

## The look-and-adjust loop

Filter numbers in the style skills are RANGES, not constants. The loop is:

1. Compose solid shapes first (principles above), apply the style filter with
   mid-range parameters.
2. `endless_submit_backdrop_draft`, then READ every preview PNG as an image.
3. Judge like a painter, not a validator: Is the texture visible but serving the
   scene? Are edges painterly without objects dissolving? Did any face/figure or
   load-bearing silhouette get destroyed by displacement?
4. Tune within the ranges in your ONE revision — texture too weak: raise the
   displacement scale or grain alpha; objects dissolving: lower scale, raise
   detail frequency; too dark/muddy: lighten the underlying fills, not the filter.
5. Commit. Do not spend the revision on microscopic differences — one decisive
   correction beats two timid ones.
