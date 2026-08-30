import * as React from "react"
import { ArtifactsPanel } from "@/components/runs/artifacts-panel"
import { EventsPanel } from "@/components/runs/events-panel"
import { StatusBadge } from "@/components/runs/status-badge"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { Skeleton } from "@/components/ui/skeleton"
import { useArtifacts } from "@/hooks/use-console"
import { fmtDateTime, fmtDuration } from "@/lib/format"
import type { Run, RunEvent } from "@/lib/types"
import { CircleAlertIcon, CircleCheckIcon, InfoIcon, TimerIcon } from "lucide-react"

function UsageLine({ run }: { run: Run }) {
  if (!run.usage) return <span className="text-xs text-muted-foreground">尚无用量统计</span>
  return (
    <span className="flex items-center gap-1 text-xs text-muted-foreground">
      <TimerIcon className="size-3.5" />
      {run.usage.duration_ms != null ? `${fmtDuration(run.usage.duration_ms)} · ` : ""}
      {run.usage.total_tokens} tokens · {run.usage.model_calls} 模型 · {run.usage.tool_calls} 工具
    </span>
  )
}

type Verification = { passed?: boolean; rounds?: number } | undefined

function VerificationBadge({ verification }: { verification: Verification }) {
  if (!verification) return null
  return (
    <Badge
      variant="outline"
      className={
        verification.passed
          ? "border-emerald-500/30 bg-emerald-500/15 text-emerald-700 dark:text-emerald-400"
          : "border-amber-500/30 bg-amber-500/15 text-amber-700 dark:text-amber-400"
      }
    >
      {verification.passed ? <CircleCheckIcon /> : <CircleAlertIcon />}
      自检 {verification.passed ? "通过" : "未通过"}（{verification.rounds ?? 0} 轮）
    </Badge>
  )
}

function RunInfoDialog({
  run,
  events,
  open,
  onOpenChange,
}: {
  run: Run
  events: RunEvent[]
  open: boolean
  onOpenChange: (open: boolean) => void
}) {
  const artifacts = useArtifacts(open ? run.id : null)
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle>运行详情 · {run.id.slice(0, 8)}</DialogTitle>
          <DialogDescription>
            {run.agent_id} · 开始 {fmtDateTime(run.created_at)}
          </DialogDescription>
        </DialogHeader>
        <div className="grid gap-4 sm:grid-cols-2">
          <div className="flex min-w-0 flex-col gap-1.5">
            <p className="text-xs font-medium text-muted-foreground">事件时间线</p>
            <div className="rounded-lg border">
              <EventsPanel events={events} />
            </div>
          </div>
          <div className="flex min-w-0 flex-col gap-1.5">
            <p className="text-xs font-medium text-muted-foreground">产物</p>
            {artifacts.isLoading ? (
              <div className="flex flex-col gap-2">
                <Skeleton className="h-20 w-full" />
                <Skeleton className="h-10 w-full" />
              </div>
            ) : (
              <ArtifactsPanel runId={run.id} artifacts={artifacts.data ?? []} />
            )}
          </div>
        </div>
      </DialogContent>
    </Dialog>
  )
}

/** Slim chat header above the conversation: status, agent, usage, and actions. */
export function RunChatHeader({
  run,
  events,
}: {
  run: Run
  events: RunEvent[]
}) {
  const [infoOpen, setInfoOpen] = React.useState(false)
  const verification = (run.metadata as { verification?: Verification })?.verification

  return (
    <div className="flex flex-wrap items-center gap-2 border-b px-4 py-2">
      <StatusBadge status={run.status} />
      <Badge variant="secondary">{run.agent_id}</Badge>
      <UsageLine run={run} />
      <VerificationBadge verification={verification} />
      {run.error && (
        <span className="w-full text-xs break-words text-destructive">{run.error}</span>
      )}
      <div className="ml-auto flex items-center gap-1">
        <Button variant="ghost" size="sm" onClick={() => setInfoOpen(true)}>
          <InfoIcon data-icon="inline-start" />
          运行详情
        </Button>
      </div>
      <RunInfoDialog run={run} events={events} open={infoOpen} onOpenChange={setInfoOpen} />
    </div>
  )
}
