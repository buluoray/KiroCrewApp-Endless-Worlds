/**
 * Narration, cut into the blocks a reader sees as paragraphs.
 *
 * The host's markdown renderer wraps every block it emits in a wrapper of its own
 * and styles its `<p>` with its own margins and line height, so a stylesheet rule on
 * `p` cannot say "a gap between paragraphs": every paragraph is the last child of its
 * own wrapper, and the gap rule never matches. The page read as one wall of text. So
 * the app owns the block boundaries: the text is split here, each block is rendered on
 * its own, and the gap is a rule between OUR blocks, which the host cannot reshape.
 *
 * Two shapes reach this function, and both mean "new paragraph":
 *
 * - a blank line, which is what the narrator is asked to write;
 * - a single line break between two lines of ordinary prose. A novel has no soft
 *   line breaks, so a line of prose on its own line is a paragraph of its own.
 *
 * Markdown structure is kept whole: a list, a quote, a table or a fenced block is one
 * block, because cutting it at each line would break the markup it is written in.
 *
 * Pure and DOM-free so it can be tested without a browser (`paragraphs.test.ts`).
 */

/** `text` is a paragraph of prose; `head` a markdown heading; `block` any other
 *  markdown structure (list, quote, table, fenced code), kept as written. */
export type ParagraphKind = 'text' | 'head' | 'block'

export interface Paragraph {
  kind: ParagraphKind
  text: string
}

const FENCE = /^\s{0,3}(```|~~~)/
const HEADING = /^\s{0,3}#{1,6}\s/
/** A line that belongs to markdown structure rather than to running prose: a list
 *  item, a quote, a table row or a thematic break. An indented line is NOT counted
 *  as code: a narrator that indents its paragraphs by hand means an indent, and
 *  narration has no use for an indented code block. */
const STRUCTURE = /^\s{0,3}([-*+]\s|\d{1,9}[.)]\s|>|\||(-{3,}|\*{3,}|_{3,})\s*$)/

function isStructural(line: string): boolean {
  return STRUCTURE.test(line) || HEADING.test(line)
}

/** Cut the text at blank lines, never inside a fenced block. */
function blankLineBlocks(text: string): string[][] {
  const blocks: string[][] = []
  let cur: string[] = []
  let fenced = false
  for (const line of text.replace(/\r\n?/g, '\n').split('\n')) {
    if (FENCE.test(line)) fenced = !fenced
    if (!fenced && line.trim() === '') {
      if (cur.length) blocks.push(cur)
      cur = []
      continue
    }
    cur.push(line)
  }
  if (cur.length) blocks.push(cur)
  return blocks
}

export function splitParagraphs(text: string): Paragraph[] {
  const out: Paragraph[] = []
  for (const lines of blankLineBlocks(text)) {
    const first = lines[0] ?? ''
    if (FENCE.test(first)) {
      out.push({ kind: 'block', text: lines.join('\n') })
      continue
    }
    if (!lines.some(isStructural)) {
      // Ordinary prose: every line is a paragraph. Leading spaces are dropped, since
      // the paragraph's own indent is the stylesheet's job and a typed one would
      // stack on top of it (four would even turn the line into a code block).
      // shortcut: verse written with single line breaks also splits into paragraphs;
      // if the narrator starts writing poems, mark them as a quote block instead.
      for (const line of lines) out.push({ kind: 'text', text: line.trim() })
      continue
    }
    // Mixed: a heading line stands alone; a run of structure lines stays together;
    // a run of prose lines between them splits per line like the case above.
    let run: string[] = []
    const flush = () => {
      if (run.length) out.push({ kind: 'block', text: run.join('\n') })
      run = []
    }
    for (const line of lines) {
      if (HEADING.test(line)) {
        flush()
        out.push({ kind: 'head', text: line.trim() })
      } else if (isStructural(line) || (run.length && /^\s+\S/.test(line))) {
        // A structure line, or an indented continuation of the one above it.
        run.push(line)
      } else {
        flush()
        out.push({ kind: 'text', text: line.trim() })
      }
    }
    flush()
  }
  return out
}
