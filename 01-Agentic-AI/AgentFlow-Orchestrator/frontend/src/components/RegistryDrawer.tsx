import SkillsPage from '../pages/SkillsPage'
import AgentsPage from '../pages/AgentsPage'
import ToolsPage from '../pages/ToolsPage'

export type RegistryPanel = 'skills' | 'agents' | 'tools' | null

interface Props {
  panel: RegistryPanel
  onClose: () => void
}

const PANELS: Record<'skills' | 'agents' | 'tools', { title: string; render: () => JSX.Element }> = {
  skills: { title: 'Skills', render: () => <SkillsPage /> },
  agents: { title: 'Agents', render: () => <AgentsPage /> },
  tools: { title: 'Tools', render: () => <ToolsPage /> },
}

function RegistryDrawer({ panel, onClose }: Props) {
  if (!panel) return null
  const { title, render } = PANELS[panel]

  return (
    <div className="fixed inset-0 z-40 flex justify-end">
      <div className="absolute inset-0 bg-black/30" onClick={onClose} />
      <div className="relative w-full max-w-2xl bg-gray-100 h-full overflow-y-auto shadow-2xl p-6">
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-xl font-bold text-gray-800">{title}</h2>
          <button onClick={onClose} className="text-gray-500 hover:text-gray-800 text-2xl leading-none">
            &times;
          </button>
        </div>
        {render()}
      </div>
    </div>
  )
}

export default RegistryDrawer
