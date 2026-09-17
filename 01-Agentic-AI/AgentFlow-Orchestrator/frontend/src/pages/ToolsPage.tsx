import { useState, useEffect } from 'react'
import { api } from '../services/api'
import type { Tool } from '../types'

function ToolsPage() {
  const [tools, setTools] = useState<Tool[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [testingTool, setTestingTool] = useState<string | null>(null)
  const [testResult, setTestResult] = useState<string | null>(null)

  useEffect(() => {
    loadTools()
  }, [])

  const loadTools = async () => {
    setLoading(true)
    try {
      const data = await api.listTools()
      setTools(data)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load tools')
    } finally {
      setLoading(false)
    }
  }

  const testCalculator = async () => {
    setTestingTool('calculator')
    setTestResult(null)
    try {
      const response = await fetch('/api/tools/calculator/execute', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ params: { expression: '6 * 7' } }),
      })
      const data = await response.json()
      setTestResult(JSON.stringify(data, null, 2))
    } catch (err) {
      setTestResult(`Error: ${err}`)
    } finally {
      setTestingTool(null)
    }
  }

  const permColors: Record<string, string> = {
    READ: 'bg-green-100 text-green-800',
    WRITE: 'bg-yellow-100 text-yellow-800',
    EXTERNAL_ACTION: 'bg-orange-100 text-orange-800',
    DESTRUCTIVE: 'bg-red-100 text-red-800',
  }

  return (
    <div className="max-w-4xl mx-auto">
      <div className="bg-white rounded-lg shadow p-8">
        <h2 className="text-2xl font-bold text-gray-800 mb-4">Tool Registry</h2>

        {loading && <p className="text-gray-500">Loading tools...</p>}
        {error && <div className="p-3 bg-red-50 border border-red-200 rounded text-red-700 text-sm">{error}</div>}

        {!loading && !error && (
          <>
            <p className="text-gray-500 mb-4">{tools.length} registered tools available for agents.</p>

            <div className="space-y-3">
              {tools.map((tool) => (
                <div key={tool.id} className="border border-gray-200 rounded-lg p-4 hover:shadow-sm transition-shadow">
                  <div className="flex items-start justify-between">
                    <div className="flex-1">
                      <div className="flex items-center gap-2 mb-1">
                        <h3 className="font-semibold text-gray-800">{tool.name}</h3>
                        <code className="text-xs bg-gray-100 px-2 py-0.5 rounded">{tool.id}</code>
                      </div>
                      <p className="text-sm text-gray-600">{tool.description}</p>
                    </div>
                    <span className={`px-2 py-1 rounded text-xs font-medium ${permColors[tool.permission_level] || 'bg-gray-100 text-gray-800'}`}>
                      {tool.permission_level}
                    </span>
                  </div>
                </div>
              ))}
            </div>

            <div className="mt-6 pt-6 border-t border-gray-200">
              <h3 className="font-semibold text-gray-800 mb-2">Test a Tool</h3>
              <button
                onClick={testCalculator}
                disabled={testingTool !== null}
                className="px-4 py-2 bg-blue-600 text-white rounded hover:bg-blue-700 disabled:opacity-50 text-sm"
              >
                {testingTool ? 'Running...' : 'Test Calculator (6 * 7)'}
              </button>
              {testResult && (
                <pre className="mt-3 p-3 bg-gray-900 text-green-400 rounded text-sm overflow-x-auto">{testResult}</pre>
              )}
            </div>
          </>
        )}
      </div>
    </div>
  )
}

export default ToolsPage