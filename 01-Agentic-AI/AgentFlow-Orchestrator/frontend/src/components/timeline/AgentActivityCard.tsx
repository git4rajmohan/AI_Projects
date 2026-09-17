interface Props {
  name: string
  status: string
  toolCalls: number
  durationMs: number | null
  error: string | null
}

const STATUS_STYLE: Record<string, { dot: string; label: string }> = {
  running: { dot: 'bg-blue-500 animate-pulse', label: 'Running' },
  completed: { dot: 'bg-green-500', label: 'Completed' },
  failed: { dot: 'bg-red-500', label: 'Failed' },
}

function AgentActivityCard({ name, status, toolCalls, durationMs, error }: Props) {
  const style = STATUS_STYLE[status] || { dot: 'bg-gray-400', label: status }

  return (
    <div className="bg-white rounded-lg shadow-sm border border-gray-100 px-4 py-3 flex items-center justify-between">
      <div className="flex items-center gap-3">
        <span className={`h-2.5 w-2.5 rounded-full ${style.dot}`} />
        <span className="font-medium text-gray-800 text-sm">{name}</span>
        <span className="text-xs text-gray-400">{style.label}</span>
      </div>
      <div className="flex items-center gap-3 text-xs text-gray-500">
        {toolCalls > 0 && <span>{toolCalls} tool call{toolCalls === 1 ? '' : 's'}</span>}
        {durationMs !== null && <span>{(durationMs / 1000).toFixed(1)}s</span>}
      </div>
      {error && <p className="text-xs text-red-600 mt-1 basis-full">{error}</p>}
    </div>
  )
}

export default AgentActivityCard
