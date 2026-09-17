import { create } from 'zustand'
import { persist } from 'zustand/middleware'

const useAppStore = create(
  persist(
    (set, get) => ({
  // Projects
  projects: [],
  activeProject: null,

  // LLM config (masked from backend)
  llmConfig: {
    provider: 'local-cpu',
    model: 'gemma-2-2b-it',
    api_key: '',
    api_base: '',
    azure_deployment: '',
    azure_api_version: '',
    temperature: 0.3,
    max_tokens: 4000,
  },
  llmConnected: false, // true when LLM config is sufficient to attempt a connection

  // Wiki navigation
  activePage: null,       // { path, raw, frontmatter, content }
  pageHistory: [],

  // Chat
  chatHistory: [],        // [{ role, content }]

  // UI
  activeTab: 'config',

  // Actions
  setProjects: (projects) => set({ projects }),
  setActiveProject: (project) => {
    const { activeProject } = get()
    // If switching to a different project (or clearing), reset all project-scoped state
    if (project?.id !== activeProject?.id) {
      set({
        activeProject: project,
        activePage: null,
        pageHistory: [],
        chatHistory: [],
      })
    } else {
      set({ activeProject: project })
    }
  },
  setLLMConfig: (cfg) => set({ llmConfig: cfg }),
  setLLMConnected: (connected) => set({ llmConnected: connected }),

  setActivePage: (page) => {
    const { activePage, pageHistory } = get()
    const history = activePage
      ? [...pageHistory, activePage.path].slice(-30)
      : pageHistory
    set({ activePage: page, pageHistory: history })
  },

  navigateBack: () => {
    const { pageHistory } = get()
    if (pageHistory.length === 0) return null
    const path = pageHistory[pageHistory.length - 1]
    set({ pageHistory: pageHistory.slice(0, -1) })
    return path
  },

  appendChatMessage: (msg) =>
    set((s) => ({ chatHistory: [...s.chatHistory, msg] })),

  updateLastAssistantMessage: (token) =>
    set((s) => {
      const msgs = [...s.chatHistory]
      if (msgs.length > 0 && msgs[msgs.length - 1].role === 'assistant') {
        msgs[msgs.length - 1] = {
          ...msgs[msgs.length - 1],
          content: msgs[msgs.length - 1].content + token,
        }
      }
      return { chatHistory: msgs }
    }),

  setLastAssistantMessage: (content) =>
    set((s) => {
      const msgs = [...s.chatHistory]
      if (msgs.length > 0 && msgs[msgs.length - 1].role === 'assistant') {
        msgs[msgs.length - 1] = {
          ...msgs[msgs.length - 1],
          content,
        }
      }
      return { chatHistory: msgs }
    }),

  clearChat: () => set({ chatHistory: [] }),

  setActiveTab: (tab) => set({ activeTab: tab }),
}),
    {
      name: 'llmwikiui-store',
      // Only persist chat history and active project; skip transient UI state
      partialize: (state) => ({
        chatHistory: state.chatHistory,
        activeProject: state.activeProject,
      }),
    }
  )
)

export default useAppStore
