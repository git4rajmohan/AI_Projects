import { useState, useEffect, useCallback, useRef } from 'react'
import useAppStore from '../store/appStore'
import StreamingOutput from './StreamingOutput'

export default function IngestPanel() {
  const { activeProject, projects, setProjects, setActiveProject, llmConnected } = useAppStore()
  const [mode, setMode] = useState('new') // 'new' | 'existing'
  const [files, setFiles] = useState([]) // source file list
  const [selectedFiles, setSelectedFiles] = useState([])
  const [lines, setLines] = useState([])
  const [isStreaming, setIsStreaming] = useState(false)
  const [progress, setProgress] = useState({ current: 0, total: 0, currentFile: '' })
  const abortRef = useRef(null)
  const fileInputRef = useRef(null)
  const [scaffolded, setScaffolded] = useState(false)
  const [dragging, setDragging] = useState(false)
  const [newProjectName, setNewProjectName] = useState('')
  const [newProjectPath, setNewProjectPath] = useState('')
  const [existingPath, setExistingPath] = useState('')
  const [existingName, setExistingName] = useState('')
  const [existingAdded, setExistingAdded] = useState(false)
  const [existingError, setExistingError] = useState('')

  const browseFolder = async (setter) => {
    try {
      const res = await fetch('/api/utils/pick-folder')
      const data = await res.json()
      if (data.path) setter(data.path)
    } catch (_) {}
  }

  // For new wiki: pick the parent folder, then append the project name
  const browseParentForNew = async () => {
    try {
      const res = await fetch('/api/utils/pick-folder')
      const data = await res.json()
      if (!data.path) return
      const sep = data.path.includes('/') ? '/' : '\\'
      const name = newProjectName.trim().replace(/[\\/:*?"<>|]/g, '_') || 'MyWiki'
      setNewProjectPath(data.path + sep + name)
    } catch (_) {}
  }

  const loadFiles = async (projectId) => {
    const res = await fetch(`/api/ingest/files?project_id=${projectId}`)
    if (res.ok) {
      const data = await res.json()
      setFiles(data.files || [])
    }
  }

  const handleBrowseFiles = useCallback(
    async (e) => {
      if (!activeProject) return
      const picked = Array.from(e.target.files || [])
      for (const file of picked) {
        const fd = new FormData()
        fd.append('file', file)
        fd.append('project_id', activeProject.id)
        await fetch('/api/ingest/upload', { method: 'POST', body: fd })
      }
      e.target.value = ''
      await loadFiles(activeProject.id)
    },
    [activeProject],
  )

  const handleRemoveFile = useCallback(
    async (filePath, fileName) => {
      if (!activeProject) return
      if (!window.confirm(`Remove "${fileName}" from Clippings?\nIts wiki source page will also be deleted.`)) return
      const res = await fetch('/api/ingest/file', {
        method: 'DELETE',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ project_id: activeProject.id, file_path: filePath }),
      })
      if (res.ok) {
        setSelectedFiles((prev) => prev.filter((p) => p !== filePath))
        await loadFiles(activeProject.id)
        setLines((l) => [...l, `✓ Removed ${fileName}`])
      }
    },
    [activeProject],
  )

  const handleScaffold = async () => {
    if (!newProjectName || !newProjectPath) return
    // 1. Register the project in config
    const createRes = await fetch('/api/config/projects', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name: newProjectName, root_path: newProjectPath }),
    })
    if (!createRes.ok) return
    const project = await createRes.json()
    // 2. Scaffold the folder structure
    await fetch('/api/ingest/scaffold', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ project_id: project.id }),
    })
    // 3. Refresh project list and set active
    const cfgRes = await fetch('/api/config')
    if (cfgRes.ok) {
      const cfg = await cfgRes.json()
      const list = cfg.projects || []
      setProjects(list)
      const found = list.find((p) => p.id === project.id)
      if (found) {
        setActiveProject(found)
        // Persist to backend so header dropdown stays in sync
        await fetch('/api/config/projects/active', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ project_id: project.id }),
        })
      }
    }
    setScaffolded(true)
    setLines((l) => [...l, `✓ Created wiki at ${newProjectPath}`])
    await loadFiles(project.id)
  }

  const handleDrop = useCallback(
    async (e) => {
      e.preventDefault()
      setDragging(false)
      if (!activeProject) return
      const droppedFiles = Array.from(e.dataTransfer.files)
      for (const file of droppedFiles) {
        const fd = new FormData()
        fd.append('file', file)
        fd.append('project_id', activeProject.id)
        await fetch('/api/ingest/upload', { method: 'POST', body: fd })
      }
      await loadFiles(activeProject.id)
    },
    [activeProject],
  )

  const toggleFile = (path) => {
    setSelectedFiles((prev) =>
      prev.includes(path) ? prev.filter((p) => p !== path) : [...prev, path],
    )
  }

  const handleStop = () => {
    if (abortRef.current) abortRef.current.abort()
  }

  const handleRun = async (rebuild = false) => {
    if (!activeProject) return
    if (!rebuild && selectedFiles.length === 0) return
    setLines([])
    setProgress({ current: 0, total: 0, currentFile: '' })
    setIsStreaming(true)

    const controller = new AbortController()
    abortRef.current = controller
    const runProjectId = activeProject.id

    try {
      const body = JSON.stringify({
        project_id: activeProject.id,
        // rebuild sends null → backend resolves to all files; ingest uses only selection
        file_paths: rebuild ? null : selectedFiles,
        rebuild,
      })

      const res = await fetch('/api/ingest/run', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body,
        signal: controller.signal,
      })

      const reader = res.body.getReader()
      const decoder = new TextDecoder()
      let buf = ''

      try {
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
              if (ev.event === 'progress') {
                setProgress({ current: ev.index, total: ev.total, currentFile: ev.file })
                setLines((l) => [...l, ev.message])
              } else if (ev.event === 'token') {
                setLines((l) => {
                  const last = l[l.length - 1] || ''
                  return [...l.slice(0, -1), last + ev.chunk]
                })
              } else if (ev.event === 'file_done') {
                setProgress((p) => ({ ...p, current: ev.index, total: ev.total, currentFile: '' }))
                setFiles((fs) => fs.map((f) => f.path === ev.file ? { ...f, status: 'ingested' } : f))
                setLines((l) => [...l, `✓ ${ev.file} (${ev.pages_written?.length ?? 0} pages)`])
              } else if (ev.event === 'error') {
                setLines((l) => [...l, `✗ ${ev.file}: ${ev.message}`])
              } else if (ev.event === 'done') {
                setProgress((p) => ({ ...p, current: p.total, currentFile: '' }))
                setLines((l) => [...l, `✓ Done — ${ev.total} file(s) processed`])
                await loadFiles(runProjectId)
              }
            } catch (_) {}
          }
        }
      } finally {
        reader.releaseLock()
      }
    } catch (err) {
      if (err.name === 'AbortError') {
        setLines((l) => [...l, '⏹ Stopped by user'])
      } else {
        setLines((l) => [...l, `✗ Error: ${err.message}`])
      }
    } finally {
      setIsStreaming(false)
      abortRef.current = null
    }
  }

  // Load files when active project changes
  useEffect(() => {
    if (activeProject) loadFiles(activeProject.id)
  }, [activeProject?.id])

  const handleSwitchProject = async (projectId) => {
    if (!projectId) {
      await fetch('/api/config/projects/active', { method: 'DELETE' })
      setActiveProject(null)
    } else {
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
  }

  return (
    <div className="space-y-5">
      {/* Active project selector */}
      <div className="flex items-center gap-3 p-3 bg-gray-50 dark:bg-gray-800/60 border border-gray-200 dark:border-gray-700 rounded">
        <span className="text-xs font-semibold text-gray-500 dark:text-gray-400 whitespace-nowrap shrink-0">Working on:</span>
        {activeProject ? (
          <>
            <span className="flex-1 text-sm font-medium text-gray-800 dark:text-gray-100 px-2 py-1 border border-gray-200 dark:border-gray-600 rounded bg-white dark:bg-gray-700">
              {activeProject.name}
            </span>
            <button
              onClick={() => handleSwitchProject('')}
              title="Switch project"
              className="text-xs text-gray-400 hover:text-red-500 dark:hover:text-red-400 transition-colors whitespace-nowrap"
            >
              × switch
            </button>
          </>
        ) : (
          <select
            className="flex-1 text-sm border border-gray-300 dark:border-gray-600 rounded px-2 py-1 bg-white dark:bg-gray-700 dark:text-gray-100"
            value=""
            onChange={(e) => handleSwitchProject(e.target.value)}
          >
            <option value="">— select project —</option>
            {projects.map((p) => (
              <option key={p.id} value={p.id}>{p.name}</option>
            ))}
          </select>
        )}
      </div>

      {/* Mode selector */}
      <div className="flex gap-4">
        {['new', 'existing'].map((m) => (
          <label key={m} className="flex items-center gap-2 cursor-pointer text-sm">
            <input
              type="radio"
              name="ingest-mode"
              value={m}
              checked={mode === m}
              onChange={() => setMode(m)}
            />
            <span className="capitalize dark:text-gray-200">{m} wiki</span>
          </label>
        ))}
      </div>

      {/* New wiki scaffold */}
      {mode === 'new' && (
        <div className="space-y-3 p-4 border border-dashed border-gray-300 dark:border-gray-600 rounded">
          <div>
            <label className="block text-xs font-medium text-gray-600 dark:text-gray-400 mb-1">
              Project Name
            </label>
            <input
              className="w-full border border-gray-300 dark:border-gray-600 rounded px-3 py-2 text-sm bg-white dark:bg-gray-800 dark:text-gray-100"
              value={newProjectName}
              onChange={(e) => setNewProjectName(e.target.value)}
              placeholder="My Wiki"
            />
          </div>
          <div>
            <label className="block text-xs font-medium text-gray-600 dark:text-gray-400 mb-1">
              Wiki Folder Path
              <span className="ml-1 font-normal text-gray-400">(Browse picks a parent folder — project name is appended)</span>
            </label>
            <div className="flex gap-2">
              <input
                className="flex-1 border border-gray-300 dark:border-gray-600 rounded px-3 py-2 text-sm bg-white dark:bg-gray-800 dark:text-gray-100"
                value={newProjectPath}
                onChange={(e) => setNewProjectPath(e.target.value)}
                placeholder="D:\MyWikis\ProjectName"
              />
              <button
                type="button"
                onClick={browseParentForNew}
                className="px-3 py-2 border border-gray-300 dark:border-gray-600 rounded text-sm hover:bg-gray-100 dark:hover:bg-gray-700 dark:text-gray-200 whitespace-nowrap"
              >
                Browse…
              </button>
            </div>
          </div>
          <button
            onClick={handleScaffold}
            disabled={!newProjectName || !newProjectPath}
            className="px-4 py-2 bg-purple-600 hover:bg-purple-700 disabled:opacity-40 text-white rounded text-sm"
          >
            Create Wiki Structure
          </button>
        </div>
      )}

      {/* Existing wiki selector */}
      {mode === 'existing' && (
        <div className="space-y-3 p-4 border border-dashed border-gray-300 dark:border-gray-600 rounded">
          {existingAdded ? (
            <div className="space-y-2">
              <p className="text-sm text-green-600 dark:text-green-400">✓ &quot;{existingName}&quot; added and set as active project.</p>
              <button
                type="button"
                onClick={() => { setExistingAdded(false); setExistingName(''); setExistingPath('') }}
                className="text-xs text-purple-600 dark:text-purple-400 underline hover:no-underline"
              >
                Add another existing project
              </button>
            </div>
          ) : (
            <>
              <div>
                <label className="block text-xs font-medium text-gray-600 dark:text-gray-400 mb-1">
                  Project Name
                </label>
                <input
                  className="w-full border border-gray-300 dark:border-gray-600 rounded px-3 py-2 text-sm bg-white dark:bg-gray-800 dark:text-gray-100"
                  value={existingName}
                  onChange={(e) => setExistingName(e.target.value)}
                  placeholder="My Existing Wiki"
                />
              </div>
              <div>
                <label className="block text-xs font-medium text-gray-600 dark:text-gray-400 mb-1">
                  Existing Wiki Folder (contains wiki/ and Clippings/)
                </label>
                <div className="flex gap-2">
                  <input
                    className="flex-1 border border-gray-300 dark:border-gray-600 rounded px-3 py-2 text-sm bg-white dark:bg-gray-800 dark:text-gray-100"
                    value={existingPath}
                    onChange={(e) => setExistingPath(e.target.value)}
                    placeholder="D:\MyWikis\ExistingProject"
                  />
                  <button
                    type="button"
                    onClick={async () => {
                      try {
                        const res = await fetch('/api/utils/pick-folder')
                        const data = await res.json()
                        if (data.path) {
                          setExistingPath(data.path)
                          if (!existingName) {
                            const sep = data.path.includes('/') ? '/' : '\\'
                            const parts = data.path.split(sep)
                            setExistingName(parts[parts.length - 1] || '')
                          }
                        }
                      } catch (_) {}
                    }}
                    className="px-3 py-2 border border-gray-300 dark:border-gray-600 rounded text-sm hover:bg-gray-100 dark:hover:bg-gray-700 dark:text-gray-200 whitespace-nowrap"
                  >
                    Browse…
                  </button>
                </div>
              </div>
              {existingError && (
                <p className="text-xs text-red-500">{existingError}</p>
              )}
              <button
                onClick={async () => {
                  setExistingError('')
                  if (!existingName.trim()) { setExistingError('Please enter a project name.'); return }
                  if (!existingPath.trim()) { setExistingError('Please select a folder.'); return }
                  const res = await fetch('/api/config/projects', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ name: existingName.trim(), root_path: existingPath.trim() }),
                  })
                  if (res.ok) {
                    const project = await res.json()
                    const cfgRes = await fetch('/api/config')
                    if (cfgRes.ok) {
                      const cfg = await cfgRes.json()
                      const list = cfg.projects || []
                      setProjects(list)
                      const found = list.find((p) => p.id === project.id)
                      if (found) {
                        setActiveProject(found)
                        // Persist to backend so header dropdown stays in sync
                        await fetch('/api/config/projects/active', {
                          method: 'POST',
                          headers: { 'Content-Type': 'application/json' },
                          body: JSON.stringify({ project_id: project.id }),
                        })
                      }
                    }
                    setExistingAdded(true)
                    setLines((l) => [...l, `✓ Added project "${existingName}" → ${existingPath}`])
                  } else {
                    const err = await res.json().catch(() => ({}))
                    setExistingError(err.detail || `Error ${res.status}`)
                  }
                }}
                className="px-4 py-2 bg-purple-600 hover:bg-purple-700 text-white rounded text-sm"
              >
                Add Project
              </button>
            </>
          )}
        </div>
      )}

      {/* LLM not connected warning */}
      {!llmConnected && activeProject && (
        <div className="p-3 rounded border border-amber-300 dark:border-amber-700 bg-amber-50 dark:bg-amber-900/20 text-sm text-amber-700 dark:text-amber-400">
          ⚠ LLM is not connected. Go to <strong>LLM Connection</strong> to configure and test your model before ingesting.
        </div>
      )}

      {/* File upload drop zone */}
      {activeProject && (
        <div
          className={`border-2 border-dashed rounded p-4 text-center text-sm transition-colors ${
            dragging
              ? 'border-purple-400 bg-purple-50 dark:bg-purple-900/20'
              : 'border-gray-300 dark:border-gray-600 text-gray-500 dark:text-gray-400'
          }`}
          onDragOver={(e) => { e.preventDefault(); setDragging(true) }}
          onDragLeave={() => setDragging(false)}
          onDrop={handleDrop}
        >
          <p>Drop markdown / text files here to add to <strong>{activeProject.name}</strong> Clippings</p>
          <p className="mt-2 text-xs text-gray-400 dark:text-gray-500">or</p>
          <button
            type="button"
            onClick={() => fileInputRef.current?.click()}
            className="mt-2 px-3 py-1.5 text-xs border border-gray-300 dark:border-gray-600 rounded hover:bg-gray-100 dark:hover:bg-gray-700 dark:text-gray-300"
          >
            Browse files…
          </button>
          <input
            ref={fileInputRef}
            type="file"
            multiple
            className="hidden"
            accept=".md,.txt,.docx,.pdf"
            onChange={handleBrowseFiles}
          />
        </div>
      )}

      {/* File list */}
      {files.length > 0 && (
        <>
          <div className="flex items-center justify-between text-xs text-gray-500 dark:text-gray-400 px-1">
            <span>{selectedFiles.length}/{files.length} selected</span>
            <div className="flex gap-2">
              <button
                type="button"
                onClick={() => setSelectedFiles(files.map((f) => f.path))}
                className="underline hover:text-gray-700 dark:hover:text-gray-200"
              >
                Select All
              </button>
              <span>·</span>
              <button
                type="button"
                onClick={() => setSelectedFiles([])}
                className="underline hover:text-gray-700 dark:hover:text-gray-200"
              >
                Deselect All
              </button>
            </div>
          </div>
          <div className="space-y-1 max-h-48 overflow-y-auto border border-gray-200 dark:border-gray-700 rounded p-2">
            {files.map((f) => (
            <div key={f.path} className="flex items-center gap-2 text-xs hover:bg-gray-50 dark:hover:bg-gray-800 px-1 py-0.5 rounded group">
              <input
                type="checkbox"
                checked={selectedFiles.includes(f.path)}
                onChange={() => toggleFile(f.path)}
                className="cursor-pointer"
              />
              <span className="flex-1 truncate dark:text-gray-200 cursor-pointer" onClick={() => toggleFile(f.path)}>{f.name}</span>
              <span
                className={`px-1.5 py-0.5 rounded text-xs ${
                  f.status === 'ingested'
                    ? 'bg-green-100 text-green-700 dark:bg-green-900/40 dark:text-green-400'
                    : 'bg-gray-100 text-gray-500 dark:bg-gray-700 dark:text-gray-400'
                }`}
              >
                {f.status === 'ingested' ? 'done' : 'pending'}
              </span>
              <button
                type="button"
                title="Remove this file"
                onClick={() => handleRemoveFile(f.path, f.name)}
                disabled={isStreaming}
                className="opacity-0 group-hover:opacity-100 text-gray-400 hover:text-red-500 dark:hover:text-red-400 transition-opacity disabled:cursor-not-allowed"
              >
                🗑
              </button>
            </div>
            ))}
          </div>
        </>
      )}

      {/* Progress bar */}
      {isStreaming && progress.total > 0 && (
        <div className="space-y-1">
          <div className="flex justify-between text-xs text-gray-500 dark:text-gray-400">
            <span>{progress.currentFile ? `Processing: ${progress.currentFile.split(/[\/\\]/).pop()}` : 'Working…'}</span>
            <span>{progress.current} / {progress.total}</span>
          </div>
          <div className="w-full bg-gray-200 dark:bg-gray-700 rounded-full h-2">
            <div
              className="bg-purple-600 h-2 rounded-full transition-all duration-300"
              style={{ width: `${Math.round((progress.current / progress.total) * 100)}%` }}
            />
          </div>
        </div>
      )}

      {/* Action buttons */}
      {activeProject && (
        <div className="flex gap-3 items-center">
          <button
            onClick={() => handleRun(false)}
            disabled={isStreaming || selectedFiles.length === 0 || !llmConnected}
            title={!llmConnected ? 'Connect LLM first' : selectedFiles.length === 0 ? 'Select files above first' : undefined}
            className="px-4 py-2 bg-purple-600 hover:bg-purple-700 disabled:opacity-40 text-white rounded text-sm"
          >
            {isStreaming
              ? progress.total > 0
                ? `Running… ${progress.current} / ${progress.total}`
                : 'Running…'
              : `Ingest Selected${selectedFiles.length > 0 ? ` (${selectedFiles.length})` : ''}`}
          </button>
          <button
            onClick={() => handleRun(true)}
            disabled={isStreaming || !llmConnected}
            title={!llmConnected ? 'Connect LLM first' : undefined}
            className="px-4 py-2 border border-gray-300 dark:border-gray-600 hover:bg-gray-50 dark:hover:bg-gray-700 disabled:opacity-40 rounded text-sm dark:text-gray-100"
          >
            Rebuild Entire Wiki
          </button>
          {isStreaming && (
            <button
              onClick={handleStop}
              className="px-4 py-2 bg-red-600 hover:bg-red-700 text-white rounded text-sm"
            >
              ⏹ Stop
            </button>
          )}
        </div>
      )}

      <StreamingOutput lines={lines} isStreaming={isStreaming} />
    </div>
  )
}
