import { useState } from 'react'
import { useWorkspaceStore } from '../../store/workspaceStore'
import type { Plan, AgentSpec } from '../../types'

interface Props {
  plan: Plan
}

function PlanCard({ plan }: Props) {
  const { approvePlan, rejectPlan } = useWorkspaceStore()
  const [acting, setActing] = useState(false)

  const planData = plan.plan_data as Record<string, unknown>
  // Skill-reuse plans store a SkillSpec (agents = string IDs); LLM plans store full AgentSpecs.
  const agents: AgentSpec[] = (((planData.agents as (AgentSpec | string)[]) || []).map((a) =>
    typeof a === 'string'
      ? ({ id: a, name: a, description: '', goal: '', tools: [] } as AgentSpec)
      : { ...a, tools: a.tools || [] }
  ))
  const matchedSkills = plan.matched_skills || []
  const isApproved = plan.status === 'approved' || plan.status === 'executing' || plan.status === 'completed'
  const isRejected = plan.status === 'rejected'
  const isPending = !isApproved && !isRejected

  const act = async (fn: () => Promise<void>) => {
    setActing(true)
    try {
      await fn()
    } finally {
      setActing(false)
    }
  }

  return (
    <div className="bg-white rounded-lg shadow p-6 border border-gray-100">
      <div className="flex items-center justify-between mb-3">
        <h3 className="font-semibold text-gray-800">Plan</h3>
        <span
          className={`px-2 py-0.5 rounded-full text-xs font-medium ${
            isApproved
              ? 'bg-green-100 text-green-800'
              : isRejected
                ? 'bg-red-100 text-red-800'
                : 'bg-blue-100 text-blue-800'
          }`}
        >
          {plan.status}
        </span>
      </div>

      <p className="text-gray-800 mb-1">{plan.objective}</p>
      {plan.summary && <p className="text-sm text-gray-500 mb-3">{plan.summary}</p>}

      {matchedSkills.length > 0 && (
        <div className="mb-3 text-sm">
          {matchedSkills.map((s, i) => (
            <span key={i} className="text-blue-600 mr-3">
              {s.skill_name} ({(s.score * 100).toFixed(0)}% match)
            </span>
          ))}
        </div>
      )}

      {agents.length > 0 && (
        <div className="space-y-2 mb-4">
          {agents.map((agent, i) => (
            <div key={agent.id || i} className="border border-gray-200 rounded p-3 text-sm">
              <div className="flex items-center justify-between">
                <span className="font-medium text-gray-800">{agent.name}</span>
                {agent.requires_human_approval && (
                  <span className="px-2 py-0.5 bg-orange-100 text-orange-800 rounded text-xs">Needs Approval</span>
                )}
              </div>
              <p className="text-gray-600 mt-1">{agent.goal}</p>
              {agent.tools.length > 0 && (
                <div className="flex flex-wrap gap-1 mt-2">
                  {agent.tools.map((tool) => (
                    <span key={tool} className="px-2 py-0.5 bg-gray-100 text-gray-600 rounded text-xs">
                      {tool}
                    </span>
                  ))}
                </div>
              )}
            </div>
          ))}
        </div>
      )}

      <div className="flex gap-4 text-sm text-gray-500 mb-4">
        <span>Est. cost: ${plan.estimated_cost.toFixed(2)}</span>
        <span>Est. time: ~{Math.ceil(plan.estimated_duration_seconds / 60)} min</span>
      </div>

      {isPending && (
        <div className="flex gap-3">
          <button
            onClick={() => act(() => approvePlan(plan.id))}
            disabled={acting}
            className="px-4 py-2 bg-green-600 text-white rounded-lg text-sm font-medium hover:bg-green-700 disabled:opacity-50"
          >
            {acting ? 'Processing...' : 'Approve & Execute'}
          </button>
          <button
            onClick={() => act(() => rejectPlan(plan.id))}
            disabled={acting}
            className="px-4 py-2 bg-red-600 text-white rounded-lg text-sm font-medium hover:bg-red-700 disabled:opacity-50"
          >
            Reject
          </button>
        </div>
      )}
    </div>
  )
}

export default PlanCard
