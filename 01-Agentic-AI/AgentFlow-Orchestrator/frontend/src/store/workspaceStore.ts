import { create } from 'zustand'
import { api } from '../services/api'
import type { Task, Plan, Execution, Approval, UploadedFile, ExecutionEvent } from '../types'

export type TimelineItem =
  | { kind: 'intent'; id: string; text: string; files: UploadedFile[] }
  | { kind: 'plan'; id: string; plan: Plan }
  | {
      kind: 'agent'
      id: string
      agentId: string
      name: string
      status: string
      toolCalls: number
      durationMs: number | null
      error: string | null
    }
  | { kind: 'approval'; id: string; approval: Approval }
  | { kind: 'result'; id: string; execution: Execution }

const TERMINAL_STATUSES = ['completed', 'failed', 'cancelled']

interface WorkspaceState {
  tasks: Task[]
  activeTaskId: string | null
  activePlanId: string | null
  activeExecutionId: string | null
  timeline: TimelineItem[]
  submitting: boolean
  error: string | null

  loadTasks: () => Promise<void>
  newTask: () => void
  selectTask: (taskId: string) => Promise<void>
  submitIntent: (text: string, files: UploadedFile[]) => Promise<void>
  approvePlan: (planId?: string) => Promise<void>
  rejectPlan: (planId?: string) => Promise<void>
  resolveApproval: (approvalId: string, decision: 'approve' | 'reject') => Promise<void>
}

// Module-level poll handle — not part of store state (avoids re-render churn).
let pollTimer: ReturnType<typeof setTimeout> | null = null

function stopPolling() {
  if (pollTimer) {
    clearTimeout(pollTimer)
    pollTimer = null
  }
}

function agentDisplayName(plan: Plan | undefined, agentId: string): string {
  const agents = (plan?.plan_data?.agents as { id: string; name: string }[]) || []
  return agents.find((a) => a.id === agentId)?.name || agentId
}

function upsertAgentItem(
  timeline: TimelineItem[],
  event: ExecutionEvent,
  plan: Plan | undefined
): TimelineItem[] {
  if (!event.agent_id) return timeline
  const agentId = event.agent_id
  const status =
    event.event_type === 'AGENT_STARTED'
      ? 'running'
      : event.event_type === 'AGENT_COMPLETED'
        ? 'completed'
        : event.event_type === 'AGENT_FAILED'
          ? 'failed'
          : null
  if (!status) return timeline

  const idx = timeline.findIndex((t) => t.kind === 'agent' && t.agentId === agentId)
  const toolCalls = (event.data?.tool_calls as number) ?? undefined
  const updated: TimelineItem = {
    kind: 'agent',
    id: `agent-${agentId}`,
    agentId,
    name: agentDisplayName(plan, agentId),
    status,
    toolCalls: toolCalls ?? (idx >= 0 ? (timeline[idx] as { toolCalls: number }).toolCalls : 0),
    durationMs: event.duration_ms ?? (idx >= 0 ? (timeline[idx] as { durationMs: number | null }).durationMs : null),
    error: event.error ?? (idx >= 0 ? (timeline[idx] as { error: string | null }).error : null),
  }

  if (idx >= 0) {
    const next = [...timeline]
    next[idx] = updated
    return next
  }
  return [...timeline, updated]
}

function upsertApprovalItems(timeline: TimelineItem[], approvals: Approval[]): TimelineItem[] {
  let next = timeline
  for (const approval of approvals) {
    const exists = next.some((t) => t.kind === 'approval' && t.approval.id === approval.id)
    if (exists) continue
    const agentId = (approval.context?.agent_id as string) || null
    const anchorIdx = agentId ? next.findIndex((t) => t.kind === 'agent' && t.agentId === agentId) : -1
    const item: TimelineItem = { kind: 'approval', id: approval.id, approval }
    if (anchorIdx >= 0) {
      next = [...next.slice(0, anchorIdx + 1), item, ...next.slice(anchorIdx + 1)]
    } else {
      next = [...next, item]
    }
  }
  return next
}

export const useWorkspaceStore = create<WorkspaceState>((set, get) => ({
  tasks: [],
  activeTaskId: null,
  activePlanId: null,
  activeExecutionId: null,
  timeline: [],
  submitting: false,
  error: null,

  loadTasks: async () => {
    try {
      const tasks = await api.listTasks()
      set({ tasks })
    } catch {
      // Non-fatal — history sidebar just stays empty.
    }
  },

  newTask: () => {
    stopPolling()
    set({ activeTaskId: null, activePlanId: null, activeExecutionId: null, timeline: [], error: null })
  },

  selectTask: async (taskId: string) => {
    stopPolling()
    set({ activeTaskId: taskId, activePlanId: null, activeExecutionId: null, timeline: [], error: null })
    try {
      const task = await api.getTask(taskId)
      let timeline: TimelineItem[] = [{ kind: 'intent', id: task.id, text: task.intent, files: [] }]

      const plans = await api.listPlans(taskId)
      const plan = plans[0]
      if (plan) {
        timeline = [...timeline, { kind: 'plan', id: plan.id, plan }]
        set({ activePlanId: plan.id })
      }

      const executions = await api.listExecutions(taskId)
      const execution = executions[0]
      if (execution) {
        set({ activeExecutionId: execution.id })
        const { events } = await api.getExecutionEvents(execution.id)
        for (const event of events) timeline = upsertAgentItem(timeline, event, plan)

        const { approvals } = await api.listApprovals(execution.id)
        timeline = upsertApprovalItems(timeline, approvals)

        if (TERMINAL_STATUSES.includes(execution.status)) {
          timeline = [...timeline, { kind: 'result', id: execution.id, execution }]
        }
        set({ timeline })

        if (!TERMINAL_STATUSES.includes(execution.status)) {
          pollExecution(set, get)
        }
      } else {
        set({ timeline })
      }
    } catch (err) {
      set({ error: err instanceof Error ? err.message : 'Failed to load task' })
    }
  },

  submitIntent: async (text: string, files: UploadedFile[]) => {
    stopPolling()
    set({ submitting: true, error: null })
    try {
      // Carry the previous turn's result forward as context so follow-ups like
      // "show the details of insight here" have something concrete to work with —
      // otherwise every send starts a fully isolated, context-free task.
      const { timeline: previousTimeline } = get()
      const lastResult = [...previousTimeline].reverse().find((t) => t.kind === 'result') as
        | Extract<TimelineItem, { kind: 'result' }>
        | undefined
      const lastResponse = lastResult
        ? Object.values((lastResult.execution.result?.outputs as Record<string, { response?: string }>) || {})
            .map((o) => o.response)
            .filter(Boolean)
            .join('\n\n')
        : ''

      let fullIntent = text
      if (files.length > 0) {
        fullIntent += `\n\nAttached files: ${files.map((f) => f.path).join(', ')}`
      }
      if (lastResponse) {
        fullIntent += `\n\nContext from the previous step in this conversation (the user may refer to this as "it", "this", or "here"):\n${lastResponse.slice(0, 3000)}`
      }

      const task = await api.createTask(fullIntent)
      set((s) => ({
        activeTaskId: task.id,
        activePlanId: null,
        activeExecutionId: null,
        timeline: [...s.timeline, { kind: 'intent', id: task.id, text, files }],
      }))
      get().loadTasks()

      const plan = await api.generatePlan(task.id)
      set((s) => ({ activePlanId: plan.id, timeline: [...s.timeline, { kind: 'plan', id: plan.id, plan }] }))
    } catch (err) {
      set({ error: err instanceof Error ? err.message : 'Failed to generate plan' })
    } finally {
      set({ submitting: false })
    }
  },

  approvePlan: async (planId?: string) => {
    const targetPlanId = planId ?? get().activePlanId
    if (!targetPlanId) return
    try {
      await api.approvePlan(targetPlanId)
      set((s) => ({
        timeline: s.timeline.map((t) =>
          t.kind === 'plan' && t.id === targetPlanId ? { ...t, plan: { ...t.plan, status: 'approved' } } : t
        ),
      }))
      const execution = await api.startExecution(targetPlanId)
      set({ activeExecutionId: execution.id })
      pollExecution(set, get)
    } catch (err) {
      set({ error: err instanceof Error ? err.message : 'Failed to approve plan' })
    }
  },

  rejectPlan: async (planId?: string) => {
    const targetPlanId = planId ?? get().activePlanId
    if (!targetPlanId) return
    try {
      await api.rejectPlan(targetPlanId)
      set((s) => ({
        timeline: s.timeline.map((t) =>
          t.kind === 'plan' && t.id === targetPlanId ? { ...t, plan: { ...t.plan, status: 'rejected' } } : t
        ),
      }))
    } catch (err) {
      set({ error: err instanceof Error ? err.message : 'Failed to reject plan' })
    }
  },

  resolveApproval: async (approvalId: string, decision: 'approve' | 'reject') => {
    set((s) => ({
      timeline: s.timeline.map((t) =>
        t.kind === 'approval' && t.approval.id === approvalId
          ? { ...t, approval: { ...t.approval, status: decision === 'approve' ? 'approved' : 'rejected' } }
          : t
      ),
    }))
    try {
      if (decision === 'approve') await api.approveRequest(approvalId)
      else await api.rejectRequest(approvalId)
    } catch (err) {
      set({ error: err instanceof Error ? err.message : `Failed to ${decision} request` })
    }
  },
}))

function pollExecution(set: (fn: (s: WorkspaceState) => Partial<WorkspaceState>) => void, get: () => WorkspaceState) {
  const tick = async () => {
    const { activeExecutionId } = get()
    if (!activeExecutionId) return
    try {
      const execution = await api.getExecution(activeExecutionId)
      const { events } = await api.getExecutionEvents(activeExecutionId)
      const { approvals } = await api.listApprovals(activeExecutionId)

      set((s) => {
        const plan = s.timeline.find((t) => t.kind === 'plan')?.plan
        let timeline = s.timeline
        for (const event of events) timeline = upsertAgentItem(timeline, event, plan)
        timeline = upsertApprovalItems(timeline, approvals)

        if (TERMINAL_STATUSES.includes(execution.status) && !timeline.some((t) => t.kind === 'result')) {
          timeline = [...timeline, { kind: 'result', id: execution.id, execution }]
        }
        return { timeline }
      })

      if (!TERMINAL_STATUSES.includes(execution.status)) {
        pollTimer = setTimeout(tick, 2000)
      } else {
        stopPolling()
      }
    } catch {
      // Transient network error — retry on the next tick rather than giving up.
      pollTimer = setTimeout(tick, 2000)
    }
  }
  pollTimer = setTimeout(tick, 1000)
}
