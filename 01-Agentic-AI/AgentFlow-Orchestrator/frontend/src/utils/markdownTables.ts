export interface TableSegment {
  kind: 'table'
  headers: string[]
  rows: string[][]
}

export interface TextSegment {
  kind: 'text'
  content: string
}

export type MarkdownSegment = TableSegment | TextSegment

const TABLE_ROW_RE = /^\s*\|(.+)\|\s*$/
const SEPARATOR_RE = /^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$/

function splitRow(line: string): string[] {
  return line
    .trim()
    .replace(/^\|/, '')
    .replace(/\|$/, '')
    .split('|')
    .map((cell) => cell.trim())
}

/** Split a markdown document into alternating text and GFM-table segments. */
export function parseMarkdownSegments(markdown: string): MarkdownSegment[] {
  const lines = markdown.split('\n')
  const segments: MarkdownSegment[] = []
  let textBuffer: string[] = []

  const flushText = () => {
    if (textBuffer.length > 0) {
      segments.push({ kind: 'text', content: textBuffer.join('\n') })
      textBuffer = []
    }
  }

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i]
    const next = lines[i + 1]
    if (TABLE_ROW_RE.test(line) && next !== undefined && SEPARATOR_RE.test(next)) {
      flushText()
      const headers = splitRow(line)
      let j = i + 2
      const rows: string[][] = []
      while (j < lines.length && TABLE_ROW_RE.test(lines[j])) {
        rows.push(splitRow(lines[j]))
        j++
      }
      segments.push({ kind: 'table', headers, rows })
      i = j - 1
    } else {
      textBuffer.push(line)
    }
  }
  flushText()
  return segments
}

/** Strip markdown emphasis markers so cell text is chart/display friendly. */
export function cleanCell(cell: string): string {
  return cell.replace(/\*\*/g, '').replace(/`/g, '').trim()
}

/** Extract a numeric value from a cell like "**$3,842,869**" or "152 (≈ 6 %)". */
export function extractNumber(cell: string): number | null {
  const match = cleanCell(cell).match(/-?[\d,]+\.?\d*/)
  if (!match) return null
  const num = parseFloat(match[0].replace(/,/g, ''))
  return Number.isFinite(num) ? num : null
}
