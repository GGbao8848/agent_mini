import * as React from "react"
import { ArtifactsPanel } from "@/components/runs/artifacts-panel"
import { EventsPanel } from "@/components/runs/events-panel"
import { StatusBadge } from "@/components/runs/status-badge"
import { TaskIdChip } from "@/components/runs/task-stats"
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  Drawer,
  DrawerContent,
  DrawerDescription,
  DrawerFooter,
  DrawerHeader,
  DrawerTitle,
} from "@/components/ui/drawer"
import { Skeleton } from "@/components/ui/skeleton"
import { useCancelTask, useDeleteTask, useTaskArtifacts } from "@/hooks/use-console"
import { fmtDateTime, fmtDuration } from "@/lib/format"
import { TERMINAL_RUN_STATUSES } from "@/lib/types"
import type { Run, RunEvent } from "@/lib/types"
import {
  CircleAlertIcon,
  CircleCheckIcon,
  CircleStopIcon,
  InfoIcon,
  TimerIcon,
  Trash2Icon,
} from "lucide-react"

function UsageLine({ run }: { run: Run }) {
  if (!run.usage) return <span className="text-xs text-muted-foreground">尚无用量统计</span>
  return (
    <span className="flex items-center gap-1.5 text-xs text-muted-foreground">
      <TaskIdChip taskId={run.task_id} />
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

function RunInfoDrawer({
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
  // Aggregate the whole conversation's artifacts: the active run's own list is
  // empty when a follow-up message just started a fresh run, which would make
  // earlier turns' files vanish from the panel.
  const artifacts = useTaskArtifacts(open ? run.task_id : null)
  return (
    <Drawer open={open} onOpenChange={onOpenChange} showSwipeHandle>
      <DrawerContent
        style={{ "--drawer-height": "min(80dvh, 40rem)" } as React.CSSProperties}
      >
        <DrawerHeader>
          <DrawerTitle>运行详情 · {run.id.slice(0, 8)}</DrawerTitle>
          <DrawerDescription>
            {run.agent_id} · 开始 {fmtDateTime(run.created_at)}
          </DrawerDescription>
        </DrawerHeader>
        <div className="grid gap-4 overflow-y-auto px-4 pb-4 sm:grid-cols-2">
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
        <DrawerFooter className="border-t">
          <Button variant="outline" size="sm" onClick={() => onOpenChange(false)}>
            关闭
          </Button>
        </DrawerFooter>
      </DrawerContent>
    </Drawer>
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
  const [stopping, setStopping] = React.useState(false)
  const [removing, setRemoving] = React.useState(false)
  const cancel = useCancelTask()
  const deleteTask = useDeleteTask()
  const verification = (run.metadata as { verification?: Verification })?.verification
  const running = !TERMINAL_RUN_STATUSES.has(run.status)

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
        {running && (
          <>
            <Button
              variant="destructive"
              size="sm"
              disabled={cancel.isPending}
              onClick={() => setStopping(true)}
            >
              <CircleStopIcon data-icon="inline-start" />
              {cancel.isPending ? "正在停止…" : "停止"}
            </Button>
            <AlertDialog open={stopping} onOpenChange={(open) => !open && setStopping(false)}>
              <AlertDialogContent>
                <AlertDialogHeader>
                  <AlertDialogTitle>停止任务？</AlertDialogTitle>
                  <AlertDialogDescription>
                    将中断当前运行，已生成的产物会保留。停止后可在对话里继续下达指令。
                  </AlertDialogDescription>
                </AlertDialogHeader>
                <AlertDialogFooter>
                  <AlertDialogCancel>取消</AlertDialogCancel>
                  <AlertDialogAction
                    onClick={() => {
                      cancel.mutate({ taskId: run.task_id })
                      setStopping(false)
                    }}
                  >
                    停止
                  </AlertDialogAction>
                </AlertDialogFooter>
              </AlertDialogContent>
            </AlertDialog>
          </>
        )}
        <Button variant="ghost" size="sm" onClick={() => setInfoOpen(true)}>
          <InfoIcon data-icon="inline-start" />
          运行详情
        </Button>
        <Button
          variant="ghost"
          size="sm"
          className="text-destructive hover:bg-destructive/10 hover:text-destructive"
          disabled={deleteTask.isPending}
          onClick={() => setRemoving(true)}
        >
          <Trash2Icon data-icon="inline-start" />
          删除
        </Button>
        <AlertDialog open={removing} onOpenChange={(open) => !open && setRemoving(false)}>
          <AlertDialogContent>
            <AlertDialogHeader>
              <AlertDialogTitle>删除任务？</AlertDialogTitle>
              <AlertDialogDescription>
                {running
                  ? "任务正在运行，请先停止后再删除。"
                  : "任务及其全部运行记录将被删除，此操作不可撤销。"}
              </AlertDialogDescription>
            </AlertDialogHeader>
            <AlertDialogFooter>
              <AlertDialogCancel>取消</AlertDialogCancel>
              <AlertDialogAction
                disabled={running}
                onClick={() => {
                  deleteTask.mutate({ taskId: run.task_id })
                  setRemoving(false)
                }}
              >
                删除
              </AlertDialogAction>
            </AlertDialogFooter>
          </AlertDialogContent>
        </AlertDialog>
      </div>
      <RunInfoDrawer run={run} events={events} open={infoOpen} onOpenChange={setInfoOpen} />
    </div>
  )
}
