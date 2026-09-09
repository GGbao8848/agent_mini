import * as React from "react"

import { TaskIdChip } from "@/components/runs/task-stats"
import { StatusBadge } from "@/components/runs/status-badge"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { Separator } from "@/components/ui/separator"
import { SidebarTrigger } from "@/components/ui/sidebar"
import { useCompactTask, useDeleteTask, useRun, useTask } from "@/hooks/use-console"
import { TERMINAL_RUN_STATUSES } from "@/lib/types"
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
  ArchiveIcon,
  CircleAlertIcon,
  CircleCheckIcon,
  Loader2Icon,
  Trash2Icon,
  TriangleAlertIcon,
} from "lucide-react"
import { toast } from "sonner"
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

export function SiteHeader({
  title,
  conn,
  pendingApprovals,
  taskId,
}: {
  title: string
  conn: ConnState
  pendingApprovals: number
  /** The currently open conversation (from the "新建任务" view); live stats shown when set. */
  taskId?: string | null
}) {
  const [removing, setRemoving] = React.useState(false)
  const [compacting, setCompacting] = React.useState(false)
  const deleteTask = useDeleteTask()
  const compact = useCompactTask()

  // The open conversation's live state: task → active run. The event stream
  // and activity trail live in the chat thread itself now (no run drawer).
  const { data: task } = useTask(taskId ?? null)
  const activeRunId = task?.active_run_id ?? null
  const { data: run } = useRun(activeRunId)
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
          // inline-block (not inline) so truncate can actually clip; the raw
          // error can be a 600-char JSON blob that would blow up the header.
          <span className="hidden max-w-md truncate text-xs text-destructive lg:inline-block" title={run.error}>
            {run.error.length > 140 ? `${run.error.slice(0, 140)}…` : run.error}
          </span>
        )}
      </div>
      <div className="flex shrink-0 items-center gap-2 px-3">
        {/* Context stats moved into the composer's capacity gauge; the header
            keeps only the conversation id chip. */}
        {taskId && <TaskIdChip taskId={taskId} />}{taskId && run && (
          <>
            <Button
              variant="ghost"
              size="sm"
              disabled={compact.isPending}
              title="把对话历史压缩为摘要，长对话变慢时使用；原始记录存到任务目录"
              onClick={() => setCompacting(true)}
            >
              {compact.isPending ? (
                <Loader2Icon className="size-4 animate-spin" data-icon="inline-start" />
              ) : (
                <ArchiveIcon data-icon="inline-start" />
              )}
              压缩
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
          </>
        )}
        <AlertDialog open={compacting} onOpenChange={(open) => !open && setCompacting(false)}>
          <AlertDialogContent>
            <AlertDialogHeader>
              <AlertDialogTitle>压缩对话上下文？</AlertDialogTitle>
              <AlertDialogDescription>
                把历史消息压缩为一份摘要（原文存到任务目录），后续每轮对话显著变快；
                分身对久远细节的记忆会变模糊。运行中的任务需先停止。
              </AlertDialogDescription>
            </AlertDialogHeader>
            <AlertDialogFooter>
              <AlertDialogCancel>取消</AlertDialogCancel>
              <AlertDialogAction
                disabled={compact.isPending}
                onClick={() => {
                  if (!taskId) return
                  compact.mutate(taskId, {
                    onSuccess: (r) => {
                      setCompacting(false)
                      if (r.compacted) {
                        toast.success(`已压缩：${r.before} 条 → ${r.after} 条`)
                      } else {
                        toast.info(r.reason ?? "无需压缩")
                      }
                    },
                    onError: () => setCompacting(false),
                  })
                }}
              >
                压缩
              </AlertDialogAction>
            </AlertDialogFooter>
          </AlertDialogContent>
        </AlertDialog>
        {pendingApprovals > 0 && (
          <Badge variant="outline" className="border-amber-500/30 bg-amber-500/15 text-amber-700 dark:text-amber-400">
            <TriangleAlertIcon />
            {pendingApprovals} 待审批
          </Badge>
        )}
        <Badge variant="outline" className={CONN_BADGE[conn].className}>
          {CONN_BADGE[conn].label}
        </Badge>
      </div>
    </header>
  )
}
