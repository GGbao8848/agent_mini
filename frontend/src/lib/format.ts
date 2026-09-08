/* Small display helpers shared across the console. */

import type { RunStatus } from './types'

export function fmtTime(iso: string): string {
  return new Date(iso).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })
}

/** Relative age for compact list rows: 刚刚 / n分 / n时 / n天 / n月 / n年 —
 *  the largest unit that fits, relative to now. Day/month/year buckets are
 *  calendar-accurate, not 30-day approximations. */
export function fmtTimeShort(iso: string): string {
  const then = new Date(iso)
  const now = new Date()
  const diffMs = now.getTime() - then.getTime()
  if (diffMs < 60_000) return '刚刚'
  const minutes = Math.floor(diffMs / 60_000)
  if (minutes < 60) return `${minutes}分`
  const hours = Math.floor(diffMs / 3_600_000)
  if (hours < 24) return `${hours}时`
  const days = calendarDaysBetween(then, now)
  if (days < 30) return `${days}天`
  const months = (now.getFullYear() - then.getFullYear()) * 12 + (now.getMonth() - then.getMonth())
  if (months < 12) return `${months}月`
  return `${now.getFullYear() - then.getFullYear()}年`
}

/** Whole days between two instants, comparing local calendar dates. */
function calendarDaysBetween(from: Date, to: Date): number {
  const a = new Date(from.getFullYear(), from.getMonth(), from.getDate())
  const b = new Date(to.getFullYear(), to.getMonth(), to.getDate())
  return Math.round((b.getTime() - a.getTime()) / 86_400_000)
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
  const total = Math.floor(ms / 1000)
  if (total < 1) return '<1秒'
  if (total < 60) return `${total}秒`
  const h = Math.floor(total / 3600)
  const m = Math.floor((total % 3600) / 60)
  const s = total % 60
  if (h) return `${h}小时${m}分${s}秒`
  return `${m}分${s}秒`
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

