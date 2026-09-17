import { useEffect, useRef } from 'react'

/**
 * StreamingOutput — scrolling log panel for SSE events.
 * Props:
 *   lines: string[]   — array of log lines to display
 *   isStreaming: bool — show spinner when true
 */
export default function StreamingOutput({ lines = [], isStreaming = false }) {
  const bottomRef = useRef(null)

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [lines])

  if (lines.length === 0 && !isStreaming) return null

  return (
    <div className="mt-3 rounded border border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-900 overflow-y-auto max-h-64 p-3 font-mono text-xs">
      {lines.map((line, i) => (
        <div key={i} className="whitespace-pre-wrap text-gray-700 dark:text-gray-300">
          {line}
        </div>
      ))}
      {isStreaming && (
        <div className="text-purple-500 animate-pulse">▋</div>
      )}
      <div ref={bottomRef} />
    </div>
  )
}
