import { useEffect } from 'react'
import { useWorkspaceStore } from '../store/workspaceStore'

function HistorySidebar() {
  const { tasks, activeTaskId, loadTasks, selectTask, newTask } = useWorkspaceStore()

  useEffect(() => {
    loadTasks()
  }, [loadTasks])

  const statusColors: Record<string, string> = {
    created: 'bg-gray-100 text-gray-600',
    planning: 'bg-blue-100 text-blue-700',
    planned: 'bg-blue-100 text-blue-700',
    approved: 'bg-green-100 text-green-700',
    rejected: 'bg-red-100 text-red-700',
  }

  return (
    <aside className="w-64 shrink-0 bg-gray-50 border-r border-gray-200 flex flex-col h-full">
      <div className="p-3 border-b border-gray-200">
        <button
          onClick={newTask}
          className="w-full px-3 py-2 bg-blue-600 text-white rounded-lg text-sm font-medium hover:bg-blue-700"
        >
          + New Task
        </button>
      </div>
      <div className="flex-1 overflow-y-auto p-2 space-y-1">
        {tasks.length === 0 && <p className="text-xs text-gray-400 px-2 py-4">No tasks yet.</p>}
        {tasks.map((task) => (
          <button
            key={task.id}
            onClick={() => selectTask(task.id)}
            className={`w-full text-left px-3 py-2 rounded-lg text-sm transition-colors ${
              activeTaskId === task.id ? 'bg-blue-100 text-blue-900' : 'hover:bg-gray-100 text-gray-700'
            }`}
          >
            <p className="truncate">{task.intent.split('\n')[0]}</p>
            <span className={`inline-block mt-1 px-1.5 py-0.5 rounded text-[10px] ${statusColors[task.status] || 'bg-gray-100 text-gray-500'}`}>
              {task.status}
            </span>
          </button>
        ))}
      </div>
    </aside>
  )
}

export default HistorySidebar
