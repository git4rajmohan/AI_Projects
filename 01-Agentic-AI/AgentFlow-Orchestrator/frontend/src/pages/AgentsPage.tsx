import { useState, useEffect } from 'react'
import { api } from '../services/api'

interface AgentInfo {
  id: string
  name: string
  description: string
  goal: string
  tools: string[]
  dependencies: string[]
  requires_human_approval: boolean
  max_iterations: number
  max_tool_calls: number
  timeout_seconds: number
}

function AgentsPage() {
  const [agents, setAgents] = useState<AgentInfo[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    loadAgents()
  }, [])

  const loadAgents = async () => {
    setLoading(true)
    try {
      const data = await api.listAgents()
      setAgents(data as AgentInfo[])
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load agents')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="max-w-4xl mx-auto">
      <div className="bg-white rounded-lg shadow p-8">
        <h2 className="text-2xl font-bold text-gray-800 mb-4">Agent Registry</h2>

        {loading && <p className="text-gray-500">Loading agents...</p>}
        {error && <div className="p-3 bg-red-50 border border-red-200 rounded text-red-700 text-sm">{error}</div>}

        {!loading && !error && (
          <>
            <p className="text-gray-500 mb-4">
              {agents.length} agent(s) from stored plans. Agents are created dynamically by the Planner.
            </p>

            {agents.length === 0 ? (
              <p className="text-gray-400 text-sm">
                No agents yet. Generate a plan from the Chat page to see agents here.
              </p>
            ) : (
              <div className="space-y-3">
                {agents.map((agent) => (
                  <div key={agent.id} className="border border-gray-200 rounded-lg p-4">
                    <div className="flex items-start justify-between mb-2">
                      <div>
                        <h3 className="font-semibold text-gray-800">{agent.name}</h3>
                        <code className="text-xs bg-gray-100 px-2 py-0.5 rounded">{agent.id}</code>
                      </div>
                      {agent.requires_human_approval && (
                        <span className="px-2 py-1 rounded text-xs bg-orange-100 text-orange-800">Requires Approval</span>
                      )}
                    </div>
                    <p className="text-sm text-gray-600 mb-2">{agent.description}</p>
                    <p className="text-sm text-gray-700"><strong>Goal:</strong> {agent.goal}</p>
                    {agent.tools.length > 0 && (
                      <div className="flex gap-1 mt-2 flex-wrap">
                        {agent.tools.map((tool) => (
                          <span key={tool} className="text-xs bg-blue-50 text-blue-700 px-2 py-0.5 rounded">{tool}</span>
                        ))}
                      </div>
                    )}
                    {agent.dependencies.length > 0 && (
                      <p className="text-xs text-gray-500 mt-2">Depends on: {agent.dependencies.join(', ')}</p>
                    )}
                  </div>
                ))}
              </div>
            )}
          </>
        )}
      </div>
    </div>
  )
}

export default AgentsPage