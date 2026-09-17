// API client service for AgentOS backend

import type {
  Task,
  Plan,
  Skill,
  Tool,
  Execution,
  ExecutionEvent,
  HealthStatus,
  Approval,
} from '../types'

const API_BASE = '/api'

async function fetchJSON<T>(url: string, options?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${url}`, {
    headers: { 'Content-Type': 'application/json' },
    ...options,
  })
  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: response.statusText }))
    throw new Error(error.detail || `HTTP ${response.status}`)
  }
  return response.json()
}

export const api = {
  // Health
  health: () => fetchJSON<HealthStatus>('/../health'),

  // Tasks
  createTask: (intent: string, userId?: string) =>
    fetchJSON<Task>('/tasks', {
      method: 'POST',
      body: JSON.stringify({ intent, user_id: userId }),
    }),
  getTask: (id: string) => fetchJSON<Task>(`/tasks/${id}`),
  listTasks: (limit = 50) => fetchJSON<Task[]>(`/tasks?limit=${limit}`),

  // Plans
  generatePlan: (taskId: string) =>
    fetchJSON<Plan>('/plans', {
      method: 'POST',
      body: JSON.stringify({ task_id: taskId }),
    }),
  getPlan: (id: string) => fetchJSON<Plan>(`/plans/${id}`),
  listPlans: (taskId?: string) =>
    fetchJSON<Plan[]>(taskId ? `/plans?task_id=${taskId}` : '/plans'),
  approvePlan: (id: string) =>
    fetchJSON<{ status: string }>(`/plans/${id}/approve`, { method: 'POST' }),
  rejectPlan: (id: string) =>
    fetchJSON<{ status: string }>(`/plans/${id}/reject`, { method: 'POST' }),

  // Skills
  listSkills: () => fetchJSON<Skill[]>('/skills'),
  getSkill: (id: string) => fetchJSON<Skill>(`/skills/${id}`),

  // Agents
  listAgents: () => fetchJSON<unknown[]>('/agents'),

  // Tools
  listTools: () => fetchJSON<Tool[]>('/tools'),

  // Executions
  startExecution: (planId: string) =>
    fetchJSON<Execution>('/executions', {
      method: 'POST',
      body: JSON.stringify({ plan_id: planId }),
    }),
  getExecution: (id: string) => fetchJSON<Execution>(`/executions/${id}`),
  listExecutions: (taskId?: string) =>
    fetchJSON<Execution[]>(taskId ? `/executions?task_id=${taskId}` : '/executions'),
  getExecutionEvents: (id: string) =>
    fetchJSON<{ execution_id: string; events: ExecutionEvent[]; count: number }>(`/executions/${id}/events`),

  // Approvals
  listApprovals: (executionId?: string) =>
    fetchJSON<{ approvals: Approval[]; count: number }>(
      executionId ? `/approvals?execution_id=${executionId}` : '/approvals'
    ),
  approveRequest: (id: string, userId?: string) =>
    fetchJSON<Record<string, unknown>>(`/approvals/${id}/approve`, {
      method: 'POST',
      body: JSON.stringify({ user_id: userId }),
    }),
  rejectRequest: (id: string, userId?: string) =>
    fetchJSON<Record<string, unknown>>(`/approvals/${id}/reject`, {
      method: 'POST',
      body: JSON.stringify({ user_id: userId }),
    }),
}