import { useState } from 'react'
import useAppStore from '../store/appStore'
import StreamingOutput from './StreamingOutput'

export default function LintPanel() {
  const { activeProject, llmConnected } = useAppStore()
  const [lines, setLines] = useState([])
  const [programmatic, setProgrammatic] = useState(null)
  const [isStreaming, setIsStreaming] = useState(false)

  const handleRun = async () => {
    if (!activeProject) return
    setLines([])
    setProgrammatic(null)
    setIsStreaming(true)

    const res = await fetch('/api/lint/run', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ project_id: activeProject.id }),
    })

    const reader = res.body.getReader()
    const decoder = new TextDecoder()
    let buf = ''

    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      buf += decoder.decode(value, { stream: true })
      const parts = buf.split('\n\n')
      buf = parts.pop()
      for (const part of parts) {
        if (!part.startsWith('data:')) continue
        try {
          const ev = JSON.parse(part.slice(5).trim())
          if (ev.type === 'progress') setLines((l) => [...l, ev.message])
          else if (ev.type === 'programmatic') setProgrammatic(ev.results)
          else if (ev.type === 'token') {
            setLines((l) => {
              const last = l[l.length - 1] || ''
              return [...l.slice(0, -1), last + ev.token]
            })
          } else if (ev.type === 'done') setLines((l) => [...l, '✓ Lint complete'])
        } catch (_) {}
      }
    }
    setIsStreaming(false)
  }

  return (
    <div className="space-y-4">
      <p className="text-sm text-gray-600 dark:text-gray-400">
        Run a two-phase health check: broken links + orphan detection, then an LLM narrative analysis.
      </p>

      {!llmConnected && (
        <div className="p-3 rounded border border-amber-300 dark:border-amber-700 bg-amber-50 dark:bg-amber-900/20 text-sm text-amber-700 dark:text-amber-400">
          ⚠ LLM is not connected. Go to <strong>LLM Connection</strong> to configure and test your model before running a health check.
        </div>
      )}

      <button
        onClick={handleRun}
        disabled={isStreaming || !activeProject || !llmConnected}
        title={!llmConnected ? 'Connect LLM first' : undefined}
        className="px-4 py-2 bg-purple-600 hover:bg-purple-700 disabled:opacity-40 text-white rounded text-sm"
      >
        {isStreaming ? 'Running…' : 'Run Health Check'}
      </button>

      {/* Programmatic results */}
      {programmatic && (
        <div className="space-y-3">
          <LintSection
            title="Broken Links"
            items={programmatic.broken_links}
            emptyMsg="No broken links"
            renderItem={(item) => (
              <span>
                <span className="font-medium">{item.source}</span> → <span className="text-red-500">{item.target}</span>
              </span>
            )}
          />
          <LintSection
            title="Orphan Pages"
            items={programmatic.orphan_pages}
            emptyMsg="No orphan pages"
            renderItem={(item) => <span>{item}</span>}
          />
          <LintSection
            title="Pages With No Outbound Links"
            items={programmatic.no_outbound}
            emptyMsg="All pages have outbound links"
            renderItem={(item) => <span>{item}</span>}
          />
        </div>
      )}

      {/* LLM streaming output */}
      {lines.length > 0 && (
        <div>
          <p className="text-xs font-medium text-gray-500 dark:text-gray-400 mb-1">LLM Analysis</p>
          <StreamingOutput lines={lines} isStreaming={isStreaming} />
        </div>
      )}
    </div>
  )
}

function LintSection({ title, items, emptyMsg, renderItem }) {
  const [open, setOpen] = useState(true)
  const hasItems = items && items.length > 0

  return (
    <div className="border border-gray-200 dark:border-gray-700 rounded overflow-hidden">
      <button
        className="w-full flex items-center justify-between px-3 py-2 bg-gray-50 dark:bg-gray-800 text-sm font-medium dark:text-gray-200"
        onClick={() => setOpen((o) => !o)}
      >
        <span>{title}</span>
        <span className={`text-xs px-2 py-0.5 rounded ${hasItems ? 'bg-red-100 text-red-700 dark:bg-red-900/40 dark:text-red-400' : 'bg-green-100 text-green-700 dark:bg-green-900/40 dark:text-green-400'}`}>
          {items?.length ?? 0}
        </span>
      </button>
      {open && (
        <div className="px-3 py-2 text-xs space-y-1 dark:text-gray-300">
          {hasItems ? items.map((item, i) => <div key={i}>{renderItem(item)}</div>) : (
            <span className="text-gray-400">{emptyMsg}</span>
          )}
        </div>
      )}
    </div>
  )
}
