/* Wire types mirroring agent_core.api.schemas (the console's only contract). */

export interface RunUsage {
  input_tokens: number
  output_tokens: number
  total_tokens: number
  model_calls: number
  tool_calls: number
  duration_ms: number | null
}

export type RunStatus =
  | 'created'
  | 'planning'
  | 'running'
  | 'waiting_approval'
  | 'needs_input'
  | 'completed'
  | 'failed'
  | 'timeout'
  | 'cancelled'

export interface Run {
  id: string
  task_id: string
  agent_id: string
  parent_run_id: string | null
  thread_id: string | null
  status: RunStatus | string
  created_at: string
  finished_at: string | null
  error: string | null
  metadata: Record<string, unknown>
  usage: RunUsage | null
  output?: unknown
  input?: string
}

export interface RunEvent {
  id: string
  event_type: string
  run_id: string
  parent_run_id: string | null
  task_id: string | null
  agent_id: string | null
  timestamp: string
  duration_ms: number | null
  input: unknown
  output: unknown
  tool: string | null
  status: string | null
  error: string | null
  metadata: Record<string, unknown>
}

export interface Approval {
  id: string
  run_id: string
  agent_id: string
  kind: string
  action_id: string | null
  tool_name: string | null
  arguments: Record<string, unknown>
  risk_level: string
  question: string
  reason: string
  status: string
  created_at: string
  resolved_at: string | null
  resolved_by: string | null
  edited_arguments: Record<string, unknown> | null
  resolved_note: string | null
}

export interface Artifact {
  path: string
  size: number
}

export interface Agent {
  id: string
  name: string
  description: string
  model: string | null
  system_prompt: string
  skills: string[]
  tools: string[]
  subagents: unknown[]
  metadata: Record<string, unknown>
}

export interface Tool {
  name: string
  description: string
  risk_level: string
  source: string
  metadata: Record<string, unknown>
}

export interface Skill {
  id: string
  name: string
  version: string
  description: string
  path: string | null
}

export interface MCPServer {
  id: string
  name: string
  version: string
  description: string
  transport: string
  endpoint: string
  auth_ref: string | null
  status: string
  metadata: Record<string, unknown>
}

/** SSE event types the console subscribes to (mirrors the runtime trace vocabulary). */
export const EVENT_TYPES = [
  'run_started', 'run_finished', 'run_failed', 'run_cancelled', 'agent_started',
  'agent_thinking', 'agent_finished', 'subagent_started', 'subagent_finished',
  'skill_loaded', 'tool_requested', 'tool_started', 'tool_executed', 'tool_failed',
  'action_pending', 'action_approved', 'action_rejected', 'loop_detected',
  'budget_warning', 'run_status_changed',
] as const

export const TERMINAL_RUN_EVENTS = new Set(['run_finished', 'run_failed', 'run_cancelled'])

export const TERMINAL_RUN_STATUSES = new Set(['completed', 'failed', 'timeout', 'cancelled'])
