/* Small display helpers shared across the console. */

import type { RunStatus } from './types'

export function fmtTime(iso: string): string {
  return new Date(iso).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })
}

export function fmtTimeShort(iso: string): string {
  return new Date(iso).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
}

export function fmtDateTime(iso: string): string {
  return new Date(iso).toLocaleString([], {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  })
}

export function fmtSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1048576) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / 1048576).toFixed(1)} MB`
}

export function fmtDuration(ms: number): string {
  if (ms < 1000) return `${Math.round(ms)}ms`
  return `${Math.round(ms / 1000)}s`
}

export function str(value: unknown): string {
  if (value == null) return ''
  return typeof value === 'string' ? value : JSON.stringify(value)
}

export const STATUS_STYLES: Record<string, string> = {
  completed: 'bg-emerald-500/15 text-emerald-700 dark:text-emerald-400 border-emerald-500/30',
  failed: 'bg-red-500/15 text-red-700 dark:text-red-400 border-red-500/30',
  timeout: 'bg-red-500/15 text-red-700 dark:text-red-400 border-red-500/30',
  cancelled: 'bg-zinc-500/15 text-zinc-600 dark:text-zinc-400 border-zinc-500/30',
  needs_input: 'bg-amber-500/15 text-amber-700 dark:text-amber-400 border-amber-500/30',
  waiting_approval: 'bg-amber-500/15 text-amber-700 dark:text-amber-400 border-amber-500/30',
  running: 'bg-blue-500/15 text-blue-700 dark:text-blue-400 border-blue-500/30',
  planning: 'bg-blue-500/15 text-blue-700 dark:text-blue-400 border-blue-500/30',
  created: 'bg-zinc-500/15 text-zinc-600 dark:text-zinc-400 border-zinc-500/30',
}

/* Compact status dot for the sidebar run list. */
export const STATUS_DOT: Record<string, string> = {
  completed: 'bg-emerald-500',
  failed: 'bg-red-500',
  timeout: 'bg-red-500',
  cancelled: 'bg-zinc-400 dark:bg-zinc-600',
  needs_input: 'bg-amber-500',
  waiting_approval: 'bg-amber-500',
  running: 'bg-blue-500',
  planning: 'bg-blue-500',
  created: 'bg-zinc-400 dark:bg-zinc-600',
}

export const STATUS_LABELS: Record<RunStatus | string, string> = {
  completed: '已完成',
  failed: '失败',
  timeout: '超时',
  cancelled: '已取消',
  needs_input: '待输入',
  waiting_approval: '待审批',
  running: '运行中',
  planning: '规划中',
  created: '已创建',
}

export function eventColor(kind: string): string {
  if (kind.startsWith('tool_failed') || kind.includes('rejected')) return 'text-red-500'
  if (kind.endsWith('_finished') || kind.includes('approved')) return 'text-emerald-600 dark:text-emerald-400'
  if (kind.startsWith('tool_')) return 'text-violet-600 dark:text-violet-400'
  if (kind.startsWith('run_')) return 'text-blue-600 dark:text-blue-400'
  return 'text-zinc-500'
}
