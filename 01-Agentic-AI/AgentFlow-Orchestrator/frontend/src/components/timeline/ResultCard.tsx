import EvaluationBadge from './EvaluationBadge'
import MarkdownReport from './MarkdownReport'
import type { Execution } from '../../types'

interface Props {
  execution: Execution
}

const STATUS_STYLE: Record<string, string> = {
  completed: 'bg-green-100 text-green-800',
  failed: 'bg-red-100 text-red-800',
  cancelled: 'bg-gray-100 text-gray-600',
}

function ResultCard({ execution }: Props) {
  const evaluation = execution.result?.evaluation as
    | { success: boolean; score: number; criteria?: Record<string, number>; issues?: string[] }
    | undefined
  const outputs = (execution.result?.outputs as Record<string, { response?: string }>) || {}

  return (
    <div className="bg-white rounded-lg shadow p-6 border border-gray-100">
      <div className="flex items-center justify-between mb-3">
        <h3 className="font-semibold text-gray-800">Result</h3>
        <span className={`px-2 py-0.5 rounded-full text-xs font-medium ${STATUS_STYLE[execution.status] || 'bg-gray-100 text-gray-800'}`}>
          {execution.status}
        </span>
      </div>

      {execution.error && (
        <div className="mb-3 p-3 bg-red-50 border border-red-200 rounded text-sm text-red-700">{execution.error}</div>
      )}

      {Object.entries(outputs).map(([agentId, output]) => (
        <div key={agentId} className="mb-3 last:mb-0">
          <p className="text-xs font-medium text-gray-500 mb-1">{agentId}</p>
          {output.response ? <MarkdownReport content={output.response} /> : null}
        </div>
      ))}

      <div className="flex gap-4 text-xs text-gray-500 mt-3">
        <span>{execution.total_tool_calls} tool calls</span>
        {execution.total_cost != null && <span>${execution.total_cost.toFixed(3)}</span>}
      </div>

      {evaluation && (
        <div className="mt-4">
          <EvaluationBadge evaluation={evaluation} />
        </div>
      )}
    </div>
  )
}

export default ResultCard
