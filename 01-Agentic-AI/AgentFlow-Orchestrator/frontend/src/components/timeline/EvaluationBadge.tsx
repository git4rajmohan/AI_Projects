interface Props {
  evaluation: { success: boolean; score: number; criteria?: Record<string, number>; issues?: string[] }
}

function EvaluationBadge({ evaluation }: Props) {
  return (
    <div className={`rounded-lg p-3 text-sm ${evaluation.success ? 'bg-green-50 border border-green-200' : 'bg-yellow-50 border border-yellow-200'}`}>
      <div className="flex items-center justify-between">
        <span className="font-medium">{evaluation.success ? '✅ Evaluation passed' : '⚠️ Evaluation below threshold'}</span>
        <span className="text-gray-600">Score: {(evaluation.score * 100).toFixed(0)}%</span>
      </div>
      {evaluation.criteria && Object.keys(evaluation.criteria).length > 0 && (
        <div className="flex gap-3 mt-2 text-xs text-gray-500">
          {Object.entries(evaluation.criteria).map(([k, v]) => (
            <span key={k}>{k}: {(v * 100).toFixed(0)}%</span>
          ))}
        </div>
      )}
      {evaluation.issues && evaluation.issues.length > 0 && (
        <ul className="mt-2 text-xs text-gray-600 list-disc list-inside">
          {evaluation.issues.map((issue, i) => (
            <li key={i}>{issue}</li>
          ))}
        </ul>
      )}
    </div>
  )
}

export default EvaluationBadge
