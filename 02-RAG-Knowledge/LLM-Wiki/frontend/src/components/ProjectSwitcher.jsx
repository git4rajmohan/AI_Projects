import { useEffect } from 'react'
import useAppStore from '../store/appStore'

export default function ProjectSwitcher() {
  const { projects, activeProject, setProjects, setActiveProject } = useAppStore()

  useEffect(() => {
    fetch('/api/config')
      .then((r) => r.json())
      .then((data) => {
        const list = data.projects || []
        setProjects(list)
        if (data.active_project_id) {
          const found = list.find((p) => p.id === data.active_project_id)
          if (found) setActiveProject(found)
        }
      })
      .catch(() => {})
  }, [])

  const handleSwitch = async (projectId) => {
    if (!projectId) {
      // User picked the "none" option — deselect
      const res = await fetch('/api/config/projects/active', { method: 'DELETE' })
      if (res.ok) setActiveProject(null)
      return
    }
    const res = await fetch('/api/config/projects/active', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ project_id: projectId }),
    })
    if (res.ok) {
      const found = projects.find((p) => p.id === projectId)
      if (found) setActiveProject(found)
    }
  }

  const handleUnselect = async () => {
    const res = await fetch('/api/config/projects/active', { method: 'DELETE' })
    if (res.ok) setActiveProject(null)
  }

  return (
    <div className="flex items-center gap-2">
      <span className="text-sm text-gray-500 dark:text-gray-400">Wiki:</span>
      {activeProject ? (
        <>
          <span className="text-sm font-medium text-gray-800 dark:text-gray-100 px-2 py-1 border border-gray-300 dark:border-gray-600 rounded bg-white dark:bg-gray-800">
            {activeProject.name}
          </span>
          <button
            onClick={handleUnselect}
            title="Unselect project"
            className="text-gray-400 hover:text-red-500 dark:hover:text-red-400 text-lg leading-none transition-colors"
          >
            ×
          </button>
        </>
      ) : (
        <select
          className="text-sm border border-gray-300 dark:border-gray-600 rounded px-2 py-1 bg-white dark:bg-gray-800 dark:text-gray-100"
          value=""
          onChange={(e) => handleSwitch(e.target.value)}
        >
          <option value="">— select project —</option>
          {projects.map((p) => (
            <option key={p.id} value={p.id}>
              {p.name}
            </option>
          ))}
        </select>
      )}
    </div>
  )
}
