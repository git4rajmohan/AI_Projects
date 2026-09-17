import { useState } from 'react'
import LLMConfigForm from '../components/LLMConfigForm'
import IngestPanel from '../components/IngestPanel'
import LintPanel from '../components/LintPanel'
import useAppStore from '../store/appStore'

const SECTIONS = ['LLM Connection', 'Ingest', 'Health Check']

export default function ConfigTab() {
  const [section, setSection] = useState('LLM Connection')
  const { activeProject } = useAppStore()

  return (
    <div className="flex h-full">
      {/* Sidebar */}
      <nav className="w-44 shrink-0 border-r border-gray-200 dark:border-gray-700 py-4 space-y-1">
        {SECTIONS.map((s) => (
          <button
            key={s}
            onClick={() => setSection(s)}
            className={`w-full text-left px-4 py-2 text-sm rounded-l-none rounded-r ${
              section === s
                ? 'bg-purple-50 dark:bg-purple-900/30 text-purple-700 dark:text-purple-300 font-medium border-r-2 border-purple-500'
                : 'text-gray-600 dark:text-gray-400 hover:bg-gray-50 dark:hover:bg-gray-800'
            }`}
          >
            {s}
          </button>
        ))}
      </nav>

      {/* Content */}
      <div className="flex-1 overflow-y-auto p-6">
        {section === 'LLM Connection' && (
          <div>
            <h2 className="text-lg font-semibold mb-4 dark:text-gray-100">LLM Connection</h2>
            <div className="max-w-lg">
              <LLMConfigForm />
            </div>
          </div>
        )}

        {section === 'Ingest' && (
          <div>
            <h2 className="text-lg font-semibold mb-1 dark:text-gray-100">Ingest</h2>
            {!activeProject && (
              <p className="text-sm text-amber-600 dark:text-amber-400 mb-4">
                No active project. Create a new wiki below or select one from the header.
              </p>
            )}
            <IngestPanel />
          </div>
        )}

        {section === 'Health Check' && (
          <div>
            <h2 className="text-lg font-semibold mb-4 dark:text-gray-100">Wiki Health Check</h2>
            {!activeProject ? (
              <p className="text-sm text-amber-600 dark:text-amber-400">
                Select a project first.
              </p>
            ) : (
              <LintPanel />
            )}
          </div>
        )}
      </div>
    </div>
  )
}
