import { useEffect, useState } from 'react'
import useAppStore from '../store/appStore'

export default function BacklinksPanel({ pagePath }) {
  const { activeProject } = useAppStore()
  const [links, setLinks] = useState([])

  useEffect(() => {
    if (!pagePath || !activeProject) return
    fetch(`/api/wiki/backlinks?project_id=${activeProject.id}&path=${encodeURIComponent(pagePath)}`)
      .then((r) => r.json())
      .then((d) => setLinks(d.backlinks || []))
      .catch(() => setLinks([]))
  }, [pagePath, activeProject?.id])

  if (links.length === 0) return null

  return (
    <div className="border-t border-gray-200 dark:border-gray-700 pt-3 mt-4">
      <h3 className="text-xs font-semibold uppercase tracking-wider text-gray-400 dark:text-gray-500 mb-2">
        Backlinks
      </h3>
      <ul className="space-y-1">
        {links.map((l) => (
          <li key={l.path} className="text-xs">
            <BacklinkItem link={l} />
          </li>
        ))}
      </ul>
    </div>
  )
}

function BacklinkItem({ link }) {
  const { setActivePage, activeProject } = useAppStore()

  const handleClick = async () => {
    if (!activeProject) return
    const res = await fetch(
      `/api/wiki/page?project_id=${activeProject.id}&path=${encodeURIComponent(link.path)}`,
    )
    if (res.ok) {
      const data = await res.json()
      setActivePage(data)
    }
  }

  return (
    <button
      onClick={handleClick}
      className="text-purple-600 dark:text-purple-400 hover:underline truncate max-w-full block"
    >
      {link.title || link.path}
    </button>
  )
}
