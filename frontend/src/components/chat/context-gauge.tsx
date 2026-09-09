import * as React from "react"

import { useModelConfig, useRun, useTask } from "@/hooks/use-console"
import { getSelectedModel } from "@/components/chat/model-picker"
import { cn } from "@/lib/utils"

/* When no endpoint declares a context window we still want the gauge to work;
 * 256k matches the local vLLM deployment and the tooltip says "estimated". */
const FALLBACK_WINDOW = 262_144

function fmtTokens(n: number): string {
  if (n >= 10_000) return `${(n / 1000).toFixed(1)}k`
  if (n >= 1000) return `${(n / 1000).toFixed(2)}k`
  return String(n)
}

function currentWindow(config: ReturnType<typeof useModelConfig>["data"]): {
  window: number
  estimated: boolean
} {
  const spec = getSelectedModel()
  const provider = spec ? spec.split(":")[0] : null
  const endpoint = provider
    ? config?.custom_models?.find((m) => m.name === provider)
    : null
  if (endpoint?.context_window) return { window: endpoint.context_window, estimated: false }
  return { window: FALLBACK_WINDOW, estimated: true }
}

/** Context-capacity ring in the composer: how full the conversation's context
 *  window is, based on the most recent model call's input tokens (the replayed
 *  history). Empty until the conversation has at least one run with usage. */
export function ContextGauge({ taskId }: { taskId?: string | null }) {
  const { data: task } = useTask(taskId ?? null)
  const activeRunId = task?.active_run_id ?? null
  // Prefer the live run while it exists; once settled, the task's turns stop
  // moving and the last run carries the final context snapshot.
  const lastTurnRunId = React.useMemo(() => {
    if (!task) return null
    for (let i = task.turns.length - 1; i >= 0; i--) {
      const rid = task.turns[i]?.metadata?.run_id
      if (typeof rid === "string") return rid
    }
    return null
  }, [task])
  const { data: run } = useRun(activeRunId ?? lastTurnRunId)
  const config = useModelConfig()

  const usage = run?.usage ?? null
  if (!usage || !taskId) return null
  const tokens = usage.last_input_tokens ?? usage.input_tokens ?? 0
  if (tokens <= 0) return null

  const { window: window_, estimated } = currentWindow(config.data)
  const pct = Math.min(100, Math.round((tokens / window_) * 100))
  // Ring color walks green → amber → red as the window fills up.
  const stroke =
    pct >= 85 ? "stroke-destructive" : pct >= 60 ? "stroke-amber-500" : "stroke-emerald-500"

  const R = 10
  const C = 2 * Math.PI * R

  return (
    <div
      className="flex items-center gap-1.5"
      title={`上下文约 ${fmtTokens(tokens)} / ${estimated ? "≈" : ""}${fmtTokens(window_)} tokens（最近一轮输入，占 ${pct}%）${estimated ? "；端点未配置 context_window，按 256k 估算，可在模型配置页填写" : ""}`}
    >
      <svg viewBox="0 0 24 24" className="size-6 -rotate-90">
        <circle cx="12" cy="12" r={R} className="fill-none stroke-muted" strokeWidth="3" />
        <circle
          cx="12"
          cy="12"
          r={R}
          className={cn("fill-none transition-[stroke-dashoffset]", stroke)}
          strokeWidth="3"
          strokeLinecap="round"
          strokeDasharray={C}
          strokeDashoffset={C * (1 - pct / 100)}
        />
      </svg>
      <span className="font-mono text-[10px] text-muted-foreground">{pct}%</span>
    </div>
  )
}
