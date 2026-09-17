// TypeScript types matching backend Pydantic models

export interface Task {
  id: string
  intent: string
  status: string
  user_id: string | null
  created_at: string | null
  updated_at: string | null
}

export interface UploadedFile {
  filename: string
  path: string
  size_bytes: number
}

export interface AgentSpec {
  id: string
  name: string
  description: string
  goal: string
  model: string
  system_prompt: string
  tools: string[]
  skills: string[]
  memory_scopes: string[]
  input_schema: Record<string, unknown>
  output_schema: Record<string, unknown>
  dependencies: string[]
  max_iterations: number
  max_tool_calls: number
  timeout_seconds: number
  requires_human_approval: boolean
}

export interface PlanSpec {
  task_id: string
  objective: string
  summary: string
  agents: AgentSpec[]
  workflow: {
    type: string
    nodes: Record<string, unknown>[]
    edges: Record<string, unknown>[]
  }
  memory: {
    scope: string
    working_memory: boolean
    long_term_memory: boolean
  }
  evaluation: {
    criteria: string[]
    threshold: number
  }
  permissions: Record<string, unknown>
  estimated_cost: number
  estimated_duration_seconds: number
  requires_approval: boolean
  matched_skills: string[]
}

export interface Plan {
  id: string
  task_id: string
  objective: string
  summary: string
  status: string
  estimated_cost: number
  estimated_duration_seconds: number
  requires_approval: boolean
  plan_data: Record<string, unknown>
  matched_skills?: { skill_id: string; skill_name: string; version: string; score: number; description: string }[]
}

export interface Skill {
  id: string
  name: string
  description: string
  author: string | null
  tags: string[]
  enabled: boolean
  usage_count: number
  success_count: number
  failure_count: number
  avg_duration_seconds: number
  avg_cost: number
  evaluation_score: number
  created_at: string | null
  updated_at: string | null
}

export interface Tool {
  id: string
  name: string
  description: string
  permission_level: string
  input_schema: Record<string, unknown>
  output_schema: Record<string, unknown>
  enabled: boolean
}

export interface Execution {
  id: string
  task_id: string
  plan_id: string
  status: string
  state: Record<string, unknown>
  total_duration_seconds: number | null
  total_cost: number | null
  total_tool_calls: number
  result: Record<string, unknown> | null
  error: string | null
  created_at: string | null
  started_at: string | null
  completed_at: string | null
}

export interface ExecutionEvent {
  id: string
  execution_id: string
  event_type: string
  agent_id: string | null
  tool_id: string | null
  status: string | null
  duration_ms: number | null
  error: string | null
  data: Record<string, unknown> | null
  timestamp: string | null
}

export interface HealthStatus {
  status: string
  service: string
  version: string
  timestamp: string
}

export interface Approval {
  id: string
  task_id: string | null
  execution_id: string | null
  approval_type: string
  status: string
  context: Record<string, unknown>
  user_id: string | null
  created_at: string | null
  resolved_at: string | null
}