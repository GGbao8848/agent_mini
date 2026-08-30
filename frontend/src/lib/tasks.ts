/* Conversation (task) helpers. A task is one conversation: a title, the
 * full turn history, and the latest execution's status. */

import type { Task } from "./types"

export function taskStatus(task: Task): string {
  return task.status
}

export function isTerminalTask(task: Task): boolean {
  return ["completed", "failed", "timeout", "cancelled"].includes(task.status)
}

/** Sidebar label: the title, or the first user turn's text, or the id. */
export function excerpt(task: Task, max = 60): string {
  const text =
    task.title ||
    task.turns.find((t) => t.role === "user")?.content ||
    task.id.slice(0, 8)
  return text.length > max ? `${text.slice(0, max)}…` : text
}
