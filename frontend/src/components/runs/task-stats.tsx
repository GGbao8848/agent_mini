import * as React from "react"

import { Button } from "@/components/ui/button"
import { useRun } from "@/hooks/use-console"
import { fmtDuration } from "@/lib/format"
import { CheckIcon, CopyIcon, TimerIcon } from "lucide-react"

/** One-click copy of a full task id, with a brief "已复制" confirmation. */
function useCopyId() {
  const [copied, setCopied] = React.useState(false)
  const timer = React.useRef<ReturnType<typeof setTimeout> | null>(null)
  const copy = React.useCallback(async (text: string) => {
    try {
      await navigator.clipboard.writeText(text)
      setCopied(true)
      if (timer.current) clearTimeout(timer.current)
      timer.current = setTimeout(() => setCopied(false), 1500)
    } catch {
      // clipboard may be unavailable; just no-op
    }
  }, [])
  React.useEffect(() => () => {
    if (timer.current) clearTimeout(timer.current)
  }, [])
  return { copied, copy }
}

/** Compact "task <id> [copy]" chip used in the conversation header. Shows the
 * full id (truncated visually only when the space truly runs out, never
 * shortened data-wise) and copies the complete id on click. */
export function TaskIdChip({ taskId }: { taskId: string }) {
  const { copied, copy } = useCopyId()
  return (
    <Button
      variant="outline"
      size="sm"
      title={`复制任务 id：${taskId}`}
      onClick={() => void copy(taskId)}
      className="h-6 gap-1 px-1.5 text-xs font-normal"
    >
      <span className="text-muted-foreground">task</span>
      <span className="font-mono max-w-40 truncate">{taskId}</span>
      {copied ? (
        <CheckIcon className="size-3 text-emerald-500" />
      ) : (
        <CopyIcon className="size-3 text-muted-foreground" />
      )}
    </Button>
  )
}

/** Per-run usage line shown under an assistant bubble: same format, scoped to
 *  the run that produced that reply. ``useRun`` refetches while the run is
 *  active, so the newest bubble's stats grow as the task runs and settle once
 *  it completes. The conversation-level stats live in the composer's context
 *  gauge now (the header only keeps the task id chip). */
export function RunStatsLine({ runId }: { runId: string }) {
  const { data: run } = useRun(runId)
  const usage = run?.usage
  if (!usage) return null
  return (
    <span className="flex items-center gap-1 text-xs text-muted-foreground">
      <TimerIcon className="size-3.5" />
      {usage.duration_ms != null ? `${fmtDuration(usage.duration_ms)} · ` : ""}
      {usage.total_tokens} tokens · {usage.model_calls} 模型 · {usage.tool_calls} 工具
    </span>
  )
}
