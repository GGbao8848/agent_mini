import * as React from "react"

import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible"
import { artifactUrl } from "@/lib/api"
import { fmtDuration, fmtSize } from "@/lib/format"
import type { Artifact, RunEvent } from "@/lib/types"
import { usePreview } from "@/components/preview/preview-panel"
import { cn } from "@/lib/utils"
import { ChevronRightIcon } from "lucide-react"

/* ------------------------------------------------------------- labels */

/** Chinese labels for the tools the avatar actually uses; unknown tools fall
 *  back to their own name. File tools show the file they touched. */
const TOOL_LABELS: Record<string, string> = {
  run_code: "运行命令",
  write_file: "写入文件",
  edit_file: "编辑文件",
  read_file: "读取文件",
  ls: "查看目录",
  glob: "搜索文件",
  grep: "搜索内容",
  install_skill: "安装技能",
  ensure_packages: "安装依赖",
  create_schedule: "创建日程",
}

function describeTool(event: RunEvent): string {
  const meta = TOOL_LABELS[event.tool ?? ""] ?? (event.tool ?? "工具调用")
  // File tools show which file they touched (input carries the path).
  const input = event.input as Record<string, unknown> | null | undefined
  const path =
    input && typeof input === "object"
      ? (input.file_path ?? input.path ?? input.command ?? input.pattern)
      : undefined
  if (typeof path === "string" && path) {
    const short = path.split("/").slice(-1)[0] || path
    if (event.tool === "run_code") {
      return `运行 ${short.slice(0, 40)}`
    }
    return `${meta} ${short}`
  }
  return meta
}

function text(value: unknown): string {
  if (value == null) return ""
  if (typeof value === "string") return value
  try {
    return JSON.stringify(value, null, 2)
  } catch {
    return String(value)
  }
}

/* ------------------------------------------------------- activity groups */

interface ActivityItem {
  key: string
  kind: "think" | "tool"
  label: string
  running: boolean
  error: string | null
  detail: string
  startTs: number | null
  endTs: number | null
  /** Thinking blocks are re-opened after each tool call, so interleaved
   *  思考 / 运行 steps each carry their own duration. */
}

/** Turn a run's event stream into ZCode-style collapsible steps: thinking
 *  chunks merge into per-segment "思考" groups (re-opened after each tool
 *  call, interleaved with them); every tool call becomes a step whose state
 *  follows its result event (running → ok/error). Timestamps are kept so
 *  each step can show its own duration. */
function buildItems(events: RunEvent[]): ActivityItem[] {
  const items: ActivityItem[] = []
  const openTools = new Map<string, ActivityItem>()
  let thinking: ActivityItem | null = null

  const closeThinking = (atTs: number | null) => {
    if (!thinking) return
    thinking.running = false
    if (atTs != null) thinking.endTs = atTs
    thinking = null
  }

  for (const event of events) {
    const key = event.id || `${event.timestamp}-${event.event_type}`
    const ts = parseTs(event.timestamp)
    if (event.event_type === "agent_thinking") {
      const chunk = text(event.output) || text(event.input)
      if (!chunk) continue
      if (thinking == null) {
        thinking = {
          key: `think-${key}`,
          kind: "think",
          label: "思考",
          running: true,
          error: null,
          detail: chunk,
          startTs: ts,
          endTs: ts,
        }
        items.push(thinking)
      } else {
        thinking.detail += chunk
        if (ts != null) thinking.endTs = ts
      }
      continue
    }
    if (event.event_type === "agent_started" || event.event_type === "agent_finished") {
      closeThinking(ts)
      continue
    }
    if (event.event_type === "tool_started" || event.event_type === "tool_requested") {
      if (event.event_type === "tool_requested") continue // the started event opens the step
      closeThinking(ts)
      const item: ActivityItem = {
        key,
        kind: "tool",
        label: describeTool(event),
        running: true,
        error: null,
        detail: text(event.input),
        startTs: ts,
        endTs: ts,
      }
      items.push(item)
      if (event.tool) openTools.set(event.tool, item)
      continue
    }
    if (event.event_type === "tool_executed" || event.event_type === "tool_failed") {
      const item = (event.tool ? openTools.get(event.tool) : undefined) ?? items[items.length - 1]
      if (item == null || item.kind !== "tool") continue
      item.running = false
      if (ts != null) item.endTs = ts
      const output = text(event.output)
      if (event.event_type === "tool_failed") {
        item.error = text(event.error) || output || "执行失败"
      } else if (output && output !== "None") {
        item.detail = item.detail ? `${item.detail}\n→ ${output}` : output
      }
      continue
    }
  }
  // A still-running run's last thinking block is genuinely "in progress";
  // everything trailing a finished run is settled.
  const lastType = events[events.length - 1]?.event_type
  if (thinking && lastType !== "agent_thinking") closeThinking(null)
  return items
}

const MAX_DETAIL = 4000

function ActivityStep({
  item,
  now,
}: {
  item: ActivityItem
  now: number
}) {
  const [open, setOpen] = React.useState(false)
  // Per-step duration: settled steps use their own start/end timestamps; the
  // in-flight step ticks against the parent's 1s clock.
  const stepMs =
    item.startTs == null
      ? null
      : item.running && now
        ? Math.max(0, now - item.startTs)
        : item.endTs != null
          ? Math.max(0, item.endTs - item.startTs)
          : null
  return (
    <Collapsible open={open} onOpenChange={setOpen} className="animate-fade-slide-up">
      <CollapsibleTrigger
        className={cn(
          "group flex w-full items-center gap-1.5 rounded-md px-1.5 py-1 text-left text-xs transition-colors hover:bg-muted/60",
          item.error && "text-destructive",
        )}
      >
        <ChevronRightIcon
          className={cn(
            "size-3.5 shrink-0 text-muted-foreground transition-transform",
            open && "rotate-90",
          )}
        />
        <span className={cn("min-w-0 truncate font-medium", item.error && "text-destructive")}>
          {item.label}
        </span>
        {stepMs != null && (
          <span className="shrink-0 font-mono text-[10px] text-muted-foreground">
            {fmtDuration(stepMs)}
          </span>
        )}
        {item.running && (
          <span className="flex shrink-0 gap-0.5 dot-bounce" aria-hidden>
            <span className="size-1 rounded-full bg-current" />
            <span className="size-1 rounded-full bg-current" />
            <span className="size-1 rounded-full bg-current" />
          </span>
        )}
      </CollapsibleTrigger>
      <CollapsibleContent>
        <div
          className={cn(
            "ml-6 mr-1 mt-0.5 mb-1 max-h-48 overflow-y-auto whitespace-pre-wrap break-words rounded-md bg-muted/60 px-2 py-1.5 font-mono text-[11px] leading-snug",
            item.error && "bg-destructive/10 text-destructive",
          )}
        >
          {(item.error || item.detail || "（无输出）").slice(0, MAX_DETAIL)}
        </div>
      </CollapsibleContent>
    </Collapsible>
  )
}

/** Ticking clock (1s) used for the live elapsed time while a run streams. */
function useNow(running: boolean) {
  const [now, setNow] = React.useState(() => Date.now())
  React.useEffect(() => {
    if (!running) return
    const timer = setInterval(() => setNow(Date.now()), 1000)
    return () => clearInterval(timer)
  }, [running])
  return now
}

function parseTs(value: unknown): number | null {
  if (typeof value !== "string" && typeof value !== "number") return null
  const ms = new Date(value).getTime()
  return Number.isNaN(ms) ? null : ms
}

/** The run's whole intermediate work — streamed thinking interleaved with tool
 *  calls — folded into ONE collapsible space, ZCode-style. The header stays
 *  visible while running (current step + live 分秒 timer); expanding works at
 *  any time, not only after the run finishes. */
export function RunActivity({
  events,
  running,
  startedAt,
}: {
  events: RunEvent[]
  running: boolean
  startedAt?: string | null
}) {
  const items = React.useMemo(() => buildItems(events), [events])
  const now = useNow(running)
  const [open, setOpen] = React.useState(false)

  const elapsedMs = React.useMemo(() => {
    const start = parseTs(events[0]?.timestamp) ?? parseTs(startedAt)
    const end = parseTs(events[events.length - 1]?.timestamp)
    if (running) {
      const base = start ?? parseTs(startedAt)
      return base == null ? 0 : Math.max(0, now - base)
    }
    if (start == null) return null
    return Math.max(0, (end ?? now) - start)
  }, [events, running, startedAt, now])

  if (!items.length && !running) return null
  const current = items[items.length - 1]
  const failed = items.some((item) => item.error)

  return (
    <Collapsible open={open} onOpenChange={setOpen}>
      <CollapsibleTrigger className="flex w-full items-center gap-1.5 px-1 py-1 text-left text-xs transition-colors hover:bg-muted/60">
        <ChevronRightIcon
          className={cn(
            "size-3.5 shrink-0 text-muted-foreground transition-transform",
            open && "rotate-90",
          )}
        />
        <span className={cn("shrink-0 font-medium", failed && "text-destructive")}>已工作</span>
        {elapsedMs != null && (
          <span className="shrink-0 font-mono text-muted-foreground">
            {fmtDuration(elapsedMs)}
          </span>
        )}
        {running && current && (
          <span className="min-w-0 truncate text-muted-foreground">
            {current.kind === "think" ? "思考…" : current.label}
          </span>
        )}
        {running && (
          <span className="flex shrink-0 gap-0.5 dot-bounce" aria-hidden>
            <span className="size-1 rounded-full bg-current" />
            <span className="size-1 rounded-full bg-current" />
            <span className="size-1 rounded-full bg-current" />
          </span>
        )}
      </CollapsibleTrigger>
      <CollapsibleContent>
        <div className="ml-4 flex flex-col gap-0.5 py-0.5">
          {items.map((item) => (
            <ActivityStep
              key={item.key}
              item={{ ...item, running: item.running && running }}
              now={now}
            />
          ))}
        </div>
      </CollapsibleContent>
    </Collapsible>
  )
}

/* -------------------------------------------------------------- artifacts */

/** A run's deliverables, inline in the chat: clicking any artifact opens the
 *  right-hand preview pane (images and Markdown render there; other files get
 *  a download button) instead of triggering a browser download. Deliberately
 *  sparse: filename + size, no chrome. */
export function RunArtifacts({ runId, artifacts }: { runId: string; artifacts: Artifact[] }) {
  const preview = usePreview()
  if (!artifacts.length) return null
  const images = artifacts.filter((a) => /\.(png|jpe?g|webp|gif)$/i.test(a.path))
  const files = artifacts.filter((a) => !/\.(png|jpe?g|webp|gif)$/i.test(a.path))
  return (
    <div className="flex flex-col gap-1">
      {images.map((artifact) => (
        <button
          key={artifact.path}
          type="button"
          onClick={() => preview.open({ runId: artifact.run_id ?? runId, path: artifact.path })}
          className="w-fit cursor-zoom-in overflow-hidden rounded-lg border"
          title={`${artifact.path}（点击预览）`}
        >
          <img
            src={artifactUrl(artifact.run_id ?? runId, artifact.path)}
            alt={artifact.path}
            loading="lazy"
            className="max-h-56 object-contain"
          />
        </button>
      ))}
      {files.map((artifact) => (
        <button
          key={artifact.path}
          type="button"
          onClick={() => preview.open({ runId: artifact.run_id ?? runId, path: artifact.path })}
          className="flex w-fit cursor-pointer items-baseline gap-1.5 text-left text-xs text-muted-foreground transition-colors hover:text-foreground"
          title={`${artifact.path}（点击预览）`}
        >
          <span className="truncate underline underline-offset-2 decoration-border">
            {artifact.path}
          </span>
          <span className="shrink-0 font-mono text-[10px]">{fmtSize(artifact.size)}</span>
        </button>
      ))}
    </div>
  )
}
