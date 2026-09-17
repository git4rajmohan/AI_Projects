import { useState, useEffect } from 'react'
import useAppStore from '../store/appStore'

function TreeNode({ node, depth = 0, onSelect, activePath }) {
  const [open, setOpen] = useState(depth < 2)
  const isDir = node.type === 'dir'
  const isActive = activePath === node.path

  return (
    <div>
      <button
        onClick={() => {
          if (isDir) setOpen((o) => !o)
          else onSelect(node.path)
        }}
        style={{ paddingLeft: `${depth * 12 + 8}px` }}
        className={`w-full text-left flex items-center gap-1 py-0.5 pr-2 text-xs rounded hover:bg-gray-100 dark:hover:bg-gray-800 ${
          isActive ? 'bg-purple-50 dark:bg-purple-900/30 text-purple-700 dark:text-purple-300 font-medium' : 'text-gray-700 dark:text-gray-300'
        }`}
      >
        {isDir ? (
          <span className="text-gray-400">{open ? '▾' : '▸'}</span>
        ) : (
          <span className="text-gray-300 dark:text-gray-600">·</span>
        )}
        <span className="truncate">{node.name}</span>
      </button>
      {isDir && open && node.children && (
        <div>
          {node.children.map((child) => (
            <TreeNode
              key={child.path}
              node={child}
              depth={depth + 1}
              onSelect={onSelect}
              activePath={activePath}
            />
          ))}
        </div>
      )}
    </div>
  )
}

export default function FileTree({ onSelect }) {
  const { activeProject, activePage } = useAppStore()
  const [tree, setTree] = useState(null)
  const [search, setSearch] = useState('')
  const [searchResults, setSearchResults] = useState(null)

  useEffect(() => {
    if (!activeProject) return
    fetch(`/api/wiki/tree?project_id=${activeProject.id}`)
      .then((r) => r.json())
      .then((d) => setTree(d.name ? d : null))
      .catch(() => {})
  }, [activeProject?.id])

  useEffect(() => {
    if (!search || !activeProject) {
      setSearchResults(null)
      return
    }
    const timer = setTimeout(async () => {
      const res = await fetch(
        `/api/wiki/search?project_id=${activeProject.id}&q=${encodeURIComponent(search)}`,
      )
      if (res.ok) {
        const d = await res.json()
        setSearchResults(d.results || [])
      }
    }, 300)
    return () => clearTimeout(timer)
  }, [search, activeProject?.id])

  return (
    <div className="flex flex-col h-full">
      <div className="p-2">
        <input
          className="w-full text-xs border border-gray-200 dark:border-gray-700 rounded px-2 py-1 bg-white dark:bg-gray-800 dark:text-gray-100 placeholder-gray-400"
          placeholder="Search wiki…"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
      </div>

      <div className="flex-1 overflow-y-auto">
        {search && searchResults ? (
          searchResults.length === 0 ? (
            <p className="text-xs text-gray-400 px-3 py-2">No results</p>
          ) : (
            searchResults.map((r) => (
              <button
                key={r.path}
                onClick={() => onSelect(r.path)}
                className="w-full text-left px-3 py-1 text-xs hover:bg-gray-100 dark:hover:bg-gray-800 dark:text-gray-300"
              >
                <div className="font-medium truncate">{r.title || r.path}</div>
                <div className="text-gray-400 truncate">{r.excerpt}</div>
              </button>
            ))
          )
        ) : tree ? (
          tree.children?.map((node) => (
            <TreeNode
              key={node.path}
              node={node}
              depth={0}
              onSelect={onSelect}
              activePath={activePage?.path}
            />
          ))
        ) : (
          <p className="text-xs text-gray-400 px-3 py-2">No wiki loaded</p>
        )}
      </div>
    </div>
  )
}
