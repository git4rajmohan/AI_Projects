import { useState } from 'react'
import { useWorkspaceStore } from '../../store/workspaceStore'
import type { Approval } from '../../types'

interface Props {
  approval: Approval
}

function ApprovalInlineCard({ approval }: Props) {
  const { resolveApproval } = useWorkspaceStore()
  const [acting, setActing] = useState(false)

  const isPending = approval.status === 'pending'

  const decide = async (decision: 'approve' | 'reject') => {
    setActing(true)
    try {
      await resolveApproval(approval.id, decision)
    } finally {
      setActing(false)
    }
  }

  return (
    <div className="bg-orange-50 border border-orange-200 rounded-lg p-4">
      <div className="flex items-start justify-between gap-4">
        <div className="flex-1">
          <div className="flex items-center gap-2 mb-1">
            <span className="px-2 py-0.5 rounded text-xs font-medium bg-orange-200 text-orange-900">
              Approval required
            </span>
            <span className="text-xs text-gray-500">{approval.approval_type}</span>
          </div>
          {approval.context && Object.keys(approval.context).length > 0 && (
            <pre className="mt-1 p-2 bg-white border border-gray-200 rounded text-xs overflow-x-auto">
              {JSON.stringify(approval.context, null, 2)}
            </pre>
          )}
        </div>
        {isPending ? (
          <div className="flex gap-2 shrink-0">
            <button
              onClick={() => decide('approve')}
              disabled={acting}
              className="px-3 py-1.5 bg-green-600 text-white rounded hover:bg-green-700 disabled:opacity-50 text-sm"
            >
              Approve
            </button>
            <button
              onClick={() => decide('reject')}
              disabled={acting}
              className="px-3 py-1.5 bg-red-600 text-white rounded hover:bg-red-700 disabled:opacity-50 text-sm"
            >
              Reject
            </button>
          </div>
        ) : (
          <span
            className={`px-2 py-1 rounded text-xs font-medium shrink-0 ${
              approval.status === 'approved' ? 'bg-green-100 text-green-800' : 'bg-red-100 text-red-800'
            }`}
          >
            {approval.status}
          </span>
        )}
      </div>
    </div>
  )
}

export default ApprovalInlineCard
