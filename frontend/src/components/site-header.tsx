import * as React from "react"

import { LiveTaskStats } from "@/components/runs/task-stats"
import { StatusBadge } from "@/components/runs/status-badge"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { Separator } from "@/components/ui/separator"
import { SidebarTrigger } from "@/components/ui/sidebar"
import { useCancelTask, useDeleteTask, useRun, useTask, useTaskEvents } from "@/hooks/use-console"
import { TERMINAL_RUN_STATUSES, type Run, type RunEvent } from "@/lib/types"
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
import {
  Drawer,
  DrawerContent,
  DrawerDescription,
  DrawerFooter,
  DrawerHeader,
  DrawerTitle,
} from "@/components/ui/drawer"
import { Skeleton } from "@/components/ui/skeleton"
import { ArtifactsPanel } from "@/components/runs/artifacts-panel"
import { EventsPanel } from "@/components/runs/events-panel"
import { useTaskArtifacts } from "@/hooks/use-console"
import { fmtDateTime } from "@/lib/format"
import { KeyRoundIcon, TriangleAlertIcon, CircleStopIcon, InfoIcon, Trash2Icon, CircleCheckIcon, CircleAlertIcon } from "lucide-react"
import type { ConnState } from "@/hooks/use-console"

const CONN_BADGE: Record<ConnState, { label: string; className: string }> = {
  connecting: {
    label: "连接中…",
    className: "border-amber-500/30 bg-amber-500/15 text-amber-700 dark:text-amber-400",
  },
  live: {
    label: "实时",
    className: "border-emerald-500/30 bg-emerald-500/15 text-emerald-700 dark:text-emerald-400",
  },
  offline: {
    label: "已断开",
    className: "border-red-500/30 bg-red-500/15 text-red-700 dark:text-red-400",
  },
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

export function SiteHeader({
  title,
  conn,
  pendingApprovals,
  onOpenTokenDialog,
  taskId,
}: {
  title: string
  conn: ConnState
  pendingApprovals: number
  onOpenTokenDialog: () => void
  /** The currently open conversation (from the "新建任务" view); live stats shown when set. */
  taskId?: string | null
}) {
  const [infoOpen, setInfoOpen] = React.useState(false)
  const [stopping, setStopping] = React.useState(false)
  const [removing, setRemoving] = React.useState(false)
  const cancel = useCancelTask()
  const deleteTask = useDeleteTask()

  // The open conversation's live state: task → active run → its events. This
  // makes the header the single top bar for a conversation (status, live
  // usage, run details, stop/delete), replacing the old per-chat header.
  const { data: task } = useTask(taskId ?? null)
  const activeRunId = task?.active_run_id ?? null
  const { data: run } = useRun(activeRunId)
  const events = useTaskEvents(taskId ?? null)
  const verification = (run?.metadata as { verification?: Verification } | undefined)?.verification
  const running = !!run && !TERMINAL_RUN_STATUSES.has(run.status)

  return (
    <header className="flex h-14 shrink-0 items-center gap-2 border-b">
      <div className="flex min-w-0 flex-1 items-center gap-2 px-3">
        <SidebarTrigger />
        <Separator orientation="vertical" className="mr-2 data-[orientation=vertical]:h-4" />
        <span className="truncate text-sm font-medium">{title}</span>
        {taskId && run && (
          <div className="flex min-w-0 items-center gap-1.5">
            <StatusBadge status={run.status} />
            <VerificationBadge verification={verification} />
          </div>
        )}
        {taskId && run?.error && (
          <span className="hidden truncate text-xs text-destructive lg:inline">{run.error}</span>
        )}
      </div>
      <div className="flex shrink-0 items-center gap-2 px-3">
        {taskId && <LiveTaskStats taskId={taskId} />}
        {taskId && run && (
          <>
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
            <RunInfoDrawer
              run={run}
              events={events}
              open={infoOpen}
              onOpenChange={setInfoOpen}
            />
          </>
        )}
        {pendingApprovals > 0 && (
          <Badge variant="outline" className="border-amber-500/30 bg-amber-500/15 text-amber-700 dark:text-amber-400">
            <TriangleAlertIcon />
            {pendingApprovals} 待审批
          </Badge>
        )}
        <Badge variant="outline" className={CONN_BADGE[conn].className}>
          {CONN_BADGE[conn].label}
        </Badge>
        <Button variant="ghost" size="icon" title="控制台令牌" onClick={onOpenTokenDialog}>
          <KeyRoundIcon />
        </Button>
      </div>
    </header>
  )
}
