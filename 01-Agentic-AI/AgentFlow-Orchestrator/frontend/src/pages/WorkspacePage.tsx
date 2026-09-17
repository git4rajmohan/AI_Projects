import { useState, useRef, useEffect } from 'react'
import { useWorkspaceStore } from '../store/workspaceStore'
import HistorySidebar from '../components/HistorySidebar'
import IntentBubble from '../components/timeline/IntentBubble'
import PlanCard from '../components/timeline/PlanCard'
import AgentActivityCard from '../components/timeline/AgentActivityCard'
import ApprovalInlineCard from '../components/timeline/ApprovalInlineCard'
import ResultCard from '../components/timeline/ResultCard'
import type { UploadedFile } from '../types'

function WorkspacePage() {
  const { timeline, submitting, error, submitIntent } = useWorkspaceStore()
  const [text, setText] = useState('')
  const [files, setFiles] = useState<UploadedFile[]>([])
  const [uploading, setUploading] = useState(false)
  const fileInputRef = useRef<HTMLInputElement>(null)
  const bottomRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [timeline])

  const handleFileUpload = async (event: React.ChangeEvent<HTMLInputElement>) => {
    const selected = event.target.files
    if (!selected || selected.length === 0) return
    setUploading(true)
    try {
      for (const file of Array.from(selected)) {
        const formData = new FormData()
        formData.append('file', file)
        const response = await fetch('/api/files/upload', { method: 'POST', body: formData })
        if (!response.ok) continue
        const data = await response.json()
        setFiles((prev) => [...prev, data])
      }
    } finally {
      setUploading(false)
      if (fileInputRef.current) fileInputRef.current.value = ''
    }
  }

  const handleSubmit = async () => {
    if (!text.trim() || submitting) return
    const currentText = text.trim()
    const currentFiles = files
    setText('')
    setFiles([])
    await submitIntent(currentText, currentFiles)
  }

  return (
    <div className="flex h-[calc(100vh-56px)]">
      <HistorySidebar />

      <div className="flex-1 flex flex-col">
        {/* Timeline feed */}
        <div className="flex-1 overflow-y-auto px-6 py-6 space-y-4 max-w-3xl mx-auto w-full">
          {timeline.length === 0 && (
            <div className="text-center text-gray-400 mt-20">
              <p className="text-lg">What do you want to accomplish?</p>
              <p className="text-sm mt-2">Describe your goal below — AgentOS will plan, execute, and report back here.</p>
            </div>
          )}

          {timeline.map((item, index) => {
            const isNewTurn = item.kind === 'intent' && index > 0
            return (
              <div key={item.id}>
                {isNewTurn && <div className="border-t border-gray-200 my-6" />}
                {item.kind === 'intent' && <IntentBubble text={item.text} files={item.files} />}
                {item.kind === 'plan' && <PlanCard plan={item.plan} />}
                {item.kind === 'agent' && (
                  <AgentActivityCard
                    name={item.name}
                    status={item.status}
                    toolCalls={item.toolCalls}
                    durationMs={item.durationMs}
                    error={item.error}
                  />
                )}
                {item.kind === 'approval' && <ApprovalInlineCard approval={item.approval} />}
                {item.kind === 'result' && <ResultCard execution={item.execution} />}
              </div>
            )
          })}

          {submitting && <p className="text-sm text-gray-400 animate-pulse">Understanding intent and generating plan...</p>}
          {error && <div className="p-3 bg-red-50 border border-red-200 rounded text-red-700 text-sm">{error}</div>}
          <div ref={bottomRef} />
        </div>

        {/* Persistent input bar */}
        <div className="border-t border-gray-200 bg-white px-6 py-4">
          <div className="max-w-3xl mx-auto">
            {files.length > 0 && (
              <div className="flex flex-wrap gap-2 mb-2">
                {files.map((f) => (
                  <span key={f.filename} className="text-xs bg-blue-50 text-blue-700 px-2 py-1 rounded flex items-center gap-1">
                    📎 {f.filename}
                    <button onClick={() => setFiles((prev) => prev.filter((x) => x.filename !== f.filename))} className="text-blue-400 hover:text-red-500">
                      &times;
                    </button>
                  </span>
                ))}
              </div>
            )}
            <div className="flex items-end gap-2">
              <input
                ref={fileInputRef}
                type="file"
                multiple
                onChange={handleFileUpload}
                disabled={uploading}
                className="hidden"
                id="workspace-file-upload"
              />
              <label
                htmlFor="workspace-file-upload"
                className="px-3 py-3 border border-gray-300 rounded-lg text-gray-500 hover:bg-gray-50 cursor-pointer"
                title="Attach files"
              >
                {uploading ? '...' : '📎'}
              </label>
              <textarea
                value={text}
                onChange={(e) => setText(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' && !e.shiftKey) {
                    e.preventDefault()
                    handleSubmit()
                  }
                }}
                placeholder="e.g., Convert this CSV into an Excel file."
                rows={1}
                className="flex-1 px-4 py-3 border border-gray-300 rounded-lg resize-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
              />
              <button
                onClick={handleSubmit}
                disabled={submitting || !text.trim()}
                className="px-5 py-3 bg-blue-600 text-white rounded-lg font-medium hover:bg-blue-700 disabled:opacity-50"
              >
                Send
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}

export default WorkspacePage
