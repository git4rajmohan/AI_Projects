import { useState, useEffect } from 'react'
import { api } from '../services/api'
import type { Skill } from '../types'

function SkillsPage() {
  const [skills, setSkills] = useState<Skill[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [recommendations, setRecommendations] = useState<unknown[]>([])
  const [searchIntent, setSearchIntent] = useState('')

  useEffect(() => {
    loadSkills()
  }, [])

  const loadSkills = async () => {
    setLoading(true)
    try {
      const data = await api.listSkills()
      setSkills(data)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load skills')
    } finally {
      setLoading(false)
    }
  }

  const getRecommendations = async () => {
    if (!searchIntent.trim()) return
    try {
      const response = await fetch(`/api/skills/recommend?intent=${encodeURIComponent(searchIntent)}&max_results=5`)
      const data = await response.json()
      setRecommendations(data.recommendations || [])
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to get recommendations')
    }
  }

  return (
    <div className="max-w-4xl mx-auto space-y-6">
      <div className="bg-white rounded-lg shadow p-8">
        <h2 className="text-2xl font-bold text-gray-800 mb-4">Skill Library</h2>

        {loading && <p className="text-gray-500">Loading skills...</p>}
        {error && <div className="p-3 bg-red-50 border border-red-200 rounded text-red-700 text-sm">{error}</div>}

        {!loading && !error && (
          <>
            <p className="text-gray-500 mb-4">{skills.length} skills registered.</p>

            {skills.length === 0 ? (
              <p className="text-gray-400 text-sm">
                No skills yet. Skills are created after successful workflow execution,
                or imported via the upload endpoint.
              </p>
            ) : (
              <div className="space-y-3">
                {skills.map((skill) => (
                  <div key={skill.id} className="border border-gray-200 rounded-lg p-4">
                    <div className="flex items-start justify-between mb-2">
                      <div>
                        <h3 className="font-semibold text-gray-800">{skill.name}</h3>
                        <p className="text-sm text-gray-600 mt-1">{skill.description}</p>
                      </div>
                      <span className={`px-2 py-1 rounded text-xs ${skill.enabled ? 'bg-green-100 text-green-800' : 'bg-gray-100 text-gray-500'}`}>
                        {skill.enabled ? 'Enabled' : 'Disabled'}
                      </span>
                    </div>
                    {skill.tags && skill.tags.length > 0 && (
                      <div className="flex gap-1 mt-2">
                        {skill.tags.map((tag) => (
                          <span key={tag} className="text-xs bg-blue-50 text-blue-700 px-2 py-0.5 rounded">{tag}</span>
                        ))}
                      </div>
                    )}
                    <div className="flex gap-4 mt-3 text-xs text-gray-500">
                      <span>Used: {skill.usage_count}</span>
                      <span>Success: {skill.success_count}</span>
                      <span>Failed: {skill.failure_count}</span>
                      {skill.avg_duration_seconds > 0 && <span>Avg: {skill.avg_duration_seconds.toFixed(1)}s</span>}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </>
        )}
      </div>

      <div className="bg-white rounded-lg shadow p-8">
        <h3 className="text-lg font-bold text-gray-800 mb-4">Skill Recommendations</h3>
        <p className="text-gray-500 text-sm mb-4">Enter an intent to find matching skills from the library.</p>
        <div className="flex gap-2 mb-4">
          <input
            type="text"
            value={searchIntent}
            onChange={(e) => setSearchIntent(e.target.value)}
            placeholder="e.g., Convert CSV to Excel"
            className="flex-1 px-4 py-2 border border-gray-300 rounded focus:ring-2 focus:ring-blue-500"
            onKeyDown={(e) => e.key === 'Enter' && getRecommendations()}
          />
          <button
            onClick={getRecommendations}
            className="px-4 py-2 bg-blue-600 text-white rounded hover:bg-blue-700 text-sm"
          >
            Recommend
          </button>
        </div>
        {recommendations.length > 0 && (
          <div className="space-y-2">
            {(recommendations as Array<Record<string, unknown>>).map((rec, i) => (
              <div key={i} className="border border-gray-200 rounded p-3">
                <div className="flex justify-between">
                  <span className="font-medium">{rec.skill_name as string}</span>
                  <span className="text-sm text-blue-600">Score: {(rec.score as number).toFixed(2)}</span>
                </div>
                <p className="text-xs text-gray-500 mt-1">{rec.reason as string}</p>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}

export default SkillsPage