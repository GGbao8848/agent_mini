import * as React from "react"

import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible"
import { artifactUrl } from "@/lib/api"
import { fmtSize } from "@/lib/format"
import type { Artifact, RunEvent } from "@/lib/types"
import { usePreview } from "@/components/preview/preview-panel"
import { cn } from "@/lib/utils"
import {
  BrainIcon,
  CheckIcon,
  ChevronRightIcon,
  FileIcon,
  FileTextIcon,
  FolderSearchIcon,
  Loader2Icon,
  PencilIcon,
  SquareTerminalIcon,
  XIcon,
} from "lucide-react"

/* ------------------------------------------------------------- labels */

/** Chinese labels for the tools the avatar actually uses; unknown tools fall
 *  back to their own name. File tools show the file they touched. */
const TOOL_LABELS: Record<string, { label: string; icon: React.ElementType }> = {
  run_code: { label: "运行命令", icon: SquareTerminalIcon },
  write_file: { label: "写入文件", icon: PencilIcon },
  edit_file: { label: "编辑文件", icon: PencilIcon },
  read_file: { label: "读取文件", icon: FileTextIcon },
  ls: { label: "查看目录", icon: FolderSearchIcon },
  glob: { label: "搜索文件", icon: FolderSearchIcon },
  grep: { label: "搜索内容", icon: FolderSearchIcon },
  install_skill: { label: "安装技能", icon: FileTextIcon },
  telegram_notify: { label: "发送通知", icon: FileTextIcon },
  telegram_send_artifact: { label: "发送产物", icon: FileTextIcon },
  ensure_packages: { label: "安装依赖", icon: SquareTerminalIcon },
  create_schedule: { label: "创建日程", icon: FileTextIcon },
}

function describeTool(event: RunEvent): { label: string; icon: React.ElementType } {
  const meta = TOOL_LABELS[event.tool ?? ""] ?? {
    label: event.tool ?? "工具调用",
    icon: SquareTerminalIcon,
  }
  // File tools show which file they touched (input carries the path).
  const input = event.input as Record<string, unknown> | null | undefined
  const path =
    input && typeof input === "object"
      ? (input.file_path ?? input.path ?? input.command ?? input.pattern)
      : undefined
  if (typeof path === "string" && path) {
    const short = path.split("/").slice(-1)[0] || path
    if (event.tool === "run_code") {
      return { label: `运行 ${short.slice(0, 40)}`, icon: meta.icon }
    }
    return { label: `${meta.label} ${short}`, icon: meta.icon }
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
  icon: React.ElementType
  running: boolean
  error: string | null
  detail: string
}

/** Turn a run's event stream into ZCode-style collapsible steps: thinking
 *  chunks merge into one "思考" group; every tool call becomes a step whose
 *  state follows its result event (running → ok/error). */
function buildItems(events: RunEvent[]): ActivityItem[] {
  const items: ActivityItem[] = []
  const openTools = new Map<string, ActivityItem>()
  let thinking: ActivityItem | null = null

  for (const event of events) {
    const key = event.id || `${event.timestamp}-${event.event_type}`
    if (event.event_type === "agent_thinking") {
      const chunk = text(event.output) || text(event.input)
      if (!chunk) continue
      if (thinking == null) {
        thinking = {
          key: `think-${key}`,
          kind: "think",
          label: "思考",
          icon: BrainIcon,
          running: true,
          error: null,
          detail: chunk,
        }
        items.push(thinking)
      } else {
        thinking.detail += chunk
      }
      continue
    }
    if (event.event_type === "agent_started" || event.event_type === "agent_finished") {
      if (thinking) thinking.running = false
      continue
    }
    if (event.event_type === "tool_started" || event.event_type === "tool_requested") {
      if (event.event_type === "tool_requested") continue // the started event opens the step
      if (thinking) thinking.running = false
      const described = describeTool(event)
      const item: ActivityItem = {
        key,
        kind: "tool",
        label: described.label,
        icon: described.icon,
        running: true,
        error: null,
        detail: text(event.input),
      }
      items.push(item)
      if (event.tool) openTools.set(event.tool, item)
      continue
    }
    if (event.event_type === "tool_executed" || event.event_type === "tool_failed") {
      const item = (event.tool ? openTools.get(event.tool) : undefined) ?? items[items.length - 1]
      if (item == null || item.kind !== "tool") continue
      item.running = false
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
  if (thinking && lastType !== "agent_thinking") thinking.running = false
  return items
}

const MAX_DETAIL = 4000

function ActivityStep({ item, defaultOpen }: { item: ActivityItem; defaultOpen: boolean }) {
  const [open, setOpen] = React.useState(defaultOpen)
  const Icon = item.icon
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
        {item.running ? (
          <Loader2Icon className="size-3.5 shrink-0 animate-spin text-primary" />
        ) : (
          <Icon
            className={cn(
              "size-3.5 shrink-0",
              item.error ? "text-destructive" : "text-muted-foreground",
            )}
          />
        )}
        <span className={cn("min-w-0 truncate font-medium", item.error && "text-destructive")}>
          {item.label}
        </span>
        {item.running ? (
          <span className="ml-auto flex shrink-0 gap-0.5 dot-bounce" aria-hidden>
            <span className="size-1 rounded-full bg-current" />
            <span className="size-1 rounded-full bg-current" />
            <span className="size-1 rounded-full bg-current" />
          </span>
        ) : item.error ? (
          <XIcon className="ml-auto size-3.5 shrink-0 text-destructive" />
        ) : item.kind === "tool" ? (
          <CheckIcon className="ml-auto size-3.5 shrink-0 text-emerald-500" />
        ) : null}
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

/** The activity trail of one run, rendered under the assistant bubble. */
export function RunActivity({ events, running }: { events: RunEvent[]; running: boolean }) {
  const items = React.useMemo(() => buildItems(events), [events])
  if (!items.length) return null
  const lastKey = items[items.length - 1]?.key
  return (
    <div className="flex flex-col gap-0.5 rounded-lg border bg-card/50 py-1">
      {items.map((item) => (
        <ActivityStep
          key={item.key}
          item={{ ...item, running: item.running && running }}
          defaultOpen={running && item.key === lastKey}
        />
      ))}
    </div>
  )
}

/* -------------------------------------------------------------- artifacts */

/** A run's deliverables, inline in the chat: clicking any artifact opens the
 *  right-hand preview pane (images and Markdown render there; other files get
 *  a download button) instead of triggering a browser download. */
export function RunArtifacts({ runId, artifacts }: { runId: string; artifacts: Artifact[] }) {
  const preview = usePreview()
  if (!artifacts.length) return null
  const images = artifacts.filter((a) => /\.(png|jpe?g|webp|gif)$/i.test(a.path))
  const files = artifacts.filter((a) => !/\.(png|jpe?g|webp|gif)$/i.test(a.path))
  return (
    <div className="flex flex-col gap-1.5">
      {images.length > 0 && (
        <div className="grid gap-2 sm:grid-cols-2">
          {images.map((artifact) => {
            const url = artifactUrl(artifact.run_id ?? runId, artifact.path)
            return (
              <button
                key={artifact.path}
                type="button"
                onClick={() => preview.open({ runId: artifact.run_id ?? runId, path: artifact.path })}
                className="group relative cursor-zoom-in overflow-hidden rounded-lg border"
                title="点击预览"
              >
                <img
                  src={url}
                  alt={artifact.path}
                  loading="lazy"
                  className="max-h-56 w-full object-contain transition-transform duration-200 group-hover:scale-[1.02]"
                />
                <span className="absolute inset-x-0 bottom-0 truncate bg-black/45 px-1.5 py-0.5 text-[10px] text-white opacity-0 transition-opacity group-hover:opacity-100">
                  {artifact.path} · {fmtSize(artifact.size)}
                </span>
              </button>
            )
          })}
        </div>
      )}
      {files.map((artifact) => (
        <button
          key={artifact.path}
          type="button"
          onClick={() => preview.open({ runId: artifact.run_id ?? runId, path: artifact.path })}
          className="flex w-full cursor-pointer items-center gap-2 rounded-lg border px-2 py-1.5 text-xs transition-colors hover:bg-muted"
          title="点击预览"
        >
          <FileIcon className="size-3.5 shrink-0 text-muted-foreground" />
          <span className="min-w-0 truncate" title={artifact.path}>
            {artifact.path}
          </span>
          <span className="ml-auto shrink-0 text-[10px] text-muted-foreground">
            {fmtSize(artifact.size)}
          </span>
        </button>
      ))}
    </div>
  )
}

/* ------------------------------------------------------- running indicator */

/** "The avatar is working, not frozen": spinner + the latest activity label
 *  + bouncing dots. Sits at the end of the thread while a run is live. */
export function RunningIndicator({ events }: { events: RunEvent[] }) {
  const lastTool = [...events].reverse().find((e) => e.tool)
  const label = lastTool ? describeTool(lastTool).label : "正在思考"
  return (
    <div className="flex items-center gap-2 px-1 text-xs text-muted-foreground animate-fade-slide-up">
      <Loader2Icon className="size-3.5 animate-spin text-primary" />
      <span>分身正在工作</span>
      <span className="max-w-48 truncate font-mono">{label}</span>
      <span className="flex gap-0.5 dot-bounce" aria-hidden>
        <span className="size-1 rounded-full bg-current" />
        <span className="size-1 rounded-full bg-current" />
        <span className="size-1 rounded-full bg-current" />
      </span>
    </div>
  )
}
