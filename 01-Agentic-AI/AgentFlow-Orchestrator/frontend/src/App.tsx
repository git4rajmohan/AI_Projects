import { useState } from 'react'
import WorkspacePage from './pages/WorkspacePage'
import RegistryDrawer, { type RegistryPanel } from './components/RegistryDrawer'

const registryIcons: { panel: Exclude<RegistryPanel, null>; label: string; icon: string }[] = [
  { panel: 'skills', label: 'Skills', icon: '🧩' },
  { panel: 'agents', label: 'Agents', icon: '🤖' },
  { panel: 'tools', label: 'Tools', icon: '🛠️' },
]

function App() {
  const [drawer, setDrawer] = useState<RegistryPanel>(null)

  return (
    <div className="min-h-screen flex flex-col">
      {/* Header */}
      <header className="bg-gray-900 text-white px-6 py-3 flex items-center justify-between h-14">
        <h1 className="text-xl font-bold">AgentOS</h1>
        <nav className="flex gap-1">
          {registryIcons.map((item) => (
            <button
              key={item.panel}
              onClick={() => setDrawer(item.panel)}
              className="px-3 py-1.5 rounded text-sm text-gray-300 hover:text-white hover:bg-gray-800"
              title={item.label}
            >
              {item.icon} {item.label}
            </button>
          ))}
        </nav>
      </header>

      {/* Main content */}
      <main className="flex-1">
        <WorkspacePage />
      </main>

      <RegistryDrawer panel={drawer} onClose={() => setDrawer(null)} />
    </div>
  )
}

export default App