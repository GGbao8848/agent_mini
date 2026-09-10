import * as React from "react"

import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip"
import { useModelConfig, useRun, useTask } from "@/hooks/use-console"
import { getSelectedModel } from "@/components/chat/model-picker"
import type { Run } from "@/lib/types"

/* When no endpoint declares a context window we still want the gauge to work;
 * 256k matches the local vLLM deployment and the panel says "estimated". */
const FALLBACK_WINDOW = 262_144

function fmtTokens(n: number): string {
  if (n >= 10_000) return `${(n / 1000).toFixed(1)}k`
  if (n >= 1000) return `${(n / 1000).toFixed(2)}k`
  return String(n)
}

interface Breakdown {
  builtin_tools?: number
  mcp_tools?: number
  skills?: number
}

function currentWindow(custom: ReturnType<typeof useModelConfig>["data"]): {
  window: number
  estimated: boolean
} {
  const spec = getSelectedModel()
  // Prefer the picked model's own window; fall back to the effective default
  // model's window from the same `available_models` list.
  const target = spec ?? custom?.effective_model ?? null
  const option = target
    ? custom?.available_models?.find((m) => m.spec === target)
    : undefined
  if (option?.context_window) return { window: option.context_window, estimated: false }
  return { window: FALLBACK_WINDOW, estimated: true }
}

/** One row of the hover panel: label, estimated tokens, share of the window. */
function Part({ label, tokens, total }: { label: string; tokens: number; total: number }) {
  const share = total > 0 ? Math.round((tokens / total) * 100) : 0
  return (
    <div className="flex items-center gap-2 text-xs">
      <span className="w-16 shrink-0 text-muted-foreground">{label}</span>
      <span className="w-14 shrink-0 text-right font-mono">{fmtTokens(tokens)}</span>
      <span className="w-10 shrink-0 text-right font-mono text-muted-foreground">{share}%</span>
    </div>
  )
}

/** Context-capacity ring in the composer. Idle state: a single muted ring.
 *  Hovering opens a white panel with the capacity line and a per-part
 *  breakdown (messages, system prompt, built-in tools, MCP tools, skills).
 *
 *  While a follow-up run is starting it has no usage yet — reading only the
 *  active run made the gauge flash to empty on every send. The gauge walks
 *  back through the latest runs (newest first) and shows the most recent one
 *  that actually carries a context snapshot, labelling it 上一轮. */
export function ContextGauge({ taskId }: { taskId?: string | null }) {
  const { data: task } = useTask(taskId ?? null)

  // Deduped run ids from the conversation, newest first.
  const historyRunIds = React.useMemo(() => {
    if (!task) return [] as string[]
    const ids: string[] = []
    for (let i = task.turns.length - 1; i >= 0; i--) {
      const rid = task.turns[i]?.metadata?.run_id
      if (typeof rid === "string" && !ids.includes(rid)) ids.push(rid)
      if (ids.length >= 3) break
    }
    return ids
  }, [task])

  const activeRunId = task?.active_run_id ?? null
  const candidates = React.useMemo(() => {
    const rest = historyRunIds.filter((id) => id !== activeRunId)
    return (activeRunId ? [activeRunId, ...rest] : rest).slice(0, 3)
  }, [activeRunId, historyRunIds])

  // Fixed hook count (rules of hooks); candidates shift through the slots.
  const r0 = useRun(candidates[0] ?? null)
  const r1 = useRun(candidates[1] ?? null)
  const r2 = useRun(candidates[2] ?? null)
  const runs = [r0.data, r1.data, r2.data]

  const usageOf = (r: Run | undefined) => r?.usage?.last_input_tokens ?? 0
  const chosenIdx = runs.findIndex((r) => usageOf(r) > 0)
  const run = (chosenIdx >= 0 ? runs[chosenIdx] : runs[0]) ?? undefined
  const stale = chosenIdx > 0 // the shown snapshot is from an earlier run

  const config = useModelConfig()
  if (!taskId) return null

  const usage = run?.usage ?? null
  const tokens = usage?.last_input_tokens ?? 0
  const hasData = tokens > 0

  const { window: window_, estimated } = currentWindow(config.data)
  const pct = hasData ? Math.min(100, (tokens / window_) * 100) : 0
  const pctLabel = Math.round(pct)

  const breakdown = ((run as Run | undefined)?.metadata?.context_breakdown ?? {}) as Breakdown
  const parts = [
    { label: "消息", tokens: usage?.estimated_messages_tokens ?? 0 },
    { label: "系统提示词", tokens: usage?.estimated_system_tokens ?? 0 },
    { label: "系统工具", tokens: breakdown.builtin_tools ?? 0 },
    { label: "MCP工具", tokens: breakdown.mcp_tools ?? 0 },
    { label: "技能", tokens: breakdown.skills ?? 0 },
  ]
  const known = parts.reduce((sum, p) => sum + p.tokens, 0)
  const other = Math.max(0, tokens - known)
  const R = 10
  const C = 2 * Math.PI * R

  return (
    <TooltipProvider delay={120}>
      <Tooltip>
        <TooltipTrigger
          render={
            <span className="flex cursor-help items-center" title={undefined}>
              <svg viewBox="0 0 24 24" className="size-6 -rotate-90">
                <circle cx="12" cy="12" r={R} className="fill-none stroke-muted" strokeWidth="3" />
                <circle
                  cx="12"
                  cy="12"
                  r={R}
                  className="fill-none stroke-foreground/60 transition-[stroke-dashoffset]"
                  strokeWidth="3"
                  strokeLinecap="round"
                  strokeDasharray={C}
                  strokeDashoffset={C * (1 - pct / 100)}
                />
              </svg>
            </span>
          }
        />
        <TooltipContent className="w-64 flex-col gap-2 bg-white p-3 text-foreground border shadow-lg [&_svg]:fill-white [&_svg]:bg-white">
          {hasData ? (
            <div className="flex flex-col gap-2">
              <div className="flex items-baseline justify-between text-xs">
                <span className="font-medium">
                  上下文容量{stale && <span className="ml-1 font-normal text-muted-foreground">（上一轮）</span>}
                </span>
                <span className="font-mono text-muted-foreground">
                  {fmtTokens(tokens)} / {estimated ? "≈" : ""}
                  {fmtTokens(window_)} · {pctLabel}%
                </span>
              </div>
              <div className="h-1.5 overflow-hidden rounded-full bg-muted">
                <div
                  className="h-full rounded-full bg-foreground/60"
                  style={{ width: `${Math.min(100, pct)}%` }}
                />
              </div>
              <div className="mt-1 flex flex-col gap-1 border-t pt-2">
                <Part label="消息" tokens={parts[0].tokens} total={tokens} />
                <Part label="系统提示词" tokens={parts[1].tokens} total={tokens} />
                <Part label="系统工具" tokens={parts[2].tokens} total={tokens} />
                <Part label="MCP工具" tokens={parts[3].tokens} total={tokens} />
                <Part label="技能" tokens={parts[4].tokens} total={tokens} />
                <Part label="其他" tokens={other} total={tokens} />
              </div>
              <p className="text-[10px] leading-snug text-muted-foreground">
                按最近一次模型调用估算{estimated ? "；端点未配置 context_window，按 256k 计" : ""}
              </p>
            </div>
          ) : (
            <div className="flex flex-col gap-1 text-xs">
              <span className="font-medium">上下文容量</span>
              <span className="text-muted-foreground">
                这条对话还没有容量数据（旧版本时期创建的运行不带统计）。发送一条消息后即可显示。
              </span>
            </div>
          )}
        </TooltipContent>
      </Tooltip>
    </TooltipProvider>
  )
}
