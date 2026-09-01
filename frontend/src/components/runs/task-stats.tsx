import * as React from "react"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { useRun, useTask } from "@/hooks/use-console"
import { fmtDuration } from "@/lib/format"
import { CheckIcon, CopyIcon } from "lucide-react"

const SHORT_ID = (id: string) => id.slice(0, 8)

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

/** Compact "task <id> [copy]" chip used in the conversation header. */
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
      <span className="font-mono">{SHORT_ID(taskId)}</span>
      {copied ? (
        <CheckIcon className="size-3 text-emerald-500" />
      ) : (
        <CopyIcon className="size-3 text-muted-foreground" />
      )}
    </Button>
  )
}

/** Live task stats for the top nav: current task id + the active run's usage.
 *
 * "实时" comes from the same polling the chat uses: ``useRun`` refetches every
 * 10s while the active run is non-terminal, and ``useTask`` keeps the id fresh
 * across follow-up messages (each new turn swaps the active run).
 */
export function LiveTaskStats({ taskId }: { taskId: string }) {
  const { data: task } = useTask(taskId)
  const activeRunId = task?.active_run_id ?? null
  const { data: run } = useRun(activeRunId)
  const { copied, copy } = useCopyId()
  const usage = run?.usage

  return (
    <div className="flex items-center gap-2">
      <Badge variant="outline" className="gap-1 font-mono text-xs font-normal">
        <span className="text-muted-foreground">task</span>
        {SHORT_ID(taskId)}
        <button
          type="button"
          title={`复制任务 id：${taskId}`}
          onClick={() => void copy(taskId)}
          className="flex items-center text-muted-foreground transition-colors hover:text-foreground"
        >
          {copied ? (
            <CheckIcon className="size-3 text-emerald-500" />
          ) : (
            <CopyIcon className="size-3" />
          )}
        </button>
      </Badge>
      {usage && (
        <span className="hidden text-xs text-muted-foreground md:inline">
          {usage.duration_ms != null ? `${fmtDuration(usage.duration_ms)} · ` : ""}
          {usage.total_tokens} tokens · {usage.model_calls} 模型 · {usage.tool_calls} 工具
        </span>
      )}
    </div>
  )
}
