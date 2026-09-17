import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { cleanCell, extractNumber, parseMarkdownSegments } from '../../utils/markdownTables'

interface Props {
  content: string
}

const CHART_COLOR = '#2563eb'

function TableWithChart({ headers, rows }: { headers: string[]; rows: string[][] }) {
  const valueColIdx = headers.length - 1
  const labelColIdx = headers.length >= 2 ? headers.length - 2 : 0

  const chartData = rows
    .map((row) => {
      const value = extractNumber(row[valueColIdx] ?? '')
      const label = cleanCell(row[labelColIdx] ?? '')
      return value === null ? null : { label, value }
    })
    .filter((d): d is { label: string; value: number } => d !== null)

  const isChartable = chartData.length >= 2 && chartData.length <= 15 && chartData.length === rows.length

  return (
    <div className="my-4">
      <div className="overflow-x-auto rounded-lg border border-gray-200">
        <table className="min-w-full text-sm">
          <thead className="bg-gray-50">
            <tr>
              {headers.map((h, i) => (
                <th key={i} className="px-3 py-2 text-left font-semibold text-gray-700 border-b border-gray-200">
                  {cleanCell(h)}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((row, ri) => (
              <tr key={ri} className={ri % 2 === 0 ? 'bg-white' : 'bg-gray-50/50'}>
                {row.map((cell, ci) => (
                  <td key={ci} className="px-3 py-2 text-gray-700 border-b border-gray-100">
                    {cleanCell(cell)}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {isChartable && (
        <div className="mt-2 h-56">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={chartData} layout="vertical" margin={{ left: 8, right: 16, top: 4, bottom: 4 }}>
              <CartesianGrid strokeDasharray="3 3" horizontal={false} />
              <XAxis type="number" tick={{ fontSize: 11 }} />
              <YAxis type="category" dataKey="label" width={120} tick={{ fontSize: 11 }} />
              <Tooltip />
              <Bar dataKey="value" fill={CHART_COLOR} radius={[0, 3, 3, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </div>
      )}
    </div>
  )
}

/** Renders markdown text with GFM tables auto-charted (bar chart) when the data allows it. */
function MarkdownReport({ content }: Props) {
  const segments = parseMarkdownSegments(content)

  return (
    <div>
      {segments.map((segment, i) =>
        segment.kind === 'table' ? (
          <TableWithChart key={i} headers={segment.headers} rows={segment.rows} />
        ) : segment.content.trim() ? (
          <div key={i} className="prose prose-sm max-w-none prose-headings:mt-4 prose-headings:mb-2 prose-p:my-1.5">
            <ReactMarkdown remarkPlugins={[remarkGfm]}>{segment.content}</ReactMarkdown>
          </div>
        ) : null
      )}
    </div>
  )
}

export default MarkdownReport
