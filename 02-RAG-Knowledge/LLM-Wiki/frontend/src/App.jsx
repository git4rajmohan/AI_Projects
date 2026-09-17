import { useEffect } from 'react'
import useAppStore from './store/appStore'
import ProjectSwitcher from './components/ProjectSwitcher'
import ConfigTab from './tabs/ConfigTab'
import WikiTab from './tabs/WikiTab'
import QueryTab from './tabs/QueryTab'

const TABS = [
  { id: 'config', label: 'Config' },
  { id: 'wiki', label: 'View Wiki' },
  { id: 'query', label: 'Query' },
]

export default function App() {
  const { activeTab, setActiveTab, setLLMConfig, setLLMConnected, setProjects, setActiveProject } = useAppStore()

  // Fetch config on mount to initialise LLM connection state and project list
  useEffect(() => {
    fetch('/api/config')
      .then((r) => r.json())
      .then((data) => {
        if (data.llm) {
          setLLMConfig(data.llm)
          setLLMConnected(!!data.llm.is_configured)
        }
        if (data.projects) {
          setProjects(data.projects)
          const active = data.projects.find((p) => p.id === data.active_project_id)
          if (active) setActiveProject(active)
        }
      })
      .catch(() => {})
  }, [])

  return (
    <div className="flex flex-col h-screen bg-white dark:bg-gray-900">
      {/* Header */}
      <header className="flex items-center gap-4 px-4 h-12 border-b border-gray-200 dark:border-gray-700 shrink-0">
        <span className="font-semibold text-sm text-gray-800 dark:text-gray-100 mr-2">
          LLMWikiUI
        </span>
        <ProjectSwitcher />
        <div className="flex-1" />
        {/* Tab bar */}
        <nav className="flex gap-1">
          {TABS.map((t) => (
            <button
              key={t.id}
              onClick={() => setActiveTab(t.id)}
              className={`px-4 py-1.5 text-sm rounded ${
                activeTab === t.id
                  ? 'bg-purple-600 text-white'
                  : 'text-gray-600 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-800'
              }`}
            >
              {t.label}
            </button>
          ))}
        </nav>
      </header>

      {/* Tab content */}
      <div className="flex-1 overflow-hidden">
        {activeTab === 'config' && <ConfigTab />}
        {activeTab === 'wiki' && <WikiTab />}
        {activeTab === 'query' && <QueryTab />}
      </div>
    </div>
  )
}
