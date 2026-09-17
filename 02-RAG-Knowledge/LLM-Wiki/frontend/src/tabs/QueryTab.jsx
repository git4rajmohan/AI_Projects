import { useState, useRef, useEffect, useCallback } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import useAppStore from '../store/appStore'

export default function QueryTab() {
  const { activeProject, chatHistory, appendChatMessage, updateLastAssistantMessage, setLastAssistantMessage, clearChat, setActivePage, llmConnected } = useAppStore()
  const [input, setInput] = useState('')
  const [isStreaming, setIsStreaming] = useState(false)
  const [citations, setCitations] = useState([])
  const [lastAnswer, setLastAnswer] = useState('')
  const [confidence, setConfidence] = useState(null)
  const [queryMode, setQueryMode] = useState('wiki') // 'wiki' | 'general'
  const [retrievalMode, setRetrievalMode] = useState('keyword') // 'keyword' | 'semantic'
  const [attachedImages, setAttachedImages] = useState([]) // [{url, filename}]
  const bottomRef = useRef(null)
  const textareaRef = useRef(null)
  const fileInputRef = useRef(null)

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [chatHistory])

  const uploadImage = async (file) => {
    const formData = new FormData()
    formData.append('file', file)
    try {
      const res = await fetch('/api/query/upload-image', {
        method: 'POST',
        body: formData,
      })
      const data = await res.json()
      if (res.ok) {
        setAttachedImages((prev) => [...prev, { url: data.url, filename: data.filename }])
      }
    } catch (e) {
      console.error('Image upload failed:', e)
    }
  }

  const handlePaste = useCallback((e) => {
    const items = e.clipboardData?.items
    if (!items) return
    for (const item of items) {
      if (item.type.startsWith('image/')) {
        e.preventDefault()
        const file = item.getAsFile()
        if (file) uploadImage(file)
      }
    }
  }, [])

  const handleFileSelect = (e) => {
    const files = e.target.files
    if (files) {
      for (const file of files) {
        if (file.type.startsWith('image/')) {
          uploadImage(file)
        }
      }
    }
    e.target.value = '' // reset
  }

  const removeImage = (url) => {
    setAttachedImages((prev) => prev.filter((img) => img.url !== url))
  }

  const handleImageError = (url) => {
    setAttachedImages((prev) => prev.filter((img) => img.url !== url))
  }

  const handleSend = async () => {
    const canSend = queryMode === 'general'
      ? (input.trim() || attachedImages.length > 0) && !isStreaming && llmConnected
      : (input.trim() || attachedImages.length > 0) && !isStreaming && activeProject && llmConnected
    if (!canSend) return

    const question = input.trim()
    setInput('')
    setCitations([])
    setLastAnswer('')
    setConfidence(null)

    // Build content — string if no images, list of parts if images
    let userContent
    if (attachedImages.length > 0) {
      userContent = []
      if (question) {
        userContent.push({ type: 'text', text: question })
      }
      for (const img of attachedImages) {
        userContent.push({ type: 'image_url', image_url: { url: img.url } })
      }
    } else {
      userContent = question
    }

    // Store display content for the chat UI
    const displayContent = attachedImages.length > 0
      ? { text: question, images: attachedImages.map((i) => i.url) }
      : question

    appendChatMessage({ role: 'user', content: displayContent })
    appendChatMessage({ role: 'assistant', content: '' })
    setIsStreaming(true)
    setAttachedImages([])

    // Build messages for API — convert display content back to API format for history
    const apiMessages = chatHistory.map((msg) => {
      if (typeof msg.content === 'object' && msg.content !== null && msg.content.images) {
        // Reconstruct content parts from display format
        const parts = []
        if (msg.content.text) parts.push({ type: 'text', text: msg.content.text })
        for (const imgUrl of msg.content.images) {
          parts.push({ type: 'image_url', image_url: { url: imgUrl } })
        }
        return { role: msg.role, content: parts }
      }
      return { role: msg.role, content: msg.content }
    })
    apiMessages.push({ role: 'user', content: userContent })

    let res
    try {
      res = await fetch('/api/query/', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          project_id: activeProject?.id,
          messages: apiMessages,
          mode: queryMode,
          retrieval_mode: retrievalMode,
        }),
      })
    } catch (err) {
      setLastAssistantMessage('⚠ Could not reach the server. Is the backend running?')
      setIsStreaming(false)
      return
    }

    if (!res.ok) {
      let errMsg = `⚠ Server error (${res.status})`
      try { const d = await res.json(); errMsg = `⚠ ${d.detail || errMsg}` } catch (_) {}
      setLastAssistantMessage(errMsg)
      setIsStreaming(false)
      return
    }

    const reader = res.body.getReader()
    const decoder = new TextDecoder()
    let buf = ''
    let fullAnswer = ''

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
            if (ev.type === 'token') {
              updateLastAssistantMessage(ev.token)
              fullAnswer += ev.token
            } else if (ev.type === 'confidence') {
              setConfidence({ ...ev.score, source: ev.source })
            } else if (ev.type === 'citations') {
              setCitations(ev.pages || [])
            } else if (ev.type === 'done') {
              // Strip '## Confidence: N' from the visible answer
              const cleaned = fullAnswer.replace(/##\s*Confidence:[^\n]*/gi, '').trim()
              if (cleaned !== fullAnswer) {
                setLastAssistantMessage(cleaned)
              }
              setLastAnswer(cleaned)
            }
          } catch (_) {}
        }
      }
    } catch (streamErr) {
      if (!fullAnswer) {
        setLastAssistantMessage('⚠ Connection lost while receiving response. Please try again.')
      }
    } finally {
      setIsStreaming(false)
    }
  }

  const handleKeyDown = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSend()
    }
  }

  const handleSaveAnalysis = async () => {
    if (!lastAnswer || !activeProject) return
    const title = prompt('Save analysis as (page title):')
    if (!title) return
    await fetch('/api/query/save-analysis', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        project_id: activeProject.id,
        title,
        content: lastAnswer,
      }),
    })
  }

  const openCitation = async (path) => {
    if (!activeProject) return
    const res = await fetch(
      `/api/wiki/page?project_id=${activeProject.id}&path=${encodeURIComponent(path)}`,
    )
    if (res.ok) setActivePage(await res.json())
  }

  const canSend = queryMode === 'general'
    ? llmConnected
    : activeProject && llmConnected

  return (
    <div className="flex h-full overflow-hidden">
      {/* Chat area */}
      <div className="flex-1 flex flex-col overflow-hidden">
        {/* Mode toggle */}
        <div className="flex items-center gap-2 px-4 py-2 border-b border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-800/50">
          <button
            onClick={() => setQueryMode('wiki')}
            className={`px-3 py-1 rounded text-xs font-medium transition-colors ${
              queryMode === 'wiki'
                ? 'bg-purple-600 text-white'
                : 'text-gray-500 dark:text-gray-400 hover:bg-gray-200 dark:hover:bg-gray-700'
            }`}
          >
            Query Wiki
          </button>
          <button
            onClick={() => setQueryMode('general')}
            className={`px-3 py-1 rounded text-xs font-medium transition-colors ${
              queryMode === 'general'
                ? 'bg-purple-600 text-white'
                : 'text-gray-500 dark:text-gray-400 hover:bg-gray-200 dark:hover:bg-gray-700'
            }`}
          >
            General LLM
          </button>
          <span className="text-xs text-gray-400 dark:text-gray-500 ml-2">
            {queryMode === 'wiki'
              ? 'Answers from your wiki knowledge base'
              : 'Direct Q&A with the selected LLM — no wiki context'}
          </span>
          {/* Right side: retrieval toggle (wiki mode only) + clear */}
          <div className="flex items-center gap-3 ml-auto">
            {queryMode === 'wiki' && (
              <div className="flex items-center gap-1">
                <span className="text-xs text-gray-400 dark:text-gray-500 mr-1">Retrieval:</span>
                <label className="flex items-center gap-1 cursor-pointer">
                  <input
                    type="radio"
                    name="retrievalMode"
                    value="keyword"
                    checked={retrievalMode === 'keyword'}
                    onChange={() => setRetrievalMode('keyword')}
                    className="w-3 h-3"
                  />
                  <span className="text-xs text-gray-600 dark:text-gray-400">Keyword (fast)</span>
                </label>
                <label className="flex items-center gap-1 cursor-pointer ml-2">
                  <input
                    type="radio"
                    name="retrievalMode"
                    value="semantic"
                    checked={retrievalMode === 'semantic'}
                    onChange={() => setRetrievalMode('semantic')}
                    className="w-3 h-3"
                  />
                  <span className="text-xs text-gray-600 dark:text-gray-400">Semantic (slower)</span>
                </label>
              </div>
            )}
            {chatHistory.length > 0 && (
              <button
                onClick={clearChat}
                className="px-2 py-1 text-xs text-gray-500 dark:text-gray-400 border border-gray-300 dark:border-gray-600 rounded hover:bg-red-50 hover:text-red-600 hover:border-red-300 dark:hover:bg-red-900/20 dark:hover:text-red-400 dark:hover:border-red-700 transition-colors"
              >
                Clear chat
              </button>
            )}
          </div>
        </div>

        {/* Messages */}
        <div className="flex-1 overflow-y-auto px-6 py-4 space-y-4">
          {chatHistory.length === 0 && (
            <div className="flex flex-col items-center justify-center h-full text-gray-400 dark:text-gray-600 text-sm space-y-2">
              <span>
                {!llmConnected
                  ? 'Connect an LLM to start querying'
                  : queryMode === 'wiki' && !activeProject
                    ? 'No project selected'
                    : queryMode === 'wiki'
                      ? 'Ask a question about your wiki…'
                      : 'Ask anything — the LLM will answer directly…'}
              </span>
              {queryMode === 'wiki' && !activeProject && (
                <span className="text-xs text-gray-400 dark:text-gray-500">
                  Use the <strong className="text-gray-500 dark:text-gray-400">Wiki</strong> dropdown in the header to select a project,
                  or go to <strong className="text-gray-500 dark:text-gray-400">Ingest</strong> to create or add one.
                </span>
              )}
              <span className="text-xs text-gray-400 dark:text-gray-600 flex items-center gap-1">
                <svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <path d="m21.44 11.05-9.19 9.19a6 6 0 0 1-8.49-8.49l9.19-9.19a4 4 0 0 1 5.66 5.66l-9.2 9.19a2 2 0 0 1-2.83-2.83l8.49-8.48" />
                </svg>
                Paste images with Ctrl+V or click the attach button
              </span>
              {queryMode === 'wiki' && activeProject && !llmConnected && (
                <span className="text-amber-500 dark:text-amber-400 text-xs">⚠ Go to Config → LLM Connection to set up your model</span>
              )}
            </div>
          )}
          {chatHistory.map((msg, i) => {
            const isLastMsg = i === chatHistory.length - 1
            const showMeta = !isStreaming && msg.role === 'assistant' && isLastMsg
            return (
              <ChatMessage
                key={i}
                msg={msg}
                isLast={isLastMsg}
                isStreaming={isStreaming}
                citations={showMeta ? citations : undefined}
                confidence={showMeta ? confidence : undefined}
                onCitationClick={openCitation}
                onSave={showMeta && lastAnswer ? handleSaveAnalysis : undefined}
              />
            )
          })}
          <div ref={bottomRef} />
        </div>

        {/* Attached images preview */}
        {attachedImages.length > 0 && (
          <div className="flex gap-2 px-4 py-2 border-t border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-800/50 flex-wrap">
            {attachedImages.map((img) => (
              <div key={img.url} className="relative group">
                <img
                  src={img.url}
                  alt={img.filename}
                  className="h-16 w-16 object-cover rounded border border-gray-300 dark:border-gray-600 bg-gray-200 dark:bg-gray-700"
                  onError={() => handleImageError(img.url)}
                />
                <button
                  onClick={() => removeImage(img.url)}
                  className="absolute -top-1 -right-1 bg-red-500 text-white rounded-full w-5 h-5 text-xs flex items-center justify-center opacity-0 group-hover:opacity-100 transition-opacity"
                >
                  ×
                </button>
              </div>
            ))}
          </div>
        )}

        {/* Input area */}
        <div className="border-t border-gray-200 dark:border-gray-700 p-4">
          <div className="flex gap-2">
            <textarea
              ref={textareaRef}
              className="flex-1 border border-gray-300 dark:border-gray-600 rounded px-3 py-2 text-sm resize-none bg-white dark:bg-gray-800 dark:text-gray-100 focus:outline-none focus:ring-1 focus:ring-purple-500"
              rows={2}
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={handleKeyDown}
              onPaste={handlePaste}
              placeholder={!llmConnected ? 'Connect LLM first…' : queryMode === 'general' ? 'Ask anything… (Enter to send, Shift+Enter for newline, Ctrl+V to paste image)' : 'Ask a question about your wiki… (Enter to send, Shift+Enter for newline, Ctrl+V to paste image)'}
              disabled={isStreaming || !canSend}
            />
            <div className="flex flex-col gap-1">
              <button
                onClick={() => fileInputRef.current?.click()}
                disabled={isStreaming || !canSend}
                title="Attach image"
                className="px-3 py-2 border border-gray-300 dark:border-gray-600 hover:bg-gray-50 dark:hover:bg-gray-700 rounded text-sm disabled:opacity-40 cursor-pointer"
              >
                <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="text-gray-600 dark:text-gray-300">
                  <path d="m21.44 11.05-9.19 9.19a6 6 0 0 1-8.49-8.49l9.19-9.19a4 4 0 0 1 5.66 5.66l-9.2 9.19a2 2 0 0 1-2.83-2.83l8.49-8.48" />
                </svg>
              </button>
              <input
                ref={fileInputRef}
                type="file"
                accept="image/*"
                multiple
                onChange={handleFileSelect}
                className="hidden"
              />
              <button
                onClick={handleSend}
                disabled={isStreaming || (!input.trim() && attachedImages.length === 0) || !canSend}
                title={!llmConnected ? 'Connect LLM first' : undefined}
                className="px-4 py-2 bg-purple-600 hover:bg-purple-700 disabled:opacity-40 text-white rounded text-sm cursor-pointer flex items-center gap-2"
              >
                {isStreaming && (
                  <svg className="animate-spin w-3 h-3 text-white" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
                    <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                    <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8z" />
                  </svg>
                )}
                {isStreaming ? 'Working…' : 'Send'}
              </button>
              <button
                onClick={clearChat}
                className="px-4 py-2 border border-gray-200 dark:border-gray-700 hover:bg-gray-50 dark:hover:bg-gray-800 rounded text-xs text-gray-500 dark:text-gray-400 cursor-pointer"
              >
                Clear
              </button>
            </div>
          </div>
        </div>
      </div>

    </div>
  )
}

function resolveWikiLinks(text) {
  // Convert [[path/slug]] → readable "Slug" plain text
  return text.replace(/\[\[([^\]]+)\]\]/g, (_, link) => {
    const slug = link.split('/').pop() // take last segment
    return slug.replace(/-/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase())
  })
}

function ChatMessage({ msg, isLast, isStreaming, citations, confidence, onCitationClick, onSave }) {
  const isUser = msg.role === 'user'
  const showCursor = isLast && isStreaming && !isUser

  let textContent = ''
  let images = []
  if (isUser && typeof msg.content === 'object' && msg.content !== null && msg.content.images) {
    textContent = msg.content.text || ''
    images = msg.content.images || []
  } else {
    textContent = isUser ? msg.content : resolveWikiLinks(msg.content)
  }

  if (!isUser && !textContent) {
    if (isLast && isStreaming) {
      return (
        <div className="flex justify-start">
          <div className="rounded-lg px-4 py-3 text-sm bg-gray-100 dark:bg-gray-800 text-gray-400 dark:text-gray-500 flex items-center gap-2">
            <span className="inline-flex gap-1">
              <span className="w-1.5 h-1.5 rounded-full bg-gray-400 dark:bg-gray-500 animate-bounce" style={{ animationDelay: '0ms' }} />
              <span className="w-1.5 h-1.5 rounded-full bg-gray-400 dark:bg-gray-500 animate-bounce" style={{ animationDelay: '150ms' }} />
              <span className="w-1.5 h-1.5 rounded-full bg-gray-400 dark:bg-gray-500 animate-bounce" style={{ animationDelay: '300ms' }} />
            </span>
            <span className="text-xs">Thinking…</span>
          </div>
        </div>
      )
    }
    return null
  }

  const displayText = showCursor ? textContent.trimEnd() + '▍' : textContent
  const showFooter = !isUser && !showCursor && (citations?.length > 0 || confidence || onSave)

  return (
    <div className={`flex ${isUser ? 'justify-end' : 'justify-start'}`}>
      <div
        className={`max-w-[80%] rounded-lg px-4 py-2 text-sm ${
          isUser
            ? 'bg-purple-600 text-white'
            : 'bg-gray-100 dark:bg-gray-800 text-gray-800 dark:text-gray-200'
        }`}
      >
        {isUser ? (
          <div>
            {images.length > 0 && (
              <div className="flex flex-wrap gap-2 mb-2">
                {images.map((url, idx) => (
                  <div key={idx} className="relative group">
                    <img
                      src={url}
                      alt={`Attached ${idx + 1}`}
                      className="max-h-32 rounded border border-white/20 bg-white/10"
                      onError={(e) => {
                        const wrapper = e.currentTarget.parentElement
                        if (wrapper) wrapper.style.display = 'none'
                      }}
                    />
                  </div>
                ))}
              </div>
            )}
            {textContent && <p className="whitespace-pre-wrap">{textContent}</p>}
          </div>
        ) : (
          <>
            <div className="prose prose-sm dark:prose-invert max-w-none">
              <ReactMarkdown remarkPlugins={[remarkGfm]}>{displayText}</ReactMarkdown>
            </div>
            {showFooter && (
              <div className="mt-3 pt-2 border-t border-gray-200 dark:border-gray-600 space-y-2">
                {confidence && (
                  <div className="flex items-center gap-2 flex-wrap">
                    <span className="text-xs text-gray-400 dark:text-gray-500">Confidence:</span>
                    <span className={`text-xs font-semibold ${
                      confidence.label === 'High' ? 'text-green-600 dark:text-green-400' :
                      confidence.label === 'Medium' ? 'text-yellow-600 dark:text-yellow-400' :
                      confidence.label === 'Low' ? 'text-orange-500 dark:text-orange-400' :
                      'text-red-500 dark:text-red-400'
                    }`}>
                      {confidence.label} ({confidence.score}%)
                    </span>
                    {onSave && (
                      <button
                        onClick={onSave}
                        className="ml-auto text-xs text-purple-600 dark:text-purple-400 hover:underline"
                      >
                        Save
                      </button>
                    )}
                  </div>
                )}
                {citations?.length > 0 && (
                  <div>
                    <div className="text-xs text-gray-400 dark:text-gray-500 mb-1">Sources:</div>
                    <div className="flex flex-wrap gap-1">
                      {citations.map((c, idx) => {
                        const path = typeof c === 'string' ? c : c.path
                        const title = typeof c === 'string'
                          ? c.split('/').pop()?.replace(/\.md$/, '').replace(/-/g, ' ')
                          : (c.title || c.path?.split('/').pop())
                        return (
                          <button
                            key={path || idx}
                            onClick={() => onCitationClick?.(path)}
                            className="text-xs text-purple-600 dark:text-purple-400 hover:underline bg-purple-50 dark:bg-purple-900/20 px-2 py-0.5 rounded-md"
                          >
                            {title}
                          </button>
                        )
                      })}
                    </div>
                  </div>
                )}
                {!confidence && onSave && (
                  <div className="flex justify-end">
                    <button
                      onClick={onSave}
                      className="text-xs text-purple-600 dark:text-purple-400 hover:underline"
                    >
                      Save
                    </button>
                  </div>
                )}
              </div>
            )}
          </>
        )}
      </div>
    </div>
  )
}