/* Thread grouping helpers (multi-turn conversations share a thread_id). */

import type { Run } from "./types"

export function threadKey(run: Run): string {
  return run.thread_id || run.id
}

/** All top-level runs of the conversation `run` belongs to, oldest first. */
export function threadRuns(runs: Run[], run: Run): Run[] {
  return runs
    .filter((r) => r.parent_run_id === null && threadKey(r) === threadKey(run))
    .sort((a, b) => a.created_at.localeCompare(b.created_at))
}

export function isTerminalRun(run: Run): boolean {
  return ["completed", "failed", "timeout", "cancelled"].includes(run.status)
}

export function excerpt(run: Run, max = 160): string {
  const text = run.input || run.id.slice(0, 8)
  return text.length > max ? `${text.slice(0, max)}…` : text
}
