import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import useAppStore from '../store/appStore'
import BacklinksPanel from './BacklinksPanel'

// Render [[WikiLink]] syntax
function parseWikilinks(text) {
  // Split on [[...]] keeping the delimiters
  const parts = text.split(/(\[\[.*?\]\])/g)
  return parts.map((part, i) => {
    const match = part.match(/^\[\[(.*?)\]\]$/)
    if (match) {
      return { type: 'wikilink', slug: match[1], key: i }
    }
    return { type: 'text', text: part, key: i }
  })
}

function WikilinkRenderer({ slug }) {
  const { activeProject, setActivePage } = useAppStore()

  const handleClick = async () => {
    if (!activeProject) return
    // First try to resolve the wikilink to a path
    const res = await fetch(
      `/api/wiki/resolve?project_id=${activeProject.id}&slug=${encodeURIComponent(slug)}`,
    )
    if (res.ok) {
      const data = await res.json()
      if (data.path) {
        const pageRes = await fetch(
          `/api/wiki/page?project_id=${activeProject.id}&path=${encodeURIComponent(data.path)}`,
        )
        if (pageRes.ok) {
          const page = await pageRes.json()
          setActivePage(page)
          return
        }
      }
    }
  }

  return (
    <button
      onClick={handleClick}
      className="text-purple-600 dark:text-purple-400 hover:underline"
    >
      {slug}
    </button>
  )
}

// Custom paragraph renderer that handles [[wikilinks]]
function ParagraphWithWikilinks({ children }) {
  if (typeof children === 'string') {
    const parts = parseWikilinks(children)
    if (parts.some((p) => p.type === 'wikilink')) {
      return (
        <p>
          {parts.map((p) =>
            p.type === 'wikilink' ? (
              <WikilinkRenderer key={p.key} slug={p.slug} />
            ) : (
              p.text
            ),
          )}
        </p>
      )
    }
  }
  return <p>{children}</p>
}

export default function MarkdownViewer() {
  const { activePage, navigateBack, activeProject, setActivePage } = useAppStore()

  if (!activePage) {
    return (
      <div className="flex items-center justify-center h-full text-gray-400 dark:text-gray-600 text-sm">
        Select a page from the sidebar
      </div>
    )
  }

  const handleBack = async () => {
    const prevPath = navigateBack()
    if (prevPath && activeProject) {
      const res = await fetch(
        `/api/wiki/page?project_id=${activeProject.id}&path=${encodeURIComponent(prevPath)}`,
      )
      if (res.ok) setActivePage(await res.json())
    }
  }

  const { frontmatter, content, path } = activePage

  return (
    <div className="h-full overflow-y-auto px-8 py-6 max-w-4xl mx-auto">
      {/* Back button */}
      <button
        onClick={handleBack}
        className="text-xs text-gray-400 hover:text-gray-600 dark:hover:text-gray-200 mb-4 flex items-center gap-1"
      >
        ← Back
      </button>

      {/* Frontmatter card */}
      {frontmatter && Object.keys(frontmatter).length > 0 && (
        <div className="mb-6 rounded border border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-800/50 px-4 py-3 text-xs text-gray-600 dark:text-gray-400 grid grid-cols-2 gap-x-4 gap-y-1">
          {Object.entries(frontmatter).map(([k, v]) => (
            <div key={k} className="flex gap-1">
              <span className="font-medium">{k}:</span>
              <span className="truncate">{Array.isArray(v) ? v.join(', ') : String(v)}</span>
            </div>
          ))}
        </div>
      )}

      {/* Markdown content */}
      <article className="prose dark:prose-invert prose-sm max-w-none prose-purple">
        <ReactMarkdown
          remarkPlugins={[remarkGfm]}
          components={{
            p: ParagraphWithWikilinks,
            a: ({ href, children }) => (
              <a href={href} target="_blank" rel="noopener noreferrer" className="text-purple-600 dark:text-purple-400 hover:underline">
                {children}
              </a>
            ),
          }}
        >
          {content || ''}
        </ReactMarkdown>
      </article>

      <BacklinksPanel pagePath={path} />
    </div>
  )
}
