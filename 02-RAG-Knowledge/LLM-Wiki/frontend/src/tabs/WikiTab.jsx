import { useState, useRef, useCallback } from 'react'
import useAppStore from '../store/appStore'
import FileTree from '../components/FileTree'
import MarkdownViewer from '../components/MarkdownViewer'
import GraphView from '../components/GraphView'

export default function WikiTab() {
  const { activeProject, setActivePage } = useAppStore()
  const [viewMode, setViewMode] = useState('tree') // 'tree' | 'graph'
  const [sidebarWidth, setSidebarWidth] = useState(224) // px, default = w-56
  const dragging = useRef(false)
  const dragStart = useRef({ x: 0, width: 0 })

  const onDragStart = (e) => {
    dragging.current = true
    dragStart.current = { x: e.clientX, width: sidebarWidth }
    document.body.style.cursor = 'col-resize'
    document.body.style.userSelect = 'none'
  }

  const onDragMove = useCallback((e) => {
    if (!dragging.current) return
    const next = Math.max(140, Math.min(520, dragStart.current.width + e.clientX - dragStart.current.x))
    setSidebarWidth(next)
  }, [])

  const onDragEnd = useCallback(() => {
    dragging.current = false
    document.body.style.cursor = ''
    document.body.style.userSelect = ''
  }, [])

  const handleSelect = async (path) => {
    if (!activeProject) return
    const res = await fetch(
      `/api/wiki/page?project_id=${activeProject.id}&path=${encodeURIComponent(path)}`,
    )
    if (res.ok) {
      const data = await res.json()
      setActivePage(data)
    }
  }

  return (
    <div className="flex flex-col h-full overflow-hidden">
      {/* View mode toggle bar */}
      <div className="flex items-center gap-2 px-3 py-2 border-b border-gray-200 dark:border-gray-700 shrink-0">
        <span className="text-xs font-semibold uppercase tracking-wider text-gray-500 dark:text-gray-400 mr-1">View:</span>
        <button
          onClick={() => setViewMode('tree')}
          className={`px-4 py-1.5 text-sm font-medium rounded ${
            viewMode === 'tree'
              ? 'bg-purple-600 text-white shadow-sm'
              : 'bg-gray-100 text-gray-700 dark:bg-gray-800 dark:text-gray-200 hover:bg-gray-200 dark:hover:bg-gray-700'
          }`}
        >
          📁 Tree
        </button>
        <button
          onClick={() => setViewMode('graph')}
          className={`px-4 py-1.5 text-sm font-medium rounded ${
            viewMode === 'graph'
              ? 'bg-purple-600 text-white shadow-sm'
              : 'bg-gray-100 text-gray-700 dark:bg-gray-800 dark:text-gray-200 hover:bg-gray-200 dark:hover:bg-gray-700'
          }`}
        >
          🕸️ Graph
        </button>
      </div>

      {viewMode === 'graph' ? (
        /* Full-area graph view */
        <div className="flex-1 overflow-hidden">
          <GraphView onSelectPage={(path) => { handleSelect(path); setViewMode('tree') }} />
        </div>
      ) : (
        /* Original tree + viewer layout — resizable sidebar */
        <div
          className="flex flex-1 overflow-hidden"
          onMouseMove={onDragMove}
          onMouseUp={onDragEnd}
          onMouseLeave={onDragEnd}
        >
          {/* Sidebar */}
          <aside
            style={{ width: sidebarWidth }}
            className="shrink-0 border-r border-gray-200 dark:border-gray-700 overflow-hidden flex flex-col"
          >
            {!activeProject ? (
              <p className="text-xs text-gray-400 px-3 py-4">
                Select a project from the header
              </p>
            ) : (
              <FileTree onSelect={handleSelect} />
            )}
          </aside>

          {/* Drag handle */}
          <div
            onMouseDown={onDragStart}
            className="w-1 shrink-0 cursor-col-resize bg-transparent hover:bg-purple-400 dark:hover:bg-purple-600 transition-colors"
            title="Drag to resize"
          />

          {/* Main viewer */}
          <main className="flex-1 overflow-hidden">
            <MarkdownViewer />
          </main>
        </div>
      )}
    </div>
  )
}
